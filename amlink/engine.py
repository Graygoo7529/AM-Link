"""AM-Link refactor: mandatory episode visibility plus bounded Reflection/Search loops."""
from __future__ import annotations

import re
import threading
import time

from pydantic import ValidationError

from .errors import MemoryError
from .reflection import prepare_mutation, prompt
from .schemas import AddRequest, BfsAction, EvictAction, Mutation, QueryExpansion, SearchRequest, Selection
from .text import CHANGE, COMPLEX, FORGET, digest, dumps, excerpt, terms


def _tool(name, description, schema):
    return {"name": name, "description": description, "parameters": schema}


class Engine:
    def __init__(self, config, store, providers, observer):
        self.config, self.store, self.providers, self.observer = config, store, providers, observer
        self.locks = [threading.Lock() for _ in range(128)]
        if config.embedding_enabled:
            self.store.metadata("embedding_fingerprint", providers.embedding_fingerprint)

    def _lock(self, user):
        return self.locks[int(digest(user)[:8], 16) % len(self.locks)]

    @staticmethod
    def _response(request):
        return {"success": True, **{key: getattr(request, key) for key in ("user_id", "session_id", "request_id")}}

    @staticmethod
    def _view(row):
        keys = ("ref", "kind", "text", "source_refs", "status", "role", "source_time", "session_id", "ordinal",
                "time_expression", "time_start", "time_end", "created_at")
        return {key: row[key] for key in keys if key in row}

    @staticmethod
    def _model_row(row, query="", text_limit=720):
        """Make a bounded, still-readable narrative view for one model call."""
        value = Engine._view(row)
        if isinstance(value.get("text"), str):
            value["text"] = excerpt(value["text"], text_limit, query)
        if isinstance(value.get("source_refs"), list):
            value["source_refs"] = value["source_refs"][:24]
        return value

    def _model_context(self, context):
        """Bound model-visible context while retaining semantic refs and paths.

        The stored Reflection workspace and observation artifacts keep full text.
        This projection is the deliberate narrative budget sent to a model.
        """
        if not isinstance(context, dict):
            return {}
        result = {}
        for key in ("question", "new_refs", "frontier", "depths"):
            if key in context:
                result[key] = context[key]
        result["question"] = excerpt(str(result.get("question", "")), 1600)
        references = context.get("references", {})
        result["references"] = {
            ref: {k: excerpt(str(v), 420) if k == "narrative" else v for k, v in value.items()}
            for ref, value in list(references.items())[:24]
        }
        items = context.get("items", {})
        result["items"] = {
            ref: self._model_row(value, result["question"], 480)
            for ref, value in list(items.items())[:24]
        }
        sources = context.get("sources", [])
        result["sources"] = [self._model_row(value, result["question"], 400)
                              for value in sources[:16]]
        result["edges"] = list(context.get("edges", []))[:48]
        return result

    def add(self, request: AddRequest):
        lock = self._lock(request.user_id)
        # Concurrent official Add calls are accepted at the API boundary, but
        # one user's Reflection watermark is advanced serially.
        lock.acquire()
        try:
            return self._add(request)
        finally:
            lock.release()

    def _add(self, request):
        started = time.monotonic()
        total_chars = sum(len(message.content) for message in request.messages)
        if total_chars > self.config.max_request_chars or len(request.messages) > self.config.max_request_messages:
            raise MemoryError("add_payload_too_large", 413)
        previous = self.store.state(request.user_id).get("last_session")
        with self.observer.span("store", "raw commit", inputs=request.model_dump()) as event:
            row, replay = self.store.start_add(request)
            self.observer.output(event, {"request_id": request.request_id, "replay": replay,
                                         "raw_refs": json_load(row.get("raw_refs", "[]"))}, kind="source", title="RawEvent 持久化")
        if replay == "cached":
            root = self.observer.current.get()
            if root is not None:
                root["replay"] = "cached"
            return self._response(request)
        if time.monotonic() - started >= self.config.request_seconds:
            raise MemoryError("request_deadline", 504)
        raw_refs = json_load(row.get("raw_refs", "[]"))
        episode = self._ensure_episode(request, row, raw_refs, started)
        pending = self.store.raw(request.user_id, pending=True)
        signal = (previous is not None and previous != request.session_id) or any(
            FORGET.search(source["text"]) or CHANGE.search(source["text"]) for source in pending)
        threshold = len(pending) >= self.config.reflection_threshold or sum(len(source["text"]) for source in pending) >= self.config.reflection_chars
        trigger = self.config.mode == "graph" and (signal or threshold)
        self._observe_add_state(request, pending, trigger, episode)
        if not trigger:
            self.store.finish_minimum(request.user_id, request.request_id)
            return self._response(request)
        self._run_reflection(request, pending, started)
        return self._response(request)

    def _ensure_episode(self, request, row, raw_refs, started):
        if row.get("episode_ref"):
            return self.store.get(request.user_id, row["episode_ref"])
        sources = [self.store.get(request.user_id, ref) for ref in raw_refs]
        sources = [source for source in sources if source]
        if not sources:
            raise MemoryError("raw_source_missing", 503)
        first, last = sources[0]["ordinal"], sources[-1]["ordinal"]
        label = re.sub(r"[^a-zA-Z0-9_-]+", "-", request.session_id).strip("-").lower()[:28] or "session"
        ref = f"memory:episode-{label}-{first}-{digest(raw_refs)[:10]}"
        text = "\n".join(f"[{source['role']}][session={source['session_id']}][ordinal={source['ordinal']}] {source['text']}" for source in sources)
        episode = {"ref": ref, "kind": "episode", "text": text, "source_refs": raw_refs,
                   "ordinal_start": first, "ordinal_end": last}
        if self.config.embedding_enabled:
            with self.observer.span("index", "episode embedding", inputs=episode) as event:
                vector = self.providers.embed([text], started + self.config.request_seconds)[0]
                self.observer.output(event, {"ref": ref, "dimensions": len(vector)}, kind="memory", title="最小 episode 向量")
        else:
            vector = []
        with self.observer.span("extract", "minimum episode projection", inputs=episode) as event:
            self.store.commit_episode(request.user_id, request.request_id, episode, vector, self.providers.embedding_fingerprint)
            self.observer.output(event, episode, kind="memory", title="逐 Add 可检索 episode")
        return self.store.get(request.user_id, ref)

    def _observe_add_state(self, request, pending, trigger, episode):
        with self.observer.span("extract", "reflection trigger decision", inputs={"pending": len(pending), "episode": episode and episode.get("ref")}) as event:
            self.observer.output(event, {"trigger": trigger, "pending_count": len(pending),
                                         "pending_chars": sum(len(row["text"]) for row in pending)}, kind="context", title="Reflection 触发判断")

    def _run_reflection(self, request, pending, started):
        user = request.user_id
        deadline = started + self.config.request_seconds
        state = self.store.state(user)
        context = state.get("context") or {}
        if not context.get("new_refs") or set(context.get("new_refs", [])) != {row["ref"] for row in pending}:
            context = self._reflection_context(user, pending, deadline)
        self.store.save_workspace(user, state="maintenance", context=context)
        tools = [
            _tool("reflection_search", "Search structured memory and add related References to the Reflection context.",
                  {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"], "additionalProperties": False}),
            _tool("reflection_evict", "Evict loaded References from the active context; never delete memory.",
                  {"type": "object", "properties": {"refs": {"type": "array", "items": {"type": "string"}}}, "required": ["refs"], "additionalProperties": False}),
            _tool("reflection_mutation", "Commit grounded high-level nodes and valid relations. Do not emit the mandatory episode again, do not link to raw refs, and do not link episode to episode. An empty mutation is valid.",
                  Mutation.model_json_schema()),
            _tool("reflection_stop", "Stop because the current context is sufficient and no additional mutation is needed.",
                  {"type": "object", "properties": {}, "additionalProperties": False}),
        ]
        for step in range(self.config.reflection_steps):
            if time.monotonic() >= deadline:
                raise MemoryError("request_deadline", 504)
            payload = {"working": [self._model_row(row, request.session_id, 560) for row in pending],
                       "context": self._model_context(context),
                       "watermark": state["accepted_through"], "step": step}
            with self.observer.span("reflection", "reflection tool decision", inputs=payload) as event:
                name, arguments = self.providers.tool("reflection", prompt(), payload, tools, deadline)
                self.observer.output(event, {"tool": name, "arguments": arguments}, kind="context", title="Reflection 工具调用")
            if name == "reflection_search":
                question = str(arguments.get("question", "")).strip()
                if not question:
                    raise MemoryError("reflection_search_invalid", 502)
                refs = self._search_refs(user, question, context, deadline, mode="reflection")
                self._add_context_refs(user, context, refs, deadline)
                self.store.save_workspace(user, state="maintenance", context=context)
                continue
            if name == "reflection_evict":
                action = EvictAction.model_validate(arguments)
                allowed = set(context.get("items", {})) | set(context.get("references", {}))
                context["items"] = {ref: value for ref, value in context.get("items", {}).items() if ref not in set(action.refs)}
                context["references"] = {ref: value for ref, value in context.get("references", {}).items() if ref not in set(action.refs)}
                with self.observer.span("reflection", "reflection evict", inputs={"refs": action.refs}) as event:
                    self.observer.output(event, {"evicted": [ref for ref in action.refs if ref in allowed]}, kind="context", title="Reflection Evict")
                self.store.save_workspace(user, state="maintenance", context=context)
                continue
            if name == "reflection_mutation":
                with self.observer.span("reflection", "reflection mutation validate", inputs=arguments) as event:
                    prepared = prepare_mutation(arguments, user=user, request_id=request.request_id, number=0,
                                                context=context, store=self.store)
                    self.observer.output(event, prepared, kind="memory", title="Reflection Mutation 校验结果")
                self._commit_reflection(user, prepared, state["accepted_through"], deadline)
                return
            if name == "reflection_stop":
                prepared = {"items": [], "links": [], "forget": []}
                self._commit_reflection(user, prepared, state["accepted_through"], deadline)
                return
            raise MemoryError("unknown_reflection_tool", 502)
        raise MemoryError("reflection_tool_budget", 504)

    def _commit_reflection(self, user, prepared, watermark, deadline):
        vectors = {}
        if self.config.embedding_enabled and prepared["items"]:
            missing = [item for item in prepared["items"] if item["kind"] != "episode"]
            for start in range(0, len(missing), self.config.embedding_batch):
                group = missing[start:start + self.config.embedding_batch]
                with self.observer.span("index", "memory item embeddings", inputs=[item["ref"] for item in group]) as event:
                    values = self.providers.embed([item["text"] for item in group], deadline)
                    vectors.update({item["ref"]: vector for item, vector in zip(group, values, strict=True)})
                    self.observer.output(event, {"refs": list(vectors), "dimensions": self.config.embedding_dimensions}, kind="memory", title="结构化节点向量")
        with self.observer.span("store", "reflection mutation commit", inputs=prepared) as event:
            self.store.commit_mutation(user, prepared, watermark=watermark,
                                       fingerprint=self.providers.embedding_fingerprint, vectors=vectors)
            self.observer.output(event, {"mutation": prepared, "watermark": watermark}, kind="memory", title="Reflection Mutation 提交")

    def _reflection_context(self, user, pending, deadline):
        query = "\n".join(row["text"] for row in pending)
        refs = self._search_refs(user, query, {}, deadline, mode="reflection")
        context = {"question": query, "new_refs": [row["ref"] for row in pending], "sources": [self._view(row) for row in pending],
                   "memories": [], "edges": [], "references": {}, "items": {}}
        for row in refs[:self.config.old_candidates]:
            if row["ref"] in context["new_refs"]:
                continue
            context["references"][row["ref"]] = self._reference(row, query, "query")
            context["items"][row["ref"]] = self._view(row)
            context["memories"].append(self._view(row))
            for source in row.get("source_refs", []):
                source_row = self.store.get(user, source)
                if source_row and source not in {r["ref"] for r in context["sources"]}:
                    context["sources"].append(self._view(source_row))
        self._add_context_refs(user, context, refs[:self.config.old_candidates], deadline)
        return context

    def _reference(self, row, query, via):
        return {"ref": row["ref"], "kind": row["kind"], "label": row["ref"].split(":", 1)[-1],
                "narrative": f"{via} 命中 {row['kind']} {row['ref']}：{excerpt(row['text'], self.config.preview_chars, query)}",
                "source_refs": row.get("source_refs", []), "status": row.get("status", "active")}

    def _add_context_refs(self, user, context, refs, deadline):
        for row in refs:
            if not row or row["ref"].startswith("raw:"):
                continue
            context.setdefault("question", "")
            context.setdefault("references", {})[row["ref"]] = self._reference(row, context.get("question", ""), row.get("via", "inspect"))
            context.setdefault("items", {})[row["ref"]] = self._view(row)
            if self.store.get(user, row["ref"]):
                for source_ref in row.get("source_refs", []):
                    source = self.store.get(user, source_ref)
                    if source and source_ref not in {item["ref"] for item in context.setdefault("sources", [])}:
                        context["sources"].append(self._view(source))
                for edge in self.store.edges(user, row["ref"]):
                    context.setdefault("edges", []).append({key: edge[key] for key in ("from_ref", "to_ref", "relation", "source_refs")})

    def _model_json(self, purpose, payload, deadline, fallback_prompt):
        if hasattr(self.providers, "tool"):
            name, args = self.providers.tool(purpose, fallback_prompt, payload, [
                _tool(purpose, "Return the structured result.", {"type": "object", "additionalProperties": True})], deadline)
            return args
        return self.providers.json(purpose, fallback_prompt, payload, deadline)

    def _search_refs(self, user, query, context, deadline, *, mode="search"):
        branches = [query]
        if mode == "search" and self.config.mode == "graph" and self.config.search_model and (COMPLEX.search(query) or len(query) > 100):
            payload = {"question": query, "context": self._model_context(context)}
            prompt_text = "Expand the retrieval question into up to three concise search expressions. Never answer."
            if hasattr(self.providers, "tool"):
                name, data = self.providers.tool("query_expansion", prompt_text, payload, [_tool(
                    "query_expansion", "Produce retrieval expressions.", {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}, "required": ["queries"], "additionalProperties": False})], deadline)
            else:
                data = self.providers.json("query_expansion", prompt_text, payload, deadline)
            try:
                expansion = QueryExpansion.model_validate(data)
            except ValidationError:
                raise MemoryError("query_expansion_invalid", 502) from None
            branches += expansion.queries
        candidates = {}
        for branch in dict.fromkeys(branches):
            lexical = self.store.lexical(user, branch, self.config.candidate_limit)
            with self.observer.span("retrieve", "query.lexical", inputs={"query": branch, "mode": mode}) as event:
                self.observer.candidates(event, [self._view(row) | {"score": row["score"], "channel": "bm25"} for row in lexical])
            for row in lexical:
                current = candidates.setdefault(row["ref"], {**row, "lineage": []})
                current["score"] = current.get("score", 0) + row["score"]
                current["lineage"].append({"branch": branch, "channel": "bm25", "rank": row.get("lexical_rank")})
            if self.config.embedding_enabled:
                vectors = list(self.store.vector_rows(user, self.providers.embedding_fingerprint))
                if vectors:
                    query_vector = self.providers.embed([branch], deadline)[0]
                    scored = sorted(((sum(a * b for a, b in zip(vector, query_vector, strict=True)), row)
                                     for row, vector in vectors), key=lambda pair: (-pair[0], pair[1]["ref"]))[:self.config.candidate_limit]
                    semantic = []
                    for rank, (score, row) in enumerate(scored, 1):
                        if score <= 0:
                            continue
                        current = candidates.setdefault(row["ref"], {**row, "lineage": []})
                        current["score"] = current.get("score", 0) + 1 / (60 + rank)
                        current["lineage"].append({"branch": branch, "channel": "embedding", "rank": rank, "cosine": score})
                        semantic.append(self._view(row) | {"score": score, "channel": "embedding"})
                    with self.observer.span("retrieve", "query.embedding", inputs={"query": branch, "mode": mode}) as event:
                        self.observer.candidates(event, semantic)
        result = sorted(candidates.values(), key=lambda row: (-row["score"], row["ref"]))[:self.config.candidate_limit]
        if len(result) > self.config.seed_count * 2 and self.config.mode == "graph" and self.config.search_model:
            result = self._select_refs(user, query, result, context, deadline, reason="query")
        with self.observer.span("retrieve", "query.merge", inputs={"query": query, "branches": branches}) as event:
            self.observer.output(event, {"references": [self._reference(row, query, "query") for row in result], "lineage": {row["ref"]: row.get("lineage", []) for row in result}}, kind="result", title="Query 合并后的 References")
        return result

    def _select_refs(self, user, query, candidates, context, deadline, *, reason):
        model_candidates = candidates[:self.config.select_candidate_limit]
        previews = []
        for row in model_candidates:
            preview = self._model_row(row, query, 560)
            preview["source_refs"] = preview.get("source_refs", [])[:8]
            preview.update({
                "narrative": excerpt(self._reference(row, query, reason)["narrative"], 520, query),
                "lineage": [{**lineage, "branch": excerpt(str(lineage.get("branch", "")), 240, query)}
                             for lineage in row.get("lineage", [])[:4]]})
            previews.append(preview)
        with self.observer.span("select", "select references", inputs={"query": query, "reason": reason,
            "candidate_count": len(candidates), "model_candidate_count": len(model_candidates),
            "candidate_budget_truncated": len(model_candidates) < len(candidates), "candidates": previews}) as event:
            prompt_text = "Select and order the source-grounded memory References relevant to the question. Use only supplied refs; preserve independent quantities, people, conflicts and necessary context. Return only refs."
            if hasattr(self.providers, "tool"):
                name, data = self.providers.tool("select", prompt_text, {"query": query,
                    "context": self._model_context(context), "candidates": previews}, [_tool(
                    "select", "Return an ordered subset of supplied refs.", {"type": "object", "properties": {"refs": {"type": "array", "items": {"type": "string"}}}, "required": ["refs"], "additionalProperties": False})], deadline)
            else:
                data = self.providers.json("select", prompt_text, {"query": query,
                    "context": self._model_context(context), "candidates": previews}, deadline)
            try:
                selected = Selection.model_validate(data).refs
            except ValidationError:
                raise MemoryError("selection_invalid", 502) from None
            allowed = {row["ref"] for row in model_candidates}
            invalid = [ref for ref in selected if ref not in allowed]
            selected = list(dict.fromkeys(ref for ref in selected if ref in allowed))
            if not selected:
                raise MemoryError("selection_unknown_ref", 502)
            self.observer.candidates(event, previews, selected)
            self.observer.output(event, {"candidate_count": len(candidates),
                "model_candidate_count": len(model_candidates),
                "candidate_budget_truncated": len(model_candidates) < len(candidates),
                "selected_refs": selected, "invalid_refs": invalid,
                "duplicate_refs_removed": len(selected) + len(invalid) < len(data.get("refs", []))},
                kind="context", title="Select 候选预算")
            return [next(row for row in model_candidates if row["ref"] == ref) for ref in selected]

    def search(self, request: SearchRequest):
        lock = self._lock(request.user_id)
        if not lock.acquire(blocking=False):
            raise MemoryError("user_busy", 425)
        try:
            return self._search(request)
        finally:
            lock.release()

    def _search(self, request):
        deadline = time.monotonic() + self.config.request_seconds
        if len(request.query) > self.config.batch_chars:
            raise MemoryError("search_query_budget", 413)
        context = {"question": request.query, "references": {}, "items": {}, "edges": [], "frontier": [], "depths": {}}
        seeds = self._search_refs(request.user_id, request.query, context, deadline)
        for row in seeds:
            context["references"][row["ref"]] = self._reference(row, request.query, "query")
            context["frontier"].append(row["ref"])
            context["depths"][row["ref"]] = 0
        visited, pool = set(), {row["ref"]: row for row in seeds}
        for step in range(self.config.search_steps):
            if not context["frontier"]:
                break
            if len(context["references"]) >= self.config.max_nodes:
                break
            action = self._next_bfs_action(request.user_id, request.query, context, deadline)
            if action.action == "stop":
                break
            ref = action.ref
            if not ref or ref not in context["references"] or ref in visited or ref not in context["frontier"]:
                with self.observer.span("retrieve", "bfs invalid or repeated action", inputs={"action": action.model_dump(), "frontier": context["frontier"]}) as event:
                    self.observer.output(event, {"action": action.model_dump(), "handled": "stop", "reason": "ref_not_in_active_frontier"}, kind="context", title="BFS 非活动引用收束")
                break
            context["frontier"] = [candidate for candidate in context["frontier"] if candidate != ref]
            depth = context["depths"].get(ref, 0)
            visited.add(ref)
            if action.action == "inspect":
                value = self.inspect(request.user_id, ref)
                if value:
                    node = self.store.get(request.user_id, ref)
                    context["items"][ref] = self._view(node)
                    pool[ref] = {**node, "score": pool.get(ref, {}).get("score", 0.01), "path": [ref]}
                    for edge in value["links"]:
                        other = edge["to_ref"] if edge["from_ref"] == ref else edge["from_ref"]
                        neighbor = self.store.get(request.user_id, other)
                        if neighbor and other not in visited and depth < self.config.max_hops and len(context["references"]) < self.config.max_nodes:
                            context["references"][other] = self._reference(neighbor, request.query, "inspect")
                            context["frontier"].append(other)
                            context["depths"][other] = depth + 1
                            pool.setdefault(other, {**neighbor, "score": pool[ref]["score"] * 0.8, "path": [ref, other]})
            else:
                links = self.backlinks(request.user_id, ref)
                neighbors = []
                for edge in links:
                    other = edge["from_ref"] if edge["to_ref"] == ref else edge["to_ref"]
                    node = self.store.get(request.user_id, other)
                    if node and other not in visited and depth < self.config.max_hops:
                        neighbors.append({**node, "score": pool.get(ref, {}).get("score", 0.01) * 0.8,
                                          "path": [ref, other], "via": edge["relation"]})
                truncated = len(neighbors) > self.config.max_neighbors
                if truncated and self.config.mode == "graph" and self.config.search_model:
                    neighbors = self._select_refs(request.user_id, request.query, neighbors[:self.config.candidate_limit], context, deadline, reason="backlink")
                neighbors = neighbors[:self.config.max_neighbors]
                if truncated:
                    with self.observer.span("retrieve", "bfs neighbor budget", inputs={"ref": ref, "count": len(neighbors), "max_neighbors": self.config.max_neighbors}) as event:
                        self.observer.output(event, {"ref": ref, "truncated": True, "selected": [row["ref"] for row in neighbors]}, kind="context", title="BFS 邻居预算裁剪")
                for neighbor in neighbors:
                    if len(context["references"]) >= self.config.max_nodes:
                        break
                    other = neighbor["ref"]
                    context["references"][other] = self._reference(neighbor, request.query, "backlink")
                    context["frontier"].append(other)
                    context["depths"][other] = depth + 1
                    pool.setdefault(other, neighbor)
            context["frontier"] = list(dict.fromkeys(context["frontier"]))
            with self.observer.span("retrieve", "bfs step", inputs={"step": step, "action": action.model_dump(), "context_refs": list(context["references"] )}) as event:
                self.observer.output(event, {"action": action.model_dump(), "visited": sorted(visited), "frontier": context["frontier"]}, kind="context", title="BFS 上下文增量")
        rows = self._assemble(request.user_id, request.query, list(pool.values()), request.top_k, request.query)
        with self.observer.span("context", "search final pack", inputs=context) as event:
            self.observer.output(event, {"data": rows, "visited": sorted(visited), "steps": len(visited)}, kind="result", title="Search 最终证据装箱")
        return {"data": rows}

    def _next_bfs_action(self, user, query, context, deadline):
        if self.config.mode != "graph" or not self.config.search_model:
            return BfsAction(action="inspect", ref=context["frontier"][0])
        tools = [_tool("bfs_action", "Choose one known reference to inspect, backlinks, or stop.",
                       {"type": "object", "properties": {"action": {"type": "string", "enum": ["inspect", "backlinks", "stop"]}, "ref": {"type": "string"}, "reason": {"type": "string"}}, "required": ["action"], "additionalProperties": False})]
        with self.observer.span("retrieve", "bfs action", inputs={"query": query, "context": context}) as event:
            name, data = self.providers.tool("bfs", "Explore the supplied memory graph. Choose inspect/backlinks only for a ref in context.frontier; never reuse a visited ref. Stop when evidence is sufficient. Never answer.", {"query": query, "context": self._model_context(context)}, tools, deadline)
            try:
                action = BfsAction.model_validate(data)
            except ValidationError:
                raise MemoryError("bfs_action_invalid", 502) from None
            self.observer.output(event, action.model_dump(), kind="context", title="BFS 模型决策")
            return action

    def inspect(self, user, ref):
        with self.observer.span("retrieve", "memory.inspect", inputs={"ref": ref}) as event:
            node = self.store.get(user, ref)
            if node is None:
                self.observer.output(event, {"ref": ref, "available": False}, kind="result", title="Inspect 空结果")
                return None
            links = self.store.edges(user, ref)
            value = {"reference": self._reference(node, "", "inspect"), "node": self._view(node), "links": links, "source_refs": node["source_refs"]}
            self.observer.output(event, value, kind="context", title="Inspect Item 与正向 References")
            return value

    def backlinks(self, user, ref):
        with self.observer.span("retrieve", "memory.backlinks", inputs={"ref": ref}) as event:
            links = self.store.edges(user, ref, incoming=True) if self.store.get(user, ref) else []
            values = []
            for edge in links:
                other = edge["from_ref"] if edge["to_ref"] == ref else edge["to_ref"]
                node = self.store.get(user, other)
                if node:
                    values.append({"reference": self._reference(node, "", "backlink"), "edge": edge})
            self.observer.output(event, values, kind="context", title="Backlink 反向 References")
            return links

    def _assemble(self, user, query, rows, top_k, preferred_query):
        result, used_sources, total = [], set(), 0
        for row in sorted(rows, key=lambda value: (-value.get("score", 0), value["ref"])):
            node = self.store.get(user, row["ref"])
            if not node or node["ref"] in {item["id"] for item in result}:
                continue
            if node["status"] == "superseded" and not re.search(r"histor|previous|earlier|以前|历史", preferred_query, re.I):
                continue
            parts = [f"[{node['kind']}][{node['ref']}][status={node['status']}] {node['text']}"]
            source_refs = set(node.get("source_refs", []))
            for ref in sorted(source_refs):
                source = self.store.get(user, ref)
                if not source:
                    continue
                parts.append(f"[source={ref}][role={source['role']}][session={source['session_id']}][ordinal={source['ordinal']}] {source['text']}")
                used_sources.add(ref)
                for state in self.store.source_states(user, ref):
                    parts.append(f"[来源状态 {state['ref']}={state['status']}] {state['text']}")
            related = self.store.edges(user, node["ref"]) + self.store.edges(user, node["ref"], incoming=True)
            if related:
                parts.append("关系：" + dumps([{key: edge[key] for key in ("from_ref", "to_ref", "relation")} for edge in related]))
            content = "\n".join(parts)
            if len(content) > self.config.result_chars:
                content = excerpt(content, self.config.result_chars, query)
            if len(result) >= top_k or total + len(content) > self.config.context_chars:
                continue
            result.append({"id": node["ref"], "content": content, "score": round(row.get("score", 0.01), 8), "created_at": node["created_at"]})
            total += len(content)
        return result


def json_load(value):
    if isinstance(value, list):
        return value
    try:
        return __import__("json").loads(value or "[]")
    except (TypeError, ValueError):
        return []
