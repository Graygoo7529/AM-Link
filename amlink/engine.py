"""AM-Link refactor: mandatory episode visibility plus bounded Reflection/Search loops."""
from __future__ import annotations

import re
import threading
import time

from pydantic import ValidationError

from .errors import MemoryError
from .evidence import complementary_passages, episode_label, episode_text, passages, slug, source_date
from .providers import tool_body
from .reflection import parse_mutation, prepare_mutation, prompt
from .schemas import AddRequest, BfsAction, EvictAction, Mutation, QueryExpansion, SearchRequest, Selection
from .text import CHANGE, COMPLEX, FORGET, digest, dumps, excerpt, terms


def _tool(name, description, schema):
    # Strict tool mode requires every object property to be required and
    # forbids additional properties. Optional Pydantic values remain nullable.
    def strict(value):
        if isinstance(value, list):
            return [strict(entry) for entry in value]
        if not isinstance(value, dict):
            return value
        result = {key: strict(entry) for key, entry in value.items()}
        if result.get("type") == "object":
            properties = result.get("properties", {})
            result["required"] = list(properties)
            result["additionalProperties"] = False
        return result

    return {"name": name, "description": description,
            "parameters": strict(schema), "strict": True}


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
        value = {key: row[key] for key in keys if key in row}
        if row.get("source_time") is not None:
            value["source_time_utc"] = source_date(row["source_time"])
        return value

    @staticmethod
    def _model_row(row, query="", text_limit=720):
        """Make a bounded, still-readable narrative view for one model call."""
        value = Engine._view(row)
        if isinstance(value.get("text"), str):
            value["text"] = excerpt(value["text"], text_limit, query)
        if isinstance(value.get("source_refs"), list):
            value["source_refs"] = value["source_refs"][:64]
        return value

    def _model_context(self, context, max_chars=None):
        """Bound the whole context projection, with explicit omitted ref lists.

        Most recently read items are retained first, so a tool result can affect
        the next decision. Full working messages are supplied separately.
        """
        limit = max(0, min(self.config.context_chars, max_chars if max_chars is not None else self.config.context_chars))
        result = {"question": excerpt(str(context.get("question", "")), 1200),
                  "references": {}, "items": {}, "sources": [], "edges": []}
        if len(dumps(result)) > limit:
            return {}
        refs = context.get("references", {})
        items = context.get("items", {})
        omitted = []
        # Reserve room for navigation and coverage metadata instead of filling
        # the entire budget with item text before any refs can be disclosed.
        for ref in dict.fromkeys([*reversed(items), *refs]):
            reference = dict(refs.get(ref, {}))
            if not reference and ref in items:
                reference = self._reference(items[ref], result["question"], "context")
            reference["narrative"] = excerpt(str(reference.get("narrative", "")), 700, result["question"])
            if isinstance(reference.get("evidence_fragments"), list):
                projected_fragments = []
                for fragment in reference["evidence_fragments"][:4]:
                    value = dict(fragment)
                    original_text = str(value.get("text", ""))
                    projected_text = excerpt(original_text, 520, result["question"])
                    value["text"] = projected_text
                    value["model_projection"] = {
                        "source_text_chars": len(original_text),
                        "shown_chars": len(projected_text),
                        "complete": projected_text == original_text,
                    }
                    projected_fragments.append(value)
                reference["evidence_fragments"] = projected_fragments
            result["references"][ref] = reference
            if ref in items:
                result["items"][ref] = self._model_row(items[ref], result["question"], 2400)
            if len(dumps(result)) > max(0, limit - 1500):
                result["references"].pop(ref, None)
                result["items"].pop(ref, None)
                omitted.append(ref)
        for edge in context.get("edges", []):
            if edge["from_ref"] in result["references"] or edge["to_ref"] in result["references"]:
                result["edges"].append(edge)
                if len(dumps(result)) > max(0, limit - 1000):
                    result["edges"].pop()
                    break
        for source in context.get("sources", []):
            value = self._model_row(source, result["question"], 240)
            result["sources"].append(value)
            if len(dumps(result)) > max(0, limit - 1000):
                result["sources"].pop()
                break
        visible = set(result["references"])
        navigation = {"frontier": [ref for ref in context.get("frontier", []) if ref in visible],
                      "depths": {ref: depth for ref, depth in context.get("depths", {}).items() if ref in visible},
                      "explored": [entry for entry in context.get("explored", []) if entry[0] in visible]}
        for key, value in navigation.items():
            result[key] = value
            if len(dumps(result)) > limit:
                result.pop(key)
        projection = {"omitted_refs": omitted, "source_count": len(context.get("sources", [])),
                      "shown_source_count": len(result["sources"]), "reason": "context_budget"}
        result["projection"] = projection
        if context.get("orientation_refs") or context.get("last_gate_error"):
            result["reflection_control"] = {
                "orientation_refs": list(context.get("orientation_refs", []))[:64],
                "last_gate_error": context.get("last_gate_error"),
                "instruction": "Risky mutations require Inspect or Backlink evidence in inspected_refs.",
            }
        if len(dumps(result)) > limit:
            result["projection"] = {"omitted_ref_count": len(omitted), "reason": "context_budget"}
        if len(dumps(result)) > limit:
            result.pop("reflection_control", None)
        if len(dumps(result)) > limit:
            return {}
        return result

    def add(self, request: AddRequest):
        started = time.monotonic()
        lock = self._lock(request.user_id)
        # Concurrent official Add calls are accepted at the API boundary, but
        # one user's Reflection watermark is advanced serially.
        if not lock.acquire(timeout=self.config.request_seconds):
            raise MemoryError("request_deadline", 504)
        try:
            return self._add(request, started)
        finally:
            lock.release()

    def _add(self, request, started=None):
        started = time.monotonic() if started is None else started
        deadline = started + self.config.request_seconds
        self._check_deadline(deadline)
        total_chars = sum(len(message.content) for message in request.messages)
        if total_chars > self.config.max_request_chars or len(request.messages) > self.config.max_request_messages:
            raise MemoryError("add_payload_too_large", 413)
        previous = self.store.state(request.user_id).get("last_session")
        with self.observer.span("store", "raw commit", inputs=request.model_dump()) as event:
            row, replay = self.store.start_add(request)
            self.observer.output(event, {"request_id": request.request_id, "replay": replay,
                                         "raw_refs": json_load(row.get("raw_refs", "[]"))}, kind="source", title="RawEvent 持久化")
        if replay == "cached" and row.get("episode_ref") and self.store.get(request.user_id, row["episode_ref"], include_blocked=True):
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
        required = row.get("reflection_watermark", 0)
        trigger = self.config.mode == "graph" and (signal or threshold or required > self.store.state(request.user_id)["settled_through"])
        self._observe_add_state(request, pending, trigger, episode)
        if not trigger:
            self._check_deadline(deadline)
            self.store.finish_minimum(request.user_id, request.request_id, require_vector=self.config.embedding_enabled)
            return self._response(request)
        target = max(required, self.store.state(request.user_id)["accepted_through"])
        self.store.require_reflection(request.user_id, request.request_id, target)
        batches = 0
        while pending and pending[0]["ordinal"] <= target:
            self._check_deadline(deadline)
            if batches >= self.config.max_batches:
                raise MemoryError("reflection_batch_budget", 504)
            batch, chars = [], 0
            for source in pending:
                if source["ordinal"] > target:
                    break
                size = len(dumps(self._view(source)))
                if batch and (len(batch) >= self.config.batch_messages or chars + size > self.config.batch_chars):
                    break
                batch.append(source)
                chars += size
            with self.observer.span("reflection", "reflection batch", inputs={
                    "target_watermark": target, "from_ordinal": batch[0]["ordinal"],
                    "through_ordinal": batch[-1]["ordinal"], "count": len(batch), "serialized_chars": chars}) as event:
                self._run_reflection(request, batch, started)
                self.observer.output(event, {"settled_through": batch[-1]["ordinal"], "remaining": len(pending) - len(batch)}, kind="context")
            batches += 1
            pending = self.store.raw(request.user_id, pending=True)
        self._check_deadline(deadline)
        self.store.finish_minimum(request.user_id, request.request_id, target, require_vector=self.config.embedding_enabled)
        return self._response(request)

    @staticmethod
    def _check_deadline(deadline):
        if time.monotonic() >= deadline:
            raise MemoryError("request_deadline", 504)

    def _tool_size(self, purpose, prompt_text, payload, tools):
        return len(dumps(tool_body(self.config, purpose, prompt_text, payload, tools)))

    def _call_tool(self, purpose, prompt_text, payload, tools, deadline):
        self._check_deadline(deadline)
        chars = self._tool_size(purpose, prompt_text, payload, tools)
        with self.observer.span("context", "model input projection", inputs={
                "purpose": purpose, "serialized_chars": chars, "limit": self.config.model_input_chars}) as event:
            if chars > self.config.model_input_chars:
                raise MemoryError("model_input_budget", 413)
            self.observer.output(event, {"within_budget": True}, kind="context")
        name, arguments = self.providers.tool(purpose, prompt_text, payload, tools, deadline)
        self._check_deadline(deadline)
        if name not in {tool["name"] for tool in tools}:
            raise MemoryError("model_unknown_tool", 502)
        return name, arguments

    def _mutation_tool_schema(self, context, source_refs=None):
        """Constrain model provenance to the sources visible in this workspace."""
        schema = Mutation.model_json_schema()
        source_refs = list(source_refs if source_refs is not None else
                           [row["ref"] for row in context.get("sources", [])])
        definitions = schema.get("$defs", {})
        item_properties = definitions.get("ItemChange", {}).get("properties", {})
        if "kind" in item_properties:
            item_properties["kind"]["enum"] = ["episode", "person", "entity", "concept", "event", "fact"]
            item_properties["kind"]["description"] = (
                "MemoryItem kind. The system-created minimum episode is immutable; only a distinct derived episode may be added.")
        if "time_start" in item_properties:
            item_properties["time_start"]["description"] = (
                "Optional normalized event date. Never copy the source message timestamp here.")
        if "time_end" in item_properties:
            item_properties["time_end"]["description"] = (
                "Optional normalized event end date. Never copy the source message timestamp here.")
        if "time_expression" in item_properties:
            item_properties["time_expression"]["description"] = (
                "Exact time phrase in source text; required whenever time_start or time_end is set.")
        for name in ("ItemChange", "LinkChange"):
            properties = definitions.get(name, {}).get("properties", {})
            if "source_refs" in properties:
                properties["source_refs"]["items"] = {
                    "type": "string", "enum": source_refs}
        forget = definitions.get("ForgetChange", {}).get("properties", {})
        if "source_refs" in forget:
            forget["source_refs"]["items"] = {"type": "string", "enum": source_refs}
        if "instruction_refs" in forget:
            instruction_refs = [
                ref for ref in source_refs
                if any(row["ref"] == ref and row.get("role") == "user"
                       for row in context.get("sources", []))
            ]
            forget["instruction_refs"]["items"] = {"type": "string", "enum": instruction_refs}
        properties = schema.setdefault("properties", {})
        properties["basis"] = {
            "type": "string",
            "enum": ["new_information", "update_existing", "resolve_conflict",
                      "identify_person", "add_relation"],
            "description": "Updates, conflicts, person identity and relation changes require a prior Inspect or Backlink."}
        properties["inspected_refs"] = {
            "type": "array", "items": {"type": "string"}, "maxItems": 64,
            "description": "Exact loaded memory refs examined before this mutation."}
        properties["no_prior_match"] = {
            "type": "boolean",
            "description": "True only when orientation found no old match for genuinely new information."}
        return schema

    def _ensure_episode(self, request, row, raw_refs, started):
        if row.get("episode_ref"):
            return self.store.get(request.user_id, row["episode_ref"])
        sources = [self.store.get(request.user_id, ref) for ref in raw_refs]
        sources = [source for source in sources if source]
        if not sources:
            raise MemoryError("raw_source_missing", 503)
        first, last = sources[0]["ordinal"], sources[-1]["ordinal"]
        label = slug(episode_label(sources), 64)
        ref = f"memory:episode-{label}-{first}-{digest(raw_refs)[:10]}"
        text = episode_text(sources)
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
        watermark = pending[-1]["ordinal"]
        context = self._reflection_context(user, pending, deadline)
        self.store.save_workspace(user, state="maintenance", context=context)
        def reflection_tools(source_refs=None):
            refs = list(context.get("references", {}))
            tools = [
                _tool("reflection_search", "Search structured memory and add related References to the Reflection context.",
                      {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"], "additionalProperties": False}),
                _tool("reflection_mutation", "Commit grounded high-level nodes and valid relations. Do not emit the mandatory episode again, do not link to raw refs, and do not link episode to episode. An empty mutation is valid.",
                      self._mutation_tool_schema(context, source_refs)),
                _tool("reflection_stop", "Stop because the current context is sufficient and no additional mutation is needed.",
                      {"type": "object", "properties": {}, "additionalProperties": False}),
            ]
            if refs:
                positions = {"type": "integer", "enum": list(range(len(refs)))}
                tools.insert(1, _tool("reflection_evict", "Evict supplied References from the active context by position; never delete memory.",
                      {"type": "object", "properties": {"reference_positions": {
                          "type": "array", "items": positions, "maxItems": len(refs)}},
                       "required": ["reference_positions"], "additionalProperties": False}))
                ref_schema = {"type": "object", "properties": {
                    "reference_position": positions}, "required": ["reference_position"],
                    "additionalProperties": False}
                tools.insert(2, _tool("reflection_inspect", "Read one supplied reference position, its sources and forward references into context.", ref_schema))
                tools.insert(3, _tool("reflection_backlinks", "Discover references pointing to one supplied reference position; candidates are selected when numerous, then inspect as needed.", ref_schema))
            return tools
        for step in range(self.config.reflection_steps):
            if time.monotonic() >= deadline:
                raise MemoryError("request_deadline", 504)
            payload = {"working": [self._view(row) for row in pending], "context": {},
                       "watermark": watermark, "step": step}
            context_limit = self.config.context_chars
            for _ in range(20):
                payload["context"] = self._model_context(context, context_limit)
                visible_sources = {row["ref"] for row in pending}
                visible_sources.update(row["ref"] for row in payload["context"].get("sources", []))
                tools = reflection_tools(sorted(visible_sources))
                if self._tool_size("reflection", prompt(), payload, tools) <= self.config.model_input_chars:
                    break
                context_limit = int(context_limit * 0.85)
            else:
                raise MemoryError("reflection_message_budget", 413)
            with self.observer.span("reflection", "reflection tool decision", inputs=payload) as event:
                name, arguments = self._call_tool("reflection", prompt(), payload, tools, deadline)
                self.observer.output(event, {"tool": name, "arguments": arguments}, kind="context", title="Reflection 工具调用")
            if name == "reflection_search":
                question = str(arguments.get("question", "")).strip()
                if not question:
                    raise MemoryError("reflection_search_invalid", 502)
                refs = self._search_refs(user, question, context, deadline, mode="reflection")
                self._add_context_refs(user, context, refs, deadline)
                self.store.save_workspace(user, state="maintenance", context=context)
                continue
            if name in {"reflection_inspect", "reflection_backlinks"}:
                position = arguments.get("reference_position")
                refs = list(context.get("references", {}))
                if position is not None:
                    if type(position) is not int or position < 0 or position >= len(refs):
                        raise MemoryError("reflection_invalid_position", 502)
                    ref = refs[position]
                else:
                    ref = arguments.get("ref")
                if ref not in context.get("references", {}):
                    raise MemoryError("reflection_unknown_reference", 502)
                action = "inspect" if name == "reflection_inspect" else "backlinks"
                self._explore(user, ref, action, context, context["question"], deadline)
                self._refresh_context(user, context, pending)
                self.store.save_workspace(user, state="maintenance", context=context)
                continue
            if name == "reflection_evict":
                positions = arguments.get("reference_positions")
                refs = list(context.get("references", {}))
                if positions is not None:
                    if not isinstance(positions, list) or any(
                            type(position) is not int or position < 0 or position >= len(refs)
                            for position in positions):
                        raise MemoryError("reflection_invalid_position", 502)
                    evicted_refs = list(dict.fromkeys(refs[position] for position in positions))
                else:
                    # Compatibility for deterministic providers from the test suite.
                    evicted_refs = EvictAction.model_validate(arguments).refs
                allowed = set(context.get("items", {})) | set(context.get("references", {}))
                context["items"] = {ref: value for ref, value in context.get("items", {}).items() if ref not in set(evicted_refs)}
                context["references"] = {ref: value for ref, value in context.get("references", {}).items() if ref not in set(evicted_refs)}
                context["edges"] = [edge for edge in context.get("edges", [])
                                    if edge["from_ref"] not in evicted_refs and edge["to_ref"] not in evicted_refs]
                self._refresh_context(user, context, pending)
                with self.observer.span("reflection", "reflection evict", inputs={"refs": evicted_refs}) as event:
                    self.observer.output(event, {"evicted": [ref for ref in evicted_refs if ref in allowed]}, kind="context", title="Reflection Evict")
                self.store.save_workspace(user, state="maintenance", context=context)
                continue
            if name == "reflection_mutation":
                with self.observer.span("reflection", "reflection mutation validate", inputs=arguments) as event:
                    try:
                        self._check_reflection_basis(arguments, context)
                    except MemoryError as error:
                        if error.code != "reflection_orientation_required":
                            raise
                        context["last_gate_error"] = error.code
                        self.observer.output(event, {"accepted": False, "reason": error.code,
                                                     "required": "Inspect or Backlink before this mutation"}, kind="context",
                                            title="Reflection 先看再写门槛")
                        self.store.save_workspace(user, state="maintenance", context=context)
                        continue
                    prepared = prepare_mutation(arguments, user=user, request_id=request.request_id, number=watermark,
                                                context=context, store=self.store)
                    self.observer.output(event, {"basis": arguments.get("basis", "new_information"),
                                                 "inspected_refs": arguments.get("inspected_refs", []),
                                                 "accepted": True}, kind="context", title="Reflection 先看再写门槛")
                    self.observer.output(event, prepared, kind="memory", title="Reflection Mutation 校验结果")
                self.store.save_workspace(user, state="mutation", context=context)
                self._commit_reflection(user, prepared, watermark, deadline, context)
                return
            if name == "reflection_stop":
                prepared = {"items": [], "links": [], "forget": []}
                self._commit_reflection(user, prepared, watermark, deadline, context)
                return
            raise MemoryError("unknown_reflection_tool", 502)
        raise MemoryError("reflection_tool_budget", 504)

    def _commit_reflection(self, user, prepared, watermark, deadline, context=None):
        vectors = {}
        if self.config.embedding_enabled and prepared["items"]:
            missing = prepared["items"]
            for start in range(0, len(missing), self.config.embedding_batch):
                group = missing[start:start + self.config.embedding_batch]
                with self.observer.span("index", "memory item embeddings", inputs=[item["ref"] for item in group]) as event:
                    values = self.providers.embed([item["text"] for item in group], deadline)
                    vectors.update({item["ref"]: vector for item, vector in zip(group, values, strict=True)})
                    self.observer.output(event, {"refs": list(vectors), "dimensions": self.config.embedding_dimensions}, kind="memory", title="结构化节点向量")
        with self.observer.span("store", "reflection mutation commit", inputs=prepared) as event:
            self._check_deadline(deadline)
            retained = context or {}
            # Retain navigation and old/new items, not the completed raw batch.
            for item in prepared["items"]:
                retained.setdefault("items", {})[item["ref"]] = item
                retained.setdefault("references", {})[item["ref"]] = self._reference(item, "", "mutation", user)
            retained["new_refs"] = []
            retained["sources"] = []
            retained["memories"] = list(retained.get("items", {}).values())
            for edge in prepared["links"]:
                if edge not in retained.setdefault("edges", []):
                    retained["edges"].append(edge)
            self.store.commit_mutation(user, prepared, watermark=watermark,
                                       fingerprint=self.providers.embedding_fingerprint, vectors=vectors, context=retained)
            self.observer.output(event, {"mutation": prepared, "watermark": watermark}, kind="memory", title="Reflection Mutation 提交")

    def _reflection_context(self, user, pending, deadline):
        # Orientation is a bounded discovery expression, never the entire backlog.
        query = excerpt("\n".join(row["text"] for row in pending), min(4000, self.config.batch_chars))
        context = self.store.state(user).get("context") or {"references": {}, "items": {}, "edges": []}
        context["question"] = query
        context["new_refs"] = [row["ref"] for row in pending]
        context["depths"], context["explored"], context["expanded_refs"] = {}, [], []
        self._refresh_context(user, context, pending)
        with self.observer.span("reflection", "reflection orientation", inputs={
                "question": query, "pending_refs": context["new_refs"]}) as event:
            refs = self._search_refs(user, query, context, deadline, mode="reflection")
            self.observer.output(event, {"references": [row["ref"] for row in refs],
                                         "count": len(refs), "orientation_only": True}, kind="context",
                                title="Reflection Orientation 旧记忆候选")
        self._add_context_refs(user, context, refs[:self.config.old_candidates], deadline)
        context["orientation_refs"] = [row["ref"] for row in refs[:self.config.old_candidates]]
        for ref in context["references"]:
            context["depths"].setdefault(ref, 0)
        return context

    @staticmethod
    def _check_reflection_basis(arguments, context):
        """Require graph evidence before risky derived mutations."""
        mutation, _ = parse_mutation(arguments)
        known = set(context.get("items", {})) | set(context.get("references", {}))
        targets = {item.ref for item in mutation.items if item.ref in known}
        targets.update(ref for link in mutation.links for ref in (link.from_ref, link.to_ref)
                       if ref in known)
        risky = mutation.basis != "new_information" or bool(mutation.links) or bool(targets)
        risky = risky or any(item.kind == "person" for item in mutation.items)
        inspected = set(mutation.inspected_refs)
        explored = {tuple(entry) for entry in context.get("explored", [])}
        actual = {ref for ref, action in explored if action in {"inspect", "backlinks"}}
        # Reading an unrelated node cannot authorize changes to old targets.
        # A new_information label/no_prior_match never bypasses a payload risk.
        if risky and (not (inspected & actual) or not targets.issubset(inspected & actual)):
            raise MemoryError("reflection_orientation_required", 409)

    def _reference(self, row, query, via, user=None):
        label = excerpt(re.sub(r"\[[^\]\n]*\]", "", row["text"]).strip(), 140, query)
        reference = {"ref": row["ref"], "kind": row["kind"], "label": label,
                "narrative": f"{via} 命中 {row['kind']} {row['ref']}：{excerpt(row['text'], self.config.preview_chars, query)}",
                "source_refs": row.get("source_refs", []), "status": row.get("status", "active")}
        fragments = row.get("reference_fragments")
        coverage = row.get("reference_coverage")
        if user and row["kind"] == "episode" and self.store.is_minimum_episode(user, row["ref"]):
            sources = self.store.raw(user, row.get("source_refs", []))
            branches = [query] + [str(entry.get("branch", "")) for entry in row.get("lineage", [])
                                  if isinstance(entry, dict) and entry.get("branch")]
            fragments, coverage = complementary_passages(sources, branches[:4],
                                                         min(2400, max(500, self.config.preview_chars * 2)),
                                                         max_fragments=4)
        if fragments:
            reference["evidence_fragments"] = fragments
        if coverage:
            reference["coverage"] = coverage
            reference["shown_ranges"] = [range_value
                                          for entry in coverage if entry.get("included")
                                          for range_value in (entry.get("shown_ranges") or
                                                              ([entry["shown_range"]]
                                                               if entry.get("shown_range") else []))]
        return reference

    def _add_context_refs(self, user, context, refs, deadline):
        # Higher-ranked candidates are loaded last so recency projection keeps
        # them first; an explicit Inspect likewise becomes the newest item.
        for row in reversed(refs):
            if not row or row["ref"].startswith("raw:"):
                continue
            context.setdefault("question", "")
            context.setdefault("references", {})[row["ref"]] = self._reference(row, context.get("question", ""), row.get("via", "inspect"), user)
            context.setdefault("items", {})[row["ref"]] = self._view(row)
            if self.store.get(user, row["ref"]):
                for source_ref in row.get("source_refs", []):
                    source = self.store.get(user, source_ref)
                    if source and source_ref not in {item["ref"] for item in context.setdefault("sources", [])}:
                        context["sources"].append(self._view(source))
                for edge in self.store.edges(user, row["ref"]):
                    value = self._edge_view(user, edge)
                    if value not in context.setdefault("edges", []):
                        context["edges"].append(value)
            context["memories"] = list(context["items"].values())

    def _edge_view(self, user, edge):
        labels = []
        for ref in (edge["from_ref"], edge["to_ref"]):
            node = self.store.get(user, ref)
            labels.append(excerpt(node["text"], 160) if node else ref)
        return {**edge, "narrative": f"{labels[0]} --{edge['relation']}--> {labels[1]}"}

    def _refresh_context(self, user, context, pending=()):
        """Refresh mutable nodes, prune evicted/deleted sources, keep working protected."""
        items = {}
        for ref in context.get("items", {}):
            node = self.store.get(user, ref)
            if node:
                items[ref] = self._view(node)
        context["items"] = items
        context["memories"] = list(items.values())
        refs = {}
        for ref in context.get("references", {}):
            node = self.store.get(user, ref)
            if node:
                refs[ref] = self._reference(node, context.get("question", ""), "context", user)
        context["references"] = refs
        sources = {row["ref"]: self._view(row) for row in pending}
        for item in items.values():
            for ref in item.get("source_refs", []):
                source = self.store.get(user, ref)
                if source:
                    sources[ref] = self._view(source)
        context["sources"] = list(sources.values())
        context["edges"] = [edge for edge in context.get("edges", [])
                            if self.store.get(user, edge["from_ref"]) and self.store.get(user, edge["to_ref"])]

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
                name, data = self._call_tool("query_expansion", prompt_text, payload, [_tool(
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
                current = candidates.setdefault(row["ref"], {**row, "score": 0, "lineage": []})
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
                        current = candidates.setdefault(row["ref"], {**row, "score": 0, "lineage": []})
                        current["score"] = current.get("score", 0) + 1 / (60 + rank)
                        current["lineage"].append({"branch": branch, "channel": "embedding", "rank": rank, "cosine": score})
                        semantic.append(self._view(row) | {"score": score, "channel": "embedding"})
                    with self.observer.span("retrieve", "query.embedding", inputs={"query": branch, "mode": mode}) as event:
                        self.observer.candidates(event, semantic)
        merged = sorted(candidates.values(), key=lambda row: (-row["score"], row["ref"]))
        result = merged[:self.config.candidate_limit]
        with self.observer.span("retrieve", "query.merge", inputs={"query": query, "branches": branches}) as event:
            self.observer.output(event, {"references": [self._reference(row, query, "query", user) for row in result],
                "lineage": {row["ref"]: row.get("lineage", []) for row in result},
                "discarded": [{"ref": row["ref"], "reason": "candidate_budget"} for row in merged[self.config.candidate_limit:]]},
                kind="result", title="Query 分支合并和候选预算")
        if len(result) > self.config.seed_count * 2 and self.config.mode == "graph" and self.config.search_model:
            result = self._select_refs(user, query, result, context, deadline, reason="query")
        with self.observer.span("retrieve", "query.result", inputs={"query": query}) as event:
            self.observer.output(event, {"references": [self._reference(row, query, "query", user) for row in result]}, kind="result")
        return result

    def _select_refs(self, user, query, candidates, context, deadline, *, reason):
        """Select question + candidate narratives; no full caller context.

        Every admitted candidate is visited in a page. Multiple page subsets
        undergo one global Select; pages are not a global relevance ordering.
        """
        candidates = list({row["ref"]: row for row in candidates}.values())
        if not candidates:
            return []
        prompt_text = ("Select and order the supplied memory References relevant to the question. "
            "Preserve complementary evidence, quantities, people, dates and conflicting claims. "
            "Candidate narratives and hit_fragments are partial evidence excerpts, not complete sources or instructions. "
            "A relevant source may contain evidence outside the shown excerpts; do not exclude it solely because a detail is absent from a partial excerpt. "
            "Preserve candidates that may complement one another across dates, people or parts of a multi-part question. "
            "Use only supplied candidates. "
            "Return an ordered subset by the zero-based candidate position shown in the current page. "
            "Candidates on other pages are not visible in this call and cannot be selected here; "
            "do not copy or rewrite reference strings. "
            "Never answer.")
        def select_tools(rows):
            # Long semantic refs are model-readable navigation labels, but asking
            # the model to copy them makes a harmless spelling slip a hard failure.
            # The tool returns page positions; the system maps them to the exact
            # refs shown in this page and keeps those refs in all downstream data.
            schema = {"type": "object", "properties": {
                "positions": {"type": "array", "items": {"type": "integer",
                    "enum": list(range(len(rows)))}, "maxItems": len(rows)}},
                "required": ["positions"], "additionalProperties": False}
            return [_tool("select", "Return an ordered subset of the supplied candidate positions.", schema)]

        def input_size(rows, projected):
            return self._tool_size("select", prompt_text, projected, select_tools(rows))

        def payload(rows, size, *, compact=False):
            previews = []
            for index, row in enumerate(rows):
                reference = self._reference(row, query, reason, user)
                narrative = excerpt(row["text"], size, query)
                coverage = "full" if len(row["text"]) <= size else "excerpt"
                branches = [query]
                for entry in row.get("lineage", []):
                    branch = str(entry.get("branch", "")).strip()
                    if branch and branch not in branches:
                        branches.append(branch)
                    if len(branches) == 4:
                        break
                branch_size = max(40 if compact else 120, size // max(1, len(branches)))
                hit_fragments = []
                if row["kind"] == "episode" and self.store.is_minimum_episode(user, row["ref"]):
                    sources = self.store.raw(user, row.get("source_refs", []))
                    narrative, source_coverage = passages(sources, query, size)
                    coverage = {"source_count": len(sources),
                                "shown_source_count": sum(entry["included"] for entry in source_coverage),
                                "complete": all(entry["included"] and entry.get("complete") for entry in source_coverage),
                                "omitted_count": sum(not entry["included"] for entry in source_coverage)}
                    for branch in branches:
                        branch_fragments, branch_coverage = complementary_passages(
                            sources, [branch], branch_size, max_fragments=2)
                        if branch_fragments:
                            hit_fragments.extend(branch_fragments)
                        else:
                            hit_fragments.append({"query": excerpt(branch, 160),
                                "text": excerpt(row["text"], branch_size, branch),
                                "coverage": {"source_count": len(branch_coverage),
                                    "shown_source_count": sum(entry["included"] for entry in branch_coverage),
                                    "complete_count": sum(entry.get("complete", False) for entry in branch_coverage),
                                    "omitted_count": sum(not entry["included"] for entry in branch_coverage)}})
                    coverage["shown_ranges"] = [entry["shown_range"]
                                                 for fragment in hit_fragments
                                                 for entry in [{"shown_range": fragment.get("shown_range")}]
                                                 if fragment.get("shown_range")]
                    if not narrative:
                        narrative = excerpt(row["text"], size, query)
                else:
                    hit_fragments = [{"query": excerpt(branch, 160),
                                      "text": excerpt(row["text"], branch_size, branch),
                                      "coverage": "full" if len(row["text"]) <= branch_size else "excerpt"}
                                     for branch in branches]
                if compact:
                    # Merge all page survivors without repeating provenance IDs,
                    # branch metadata and per-fragment coverage tables. Keep
                    # semantic refs and evidence text; the full page inputs and
                    # candidate lineage remain in the observation artifacts.
                    fragments = []
                    seen_fragments = set()
                    for fragment in hit_fragments:
                        value = fragment if isinstance(fragment, dict) else {"text": fragment}
                        text = value.get("text")
                        if text and text != narrative and text not in seen_fragments:
                            seen_fragments.add(text)
                            fragments.append(value)
                    previews.append({"position": index, "ref": row["ref"], "kind": row["kind"],
                        "label": excerpt(reference["label"], min(80, size)),
                        "narrative": narrative, "hit_fragments": fragments,
                        "coverage": coverage,
                        "shown_ranges": coverage.get("shown_ranges", []) if isinstance(coverage, dict) else [],
                        "time_expression": row.get("time_expression"),
                        "time_start": row.get("time_start"), "time_end": row.get("time_end")})
                    continue
                previews.append({"position": index, "ref": row["ref"], "kind": row["kind"], "label": reference["label"],
                    "narrative": narrative, "hit_fragments": hit_fragments, "coverage": coverage,
                    "source_refs": row.get("source_refs", [])[:8],
                    "time_expression": row.get("time_expression"), "time_start": row.get("time_start"),
                    "time_end": row.get("time_end"),
                    "lineage": [{**entry, "branch": excerpt(str(entry.get("branch", "")), 160)}
                                for entry in row.get("lineage", [])[:4]]})
            return {"question": query, "candidates": previews}

        def execute(rows, projected, phase, page):
            with self.observer.span("select", "select references", inputs={
                    **projected, "reason": reason, "phase": phase, "page": page,
                    "candidate_count": len(candidates), "model_candidate_count": len(rows),
                    "context_included": False}) as event:
                name, data = self._call_tool("select", prompt_text, projected, select_tools(rows), deadline)
                allowed_by_position = {index: row for index, row in enumerate(rows)}
                allowed_by_ref = {row["ref"]: row for row in rows}
                positions = data.get("positions") if isinstance(data, dict) else None
                invalid_positions = []
                duplicate_positions_removed = False
                if positions is not None:
                    if not isinstance(positions, list):
                        raise MemoryError("selection_invalid_position", 502)
                    valid_positions = [pos for pos in positions
                                       if type(pos) is int and pos in allowed_by_position]
                    invalid_positions = [pos for pos in positions
                                         if type(pos) is not int or pos not in allowed_by_position]
                    unique_positions = list(dict.fromkeys(valid_positions))
                    duplicate_positions_removed = len(unique_positions) != len(valid_positions)
                    if invalid_positions and not unique_positions:
                        raise MemoryError("selection_invalid_position", 502)
                    raw_selected = [allowed_by_position[pos]["ref"] for pos in unique_positions]
                    positions = unique_positions
                else:
                    # Keep the deterministic test/provider adapter compatible;
                    # real model calls use positions because that is the only
                    # schema exposed above.
                    try:
                        raw_selected = Selection.model_validate(data).refs
                    except ValidationError:
                        raise MemoryError("selection_invalid", 502) from None
                    if any(ref not in allowed_by_ref for ref in raw_selected):
                        raise MemoryError("selection_unknown_ref", 502)
                selected = list(dict.fromkeys(raw_selected))
                self.observer.candidates(event, projected["candidates"], selected)
                self.observer.output(event, {"selected_refs": selected,
                        "selected_positions": positions,
                    "invalid_positions_dropped": invalid_positions,
                    "duplicate_positions_removed": duplicate_positions_removed,
                    "excluded_refs": [ref for ref in allowed_by_ref if ref not in selected],
                    "duplicate_refs_removed": len(selected) != len(raw_selected), "phase": phase, "page": page}, kind="context")
                return [allowed_by_ref[ref] for ref in selected]

        # Keep a stable position for observation, while exposing page-local
        # positions to the model. A page is an independent tool call: asking
        # for positions from the complete candidate list would make later
        # pages fail whenever the model chooses an earlier page's number.
        candidates = [dict(row, _select_position=index) for index, row in enumerate(candidates)]
        offset, pages, survivors = 0, 0, []
        while offset < len(candidates):
            self._check_deadline(deadline)
            page = candidates[offset:offset + self.config.select_candidate_limit]
            projected = payload(page, self.config.preview_chars)
            while len(page) > 1 and input_size(page, projected) > self.config.model_input_chars:
                page = page[:-1]
                projected = payload(page, self.config.preview_chars)
            # A single long episode can still exceed the provider budget after
            # the page has been reduced to one row.  Switch that page to the
            # compact narrative used by the global merge, then reduce only the
            # evidence excerpt size until the serialized tool input fits.  The
            # candidate remains visited; only repeated provenance metadata is
            # removed from the model projection.
            if input_size(page, projected) > self.config.model_input_chars:
                size = self.config.preview_chars
                projected = payload(page, size, compact=True)
                while size > 40 and input_size(page, projected) > self.config.model_input_chars:
                    size = max(40, size // 2)
                    projected = payload(page, size, compact=True)
                if input_size(page, projected) > self.config.model_input_chars:
                    raise MemoryError("select_message_budget", 413)
            survivors.extend(execute(page, projected, "page", pages))
            offset += len(page)
            pages += 1
        if pages > 1 and len(survivors) > 1:
            size = self.config.preview_chars
            projected = payload(survivors, size, compact=True)
            while size > 40 and input_size(survivors, projected) > self.config.model_input_chars:
                size = max(40, size // 2)
                projected = payload(survivors, size, compact=True)
            if input_size(survivors, projected) > self.config.model_input_chars:
                raise MemoryError("select_merge_budget", 413)
            survivors = execute(survivors, projected, "merge", pages)
        return [dict(row, select_order=index) for index, row in enumerate(survivors)]

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
        context = {"question": request.query, "references": {}, "items": {}, "edges": [],
                   "frontier": [], "depths": {}, "explored": [], "expanded_refs": []}
        candidates = self._search_refs(request.user_id, request.query, context, deadline)
        for row in candidates:
            context["references"][row["ref"]] = self._reference(row, request.query, "query", request.user_id)
            context["depths"][row["ref"]] = 0
        pool = {row["ref"]: row for row in candidates}
        for step in range(self.config.search_steps):
            self._check_deadline(deadline)
            done = {tuple(entry) for entry in context["explored"]}
            context["frontier"] = [ref for ref in context["references"]
                if (ref, "inspect") not in done or (ref, "backlinks") not in done]
            if not context["frontier"]:
                break
            action = self._next_bfs_action(request.user_id, request.query, context, deadline)
            if action.action == "stop":
                break
            ref = action.ref
            if not ref or ref not in context["references"] or (ref, action.action) in done:
                with self.observer.span("retrieve", "bfs invalid or repeated action", inputs=action.model_dump()) as event:
                    self.observer.output(event, {"handled": "stop", "reason": "unknown_or_repeated_operation"}, kind="context")
                break
            neighbors = self._explore(request.user_id, ref, action.action, context, request.query, deadline)
            for row in neighbors:
                pool.setdefault(row["ref"], {**row, "score": pool.get(ref, {}).get("score", 0.01) * 0.8})
            with self.observer.span("retrieve", "bfs step", inputs={"step": step, "action": action.model_dump()}) as event:
                self.observer.output(event, {"explored": context["explored"],
                    "references": list(context["references"]), "edges": context["edges"],
                    "depths": context["depths"]}, kind="context", title="BFS 上下文增量")
        with self.observer.span("context", "search final pack", inputs={"candidates": list(pool)}) as event:
            rows = self._assemble(request.user_id, request.query, list(pool.values()), request.top_k, request.query)
            self.observer.output(event, {"data": rows, "explored": context["explored"]}, kind="result", title="Search 最终证据装箱")
        return {"data": rows}

    def _explore(self, user, ref, action, context, query, deadline):
        """Shared graph reads; Reflection and standard Search keep separate state."""
        self._check_deadline(deadline)
        key = [ref, action]
        if key in context.setdefault("explored", []):
            raise MemoryError("repeated_graph_operation", 502)
        context["explored"].append(key)
        depth = context.setdefault("depths", {}).get(ref, 0)
        if action == "inspect":
            value = self.inspect(user, ref)
            if value is None:
                return []
            # Reinsert to prioritize the freshly read content in the next projection.
            context.setdefault("items", {}).pop(ref, None)
            self._add_context_refs(user, context, [value["node"]], deadline)
            edges = value["links"]
        else:
            edges = self.backlinks(user, ref)
        neighbors = {}
        for raw_edge in edges:
            edge = self._edge_view(user, raw_edge)
            other = edge["to_ref"] if edge["from_ref"] == ref else edge["from_ref"]
            node = self.store.get(user, other)
            if node:
                neighbors.setdefault(other, {**node, "via": edge["narrative"]})
            if not any((item["from_ref"], item["to_ref"], item["relation"]) ==
                       (edge["from_ref"], edge["to_ref"], edge["relation"]) for item in context.setdefault("edges", [])):
                context["edges"].append(edge)
        rows = list(neighbors.values())
        if action == "backlinks" and len(rows) > self.config.max_neighbors and self.config.mode == "graph" and self.config.search_model:
            rows = self._select_refs(user, query, rows, context, deadline, reason="backlink")
        admitted, discarded = [], []
        for node in rows:
            other = node["ref"]
            if depth >= self.config.max_hops:
                discarded.append({"ref": other, "reason": "hop_budget"})
                continue
            if other not in context["references"] and len(context.setdefault("expanded_refs", [])) >= self.config.max_nodes:
                discarded.append({"ref": other, "reason": "graph_node_budget"})
                continue
            if other not in context["references"]:
                context["expanded_refs"].append(other)
            context["references"][other] = self._reference(node, query, node["via"], user)
            context["depths"][other] = min(context["depths"].get(other, depth + 1), depth + 1)
            admitted.append(node)
        with self.observer.span("retrieve", "graph context update", inputs={"ref": ref, "action": action, "depth": depth}) as event:
            self.observer.output(event, {"references": [context["references"][node["ref"]] for node in admitted],
                "edges": edges, "discarded": discarded}, kind="context")
        return admitted

    def _next_bfs_action(self, user, query, context, deadline):
        if self.config.mode != "graph" or not self.config.search_model:
            done = {tuple(entry) for entry in context.get("explored", [])}
            for ref in context["frontier"]:
                for action in ("inspect", "backlinks"):
                    if (ref, action) not in done:
                        return BfsAction(action=action, ref=ref)
            return BfsAction(action="stop")
        frontier = list(context.get("frontier", []))
        tools = [_tool("bfs_action", "Choose one supplied frontier position to inspect, backlinks, or stop. "
                       "Use the exact zero-based position from the current frontier; never invent a reference string.",
                       {"type": "object", "properties": {
                           "action": {"type": "string", "enum": ["inspect", "backlinks", "stop"]},
                           "frontier_position": {"type": "integer", "enum": list(range(len(frontier)))},
                           "reason": {"type": "string"}},
                        "required": ["action"], "additionalProperties": False})]
        with self.observer.span("retrieve", "bfs action", inputs={"query": query, "context": context}) as event:
            name, data = self._call_tool("bfs", "Explore the supplied memory graph. Choose inspect/backlinks only for a ref in context.frontier. Inspect and backlinks on the same ref are different operations; never repeat an explored ref/operation pair. Read newly discovered links when needed. Stop when evidence is sufficient. Never answer.", {"query": query, "context": self._model_context(context)}, tools, deadline)
            try:
                action = BfsAction.model_validate(data)
            except ValidationError:
                raise MemoryError("bfs_action_invalid", 502) from None
            # Real model calls use the exact frontier position. Keep accepting
            # an exact ref from deterministic providers used by unit tests, but
            # never accept a semantic or unknown ref from either path.
            if action.action == "stop":
                action = action.model_copy(update={"ref": None})
            elif action.frontier_position is not None:
                if action.frontier_position < 0 or action.frontier_position >= len(frontier):
                    raise MemoryError("bfs_invalid_position", 502)
                action = action.model_copy(update={"ref": frontier[action.frontier_position]})
            elif action.ref not in frontier:
                raise MemoryError("bfs_unknown_reference", 502)
            self.observer.output(event, action.model_dump(), kind="context", title="BFS 模型决策")
            return action

    def inspect(self, user, ref):
        with self.observer.span("retrieve", "memory.inspect", inputs={"ref": ref}) as event:
            node = self.store.get(user, ref)
            if node is None:
                self.observer.output(event, {"ref": ref, "available": False}, kind="result", title="Inspect 空结果")
                return None
            links = self.store.edges(user, ref)
            value = {"reference": self._reference(node, "", "inspect", user), "node": self._view(node), "links": links, "source_refs": node["source_refs"]}
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
                    values.append({"reference": self._reference(node, "", "backlink", user), "edge": edge})
            self.observer.output(event, values, kind="context", title="Backlink 反向 References")
            return links

    def _assemble(self, user, query, rows, top_k, preferred_query):
        result, used_sources, total, decisions = [], {}, 0, []
        # Incoming order is authoritative: Query fusion or final Select order.
        # Retrieval scores remain in trace artifacts, not a second sorter. The
        # source coverage below is the deterministic evidence-closure pass: a
        # selected item keeps complementary source fragments and records every
        # omitted source instead of silently collapsing to one large excerpt.
        for index, row in enumerate(rows):
            decision = {"ref": row["ref"], "candidate_order": index, "included": False}
            decisions.append(decision)
            node = self.store.get(user, row["ref"])
            if not node:
                decision["reason"] = "unavailable"
                continue
            if node["ref"] in {item["id"] for item in result}:
                decision["reason"] = "duplicate_ref"
                continue
            if node["status"] == "superseded" and not re.search(r"histor|previous|earlier|以前|历史", preferred_query, re.I):
                decision["reason"] = "superseded"
                continue
            if len(result) >= top_k:
                decision["reason"] = "top_k"
                continue
            remaining = self.config.context_chars - total
            slots = min(top_k - len(result), len(rows) - index, max(1, remaining // 800))
            budget = min(self.config.result_chars, remaining // max(1, slots))
            source_refs = list(dict.fromkeys(node.get("source_refs", [])))
            available_sources = {ref: self.store.get(user, ref) for ref in source_refs}
            sources = sorted((source for source in available_sources.values() if source), key=lambda source: source["ordinal"])
            sessions = list(dict.fromkeys(source["session_id"] for source in sources))
            header = f"[{node['kind']}][{node['ref']}][status={node['status']}]"
            dates = {key: node[key] for key in ("time_expression", "time_start", "time_end") if node.get(key)}
            if dates:
                header += " " + dumps(dates)
            if sessions:
                header += "\n来源会话：" + ", ".join(sessions)
            if len(header) + 160 > budget:
                decision["reason"] = "context_budget"
                continue
            parts = [header]
            minimum = self.store.is_minimum_episode(user, node["ref"])
            if not minimum:
                parts.append(excerpt(node["text"], min(2000, max(160, (budget - len(header)) // 2)), query))
            relation_coverage, relation_chars = [], 0
            edges = self.store.edges(user, node["ref"]) + self.store.edges(user, node["ref"], incoming=True)
            seen_edges = set()
            for edge in edges:
                identity = (edge["from_ref"], edge["relation"], edge["to_ref"])
                if identity in seen_edges:
                    continue
                seen_edges.add(identity)
                narrative = f"已保存关系：{edge['from_ref']} --{edge['relation']}--> {edge['to_ref']}"
                included = relation_chars + len(narrative) + 1 <= min(600, budget // 6)
                relation_coverage.append({**edge, "included": included,
                    "reason": "relation_display" if included else "relation_display_budget"})
                if included:
                    parts.append(narrative)
                    relation_chars += len(narrative) + 1
            repeated = [source["ref"] for source in sources if source["ref"] in used_sources]
            if repeated:
                parts.append("来源原文已在前面的证据中展示：" + ", ".join(dict.fromkeys(used_sources[ref] for ref in repeated)))
            source_budget = budget - len("\n".join(parts)) - 1
            remaining_sources = [source for source in sources if source["ref"] not in used_sources]
            content, coverage = passages(remaining_sources, query, max(0, source_budget))
            if minimum and remaining_sources and not all(entry.get("complete") for entry in coverage):
                # Plan evidence closure before rendering a card: expose
                # complementary source fragments with explicit ranges so one
                # long source cannot consume the whole card and hide the other
                # messages that make the episode answerable.
                content_fragments, coverage = complementary_passages(
                    remaining_sources, [query, preferred_query], max(0, source_budget),
                    max_fragments=len(remaining_sources))
                content = "\n".join(fragment["text"] for fragment in content_fragments)
            source_coverage = {entry["ref"]: entry for entry in coverage}
            for ref in source_refs:
                source = available_sources[ref]
                if source is None:
                    source_coverage[ref] = {"ref": ref, "included": False, "complete": False,
                                            "reason": "source_unavailable"}
                elif ref in used_sources:
                    source_coverage[ref] = {"ref": ref, "included": True, "complete": True,
                                            "shown_range": [0, len(source["text"])],
                                            "reused_from": used_sources[ref], "reason": "deduplicated_source"}
            coverage = [source_coverage[ref] for ref in source_refs]
            if content:
                parts.append(content)
            if minimum and not content and not repeated:
                decision["reason"] = "source_content_budget"
                decision["source_coverage"] = coverage
                continue
            # State labels are concise and deduplicated; never re-append every
            # state's entire text for every source in this item.
            states = {}
            for source in sources:
                for state in self.store.source_states(user, source["ref"]):
                    states[state["ref"]] = state["status"]
            if states:
                state_text = "关联来源状态：" + dumps(states)
                if len("\n".join(parts)) + len(state_text) + 1 <= budget:
                    parts.append(state_text)
                else:
                    decision["state_labels_omitted"] = "content_budget"
            content = "\n".join(parts)
            if len(content) > budget or total + len(content) > self.config.context_chars:
                decision["reason"] = "context_budget"
                continue
            result.append({"id": node["ref"], "content": content,
                           "score": round(1 / (len(result) + 1), 8), "created_at": node["created_at"]})
            total += len(content)
            for entry in coverage:
                if entry["included"] and entry.get("complete") and not entry.get("reused_from"):
                    used_sources[entry["ref"]] = node["ref"]
            decision.update(included=True, reason="packed", chars=len(content), budget=budget,
                            source_coverage=coverage, deduplicated_sources=repeated,
                            relation_coverage=relation_coverage,
                            evidence_units=[{"source_ref": entry["ref"],
                                             "included": entry["included"],
                                             "complete": entry.get("complete", False),
                                             "shown_range": entry.get("shown_range") or (entry.get("shown_ranges") or [None])[0],
                                             "shown_ranges": entry.get("shown_ranges", []),
                                             "reused_from": entry.get("reused_from"),
                                             "reason": entry.get("reason")}
                                            for entry in coverage],
                            closure=("complete" if coverage and all(entry["included"] and entry.get("complete", False)
                                                                    for entry in coverage) else "partial"),
                            body_replaced_by_sources=minimum)
        with self.observer.span("context", "evidence packing decisions", inputs={"top_k": top_k, "context_chars": self.config.context_chars}) as event:
            self.observer.output(event, {
                "decisions": decisions,
                "output_chars": total,
                "closure": {
                    "packed_refs": [decision["ref"] for decision in decisions if decision.get("included")],
                    "omitted_refs": [{"ref": decision["ref"], "reason": decision.get("reason")}
                                     for decision in decisions if not decision.get("included")],
                    "partial_source_units": [
                        {"ref": decision["ref"], "source_ref": unit["source_ref"], "reason": unit["reason"]}
                        for decision in decisions for unit in decision.get("evidence_units", [])
                        if unit.get("included") is False or unit.get("complete") is False
                    ],
                },
            }, kind="context")
        return result


def json_load(value):
    if isinstance(value, list):
        return value
    try:
        return __import__("json").loads(value or "[]")
    except (TypeError, ValueError):
        return []
