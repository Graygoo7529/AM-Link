"""AM-Link refactor: mandatory episode visibility plus bounded Reflection/Search loops."""
from __future__ import annotations

import re
import threading
import time

from pydantic import ValidationError

from .errors import MemoryError
from .evidence import (complementary_passages, episode_label, episode_text, passages, slug,
                       source_date, fragment, pages, ranges_complete, shrink_fragment)
from .evidence import _excerpt_with_range
from .projection import Choices, visible_fragments, range_receipt, range_is_visible
from .reflection_policy import plan_prefix, prefix_overview
from .grounding import missing_material
from .packing import freeze_pack, pack_frozen
from .providers import tool_body
from .reflection import parse_mutation, preflight_mutation, prepare_mutation, prompt
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
            if row.get("text_fragment"):
                shown = shrink_fragment({**row["text_fragment"], "text": row["text"]}, text_limit)
            else:
                _, (start, end), _ = _excerpt_with_range(value["text"], text_limit, query)
                shown = fragment(row, start, end, query=query)
            # The full maintenance question already appears once in context.
            # Repeating it in every source receipt can outweigh all body text.
            shown["query"] = excerpt(str(shown.get("query", "")), 160)
            value["text"] = shown["text"]
            value["text_fragment"] = {k: v for k, v in shown.items() if k != "text"}
        if isinstance(value.get("source_refs"), list):
            value["source_refs"] = value["source_refs"][:64]
        return value

    def _model_context(self, context, max_chars=None):
        """Reserve actual read material before spending on automatic previews."""
        limit = max(0, min(self.config.context_chars, max_chars if max_chars is not None else self.config.context_chars))
        result = {"question": excerpt(str(context.get("question", "")), 1200),
                  "references": {}, "items": {}, "sources": [], "edges": [], "disclosures": []}
        pinned = set(context.get("pinned", []))
        protected = set(context.get("protected_refs", [])) | set(context.get("protected_bodies", []))
        disclosed = context.get("disclosures", [])
        mandatory = [v for v in disclosed if v["fragment_id"] in pinned or v["origin_ref"] in protected
                     or v["origin_ref"] in context.get("protected_sources", [])]
        result["disclosures"] = list(mandatory)
        if context.get("old_before"):
            result["reflection_control"] = {
                "old_scope": context.get("old_scope"), "last_gate_error": context.get("last_gate_error"),
                "recent_actions": context.get("action_log", [])[-6:],
                "identity_queries": {key: {**v, "refs": v["refs"][:8], "candidate_count": len(v["refs"])}
                    for key, v in list(context.get("identity_queries", {}).items())[-8:]}}
            pending = context.get("pending_mutation")
            if pending and context.get("last_gate_error", {}).get("code") == "reflection_invalid_relations":
                result["reflection_control"]["pending_mutation"] = {
                    "basis": pending.get("basis", "new_information"),
                    "items": [{key: item.get(key) for key in ("ref", "kind", "text", "source_refs")}
                              for item in pending.get("items", [])],
                    "forget_count": len(pending.get("forget", [])),
                    "instruction": "These node/forget fields are an uncommitted proposal. Grounding is checked after relation repair. Submit corrected links in reflection_relations; set drop_invalid=true with links=[] when no legal supported edge remains."
                }
        # Metadata/navigation are part of the same budget. A required page is
        # indivisible and cannot disappear during a second projection.
        if len(dumps(result)) > max(0, limit - 600):
            if mandatory:
                raise MemoryError("protected_context_budget", 413)
            return {}
        for value in reversed(disclosed):
            if value in mandatory:
                continue
            result["disclosures"].append(value)
            if len(dumps(result)) > max(limit * 0.65, len(dumps({**result, "disclosures": mandatory}))):
                result["disclosures"].pop()
        refs, items = context.get("references", {}), context.get("items", {})
        priority = [v.get("item_ref") for v in result["disclosures"] if v.get("item_ref")]
        omitted = []
        for ref in dict.fromkeys([*sorted(protected), *priority, *reversed(items), *refs]):
            reference = dict(refs.get(ref, {}))
            if not reference and ref in items:
                reference = self._reference(items[ref], result["question"], "context")
            if not reference:
                continue
            reference["narrative"] = excerpt(str(reference.get("narrative", "")), 500, result["question"])
            reference["evidence_fragments"] = [shrink_fragment(v, 520)
                for v in reference.get("evidence_fragments", [])[:4] if "content_digest" in v]
            for v in reference["evidence_fragments"]:
                v["model_projection"] = {"source_text_chars": v["source_chars"], "shown_chars": len(v["text"]), "complete": v["complete"]}
            if reference["evidence_fragments"]:
                # This is the actual projected range, not the wider Query preview.
                reference["coverage"] = [{"ref": origin, "shown_ranges": [v["shown_range"] for v in reference["evidence_fragments"] if v["origin_ref"] == origin]}
                    for origin in dict.fromkeys(v["origin_ref"] for v in reference["evidence_fragments"])]
                reference["shown_ranges"] = [v["shown_range"] for v in reference["evidence_fragments"]]
            result["references"][ref] = reference
            if len(dumps(result)) > limit - 1000:
                result["references"][ref] = {key: reference.get(key) for key in ("ref", "kind", "label", "narrative")}
                result["references"][ref]["narrative"] = excerpt(reference["narrative"], 160)
                if len(dumps(result)) > limit - 600:
                    result["references"].pop(ref)
                    omitted.append(ref)
                    continue
            if ref in items and not items[ref].get("scope_omit_body") and not any(v["origin_ref"] == ref for v in result["disclosures"]):
                result["items"][ref] = self._model_row(items[ref], result["question"], 1200)
                if len(dumps(result)) > limit - 1000:
                    result["items"].pop(ref)
        for edge in context.get("edges", []):
            if edge["from_ref"] in result["references"] or edge["to_ref"] in result["references"]:
                result["edges"].append(edge)
                if len(dumps(result)) > limit - 600:
                    result["edges"].pop()
        for source in context.get("sources", []):
            if source["ref"] in context.get("new_refs", []):
                continue  # Full working messages are a separate model payload.
            result["sources"].append(self._model_row(source, result["question"], 240))
            if len(dumps(result)) > limit - 600:
                result["sources"].pop()
        visible = set(result["references"])
        result["frontier"] = [ref for ref in context.get("frontier", []) if ref in visible]
        result["depths"] = {ref: depth for ref, depth in context.get("depths", {}).items() if ref in visible}
        result["explored"] = [entry for entry in context.get("explored", []) if entry[0] in visible]
        result["projection"] = {"omitted_refs": omitted, "reason": "context_budget"}
        # Optional navigation metadata may be folded, but required material never is.
        for key in ("explored", "depths", "frontier"):
            if len(dumps(result)) > limit:
                result.pop(key, None)
        if len(dumps(result)) > limit:
            result["projection"] = {"omitted_ref_count": len(omitted), "reason": "context_budget"}
        if len(dumps(result)) > limit:
            raise MemoryError("protected_context_budget", 413)
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
        required = row.get("reflection_watermark", 0)
        raw = self.store.raw(request.user_id, raw_refs)
        request_end = max((source["ordinal"] for source in raw), default=required)
        decision = plan_prefix(pending, request_end, required,
                               self.store.state(request.user_id)["settled_through"], self.config)
        trigger = self.config.mode == "graph" and decision["trigger"]
        with self.observer.span("reflection", "reflection prefix policy", inputs={"request_id": request.request_id}) as event:
            self.observer.output(event, {"format_version": 1, **decision}, kind="context")
        self._observe_add_state(request, pending, trigger, episode)
        if not trigger:
            self._check_deadline(deadline)
            self.store.finish_minimum(request.user_id, request.request_id, require_vector=self.config.embedding_enabled)
            return self._response(request)
        target = decision["target"]
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
        editable = sorted(ref for ref, node in context.get('items', {}).items()
                          if node['kind'] not in {'fact', 'event'} and not node.get('scope_omit_body'))
        new_ref = {'type': 'string', 'pattern': '^new:.+$'}
        item_properties['ref'] = ({'anyOf': [new_ref, {'type': 'string', 'enum': editable}]}
                                  if editable else dict(new_ref))
        item_properties['ref']['description'] = (
            'For each new or changed fact/event use a meaningful new: label. Only the listed existing mutable nodes '
            'may be re-emitted for an update. Never invent memory: identifiers or rewrite a minimum episode. '
            'Unchanged old facts/events may be relation endpoints without re-emitting them in items.')
        link_properties = definitions.get("LinkChange", {}).get("properties", {})
        for endpoint in ("from_ref", "to_ref"):
            link_properties[endpoint] = {"type": "string", "pattern": "^(new:.+|memory:.+)$",
                "description": "Exact new: item placeholder from this proposal or a loaded memory: ref. Never raw:."}
        link_properties["relation"]["description"] = (
            "Direction: about is fact/event -> person/entity/concept/event; contains is episode -> fact/event; "
            "supersedes/contradicts connect same-type fact/event; same_event_as connects events. "
            "A person is the TO endpoint of about, never its FROM endpoint.")
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
            "description": "Old targets require Inspect body evidence. Backlinks alone never authorizes a change."}
        properties["inspected_refs"] = {
            "type": "array", "items": {"type": "string"}, "maxItems": 64,
            "description": "Exact loaded memory refs examined before this mutation."}
        properties["no_prior_match"] = {
            "type": "boolean",
            "description": "True after a successful empty identity query or the supplied database old_scope.empty receipt."}
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
        prefix = self.store.raw(user, pending=True)
        target = self.store.request(user, request.request_id).get("reflection_watermark", watermark)
        context["prefix_overview"] = prefix_overview([row for row in prefix if row["ordinal"] <= target],
                                                      watermark, min(6000, self.config.context_chars // 4))
        self._save_workspace(user, state="maintenance", context=context)
        def reflection_tools(choices, source_refs=None, terminal=False):
            refs = [row["ref"] for row in choices.rows]
            tools = [
                _tool("reflection_search", "Query OLD structured memory. For each planned new person, supply for_new_ref equal to its exact future new: placeholder; use null for general discovery. The query receipt appears in reflection_control.identity_queries. Do not repeat a completed identity query unless seeking new evidence.",
                      {"type": "object", "properties": {"question": {"type": "string"}, "for_new_ref": {"type": ["string", "null"]}}, "required": ["question"], "additionalProperties": False}),
                _tool("reflection_mutation", "Commit grounded high-level nodes and valid relations. Do not emit the mandatory episode again, do not link to raw refs, and do not link episode to episode. An empty mutation is valid.",
                      self._mutation_tool_schema(context, source_refs)),
                _tool("reflection_stop", "Stop because the current context is sufficient and no additional mutation is needed.",
                      {"type": "object", "properties": {}, "additionalProperties": False}),
            ]
            relation_repair = (context.get("pending_mutation")
                               and context.get("last_gate_error", {}).get("code") == "reflection_invalid_relations")
            if relation_repair:
                mutation_schema = self._mutation_tool_schema(context, source_refs)
                link_schema = mutation_schema["$defs"]["LinkChange"]
                pending_items = context["pending_mutation"].get("items", [])
                endpoints = list(dict.fromkeys([
                    *[item.get("ref") for item in pending_items],
                    *context.get("items", {}).keys(),
                    *[row.get("ref") for row in context.get("memories", [])],
                    *context.get("references", {}).keys(),
                ]))
                if endpoints:
                    for endpoint in ("from_ref", "to_ref"):
                        link_schema["properties"][endpoint] = {"type": "string", "enum": endpoints}
                link_schema["properties"]["support"] = {
                    "type": "string", "minLength": 8,
                    "description": "One short explanation of the exact cited source text that directly supports this relation. Shared topic or co-occurrence alone is not support. For contradicts/supersedes state both sides and why the relation applies."}
                kind_summary = ", ".join(f"{item.get('ref')}={item.get('kind')}" for item in pending_items)
                tools.insert(0, _tool(
                    "reflection_relations",
                    "Repair only the relation list for the pending node proposal. Grounding is checked after this repair; nothing is committed yet. Return exactly one links array and drop_invalid. If no legal, directly supported edge remains, set drop_invalid=true and links=[]; retain the nodes for final validation without new relations. Pending kinds are " + kind_summary + ". Legal directions are: about fact/event -> person/entity/concept/event; contains episode -> fact/event; supersedes/contradicts same-kind fact/event; same_event_as event -> event. Do not use about between two facts, do not use contains from an event/person, and do not add an edge merely because two items share a topic. Use exact pending or loaded memory refs, a nonempty source_refs list, and a short direct-support explanation for every edge.",
                    {"type": "object", "properties": {"drop_invalid": {"type": "boolean"}, "links": {
                        "type": "array", "items": link_schema, "maxItems": 256}}}))
                tools = [tool for tool in tools if tool["name"] == "reflection_relations"]
            if refs:
                for action in ("evict", "inspect", "backlinks"):
                    allowed = [row["position"] for row in choices.rows if action in row["allowed_actions"]]
                    if not allowed:
                        continue
                    positions = {"type": "integer", "enum": allowed}
                    properties = ({"reference_positions": {"type": "array", "items": positions, "maxItems": len(allowed)}}
                                  if action == "evict" else {"reference_position": positions})
                    if action == "inspect":
                        properties = {"target": choices.inspect_target_schema("reference_position")}
                    tools.insert(1, _tool("reflection_" + action,
                        {"evict": "Evict allowed active references only; never delete stored memory.",
                         "inspect": "Read an unread page of a supplied reference. Use null for next relevant page, or exactly a page offered for that reference.",
                         "backlinks": "Discover references pointing to this supplied reference; Select when numerous."}[action],
                        {"type": "object", "properties": properties, "additionalProperties": False}))
            if context.get("old_scope", {}).get("empty"):
                tools = [t for t in tools if t["name"] != "reflection_search"]
            if context.get("last_gate_error"):
                tools = [t for t in tools if t["name"] != "reflection_stop"]
                # A rejected proposal with no missing material has a closed
                # deterministic todo: repair the proposal and resubmit it.
                # Keeping Inspect/Backlink/Evict available here made the model
                # reread the same old episode after a relation/type or immutable
                # episode error, consuming the final submission slots without
                # changing the rejected proposal. Material-oriented failures
                # still expose exploration tools until their missing ranges are
                # actually visible.
                if not context["last_gate_error"].get("missing"):
                    allowed_repairs = {"reflection_mutation"}
                    if relation_repair:
                        allowed_repairs = {"reflection_relations"}
                    tools = [t for t in tools if t["name"] in allowed_repairs]
            return [tool for tool in tools if tool["name"] in {"reflection_mutation", "reflection_relations", "reflection_stop"}] if terminal else tools
        for step in range(self.config.reflection_steps):
            if time.monotonic() >= deadline:
                raise MemoryError("request_deadline", 504)
            payload = {"working": [self._view(row) for row in pending], "context": {},
                       "watermark": watermark, "step": step,
                       "remaining_decisions": self.config.reflection_steps - step,
                       "prefix_overview": context.get("prefix_overview", []),
                       "instruction": "Overview is partial planning context. Future batches are not legal mutation sources."}
            context_limit = self.config.context_chars
            for _ in range(20):
                payload["context"] = self._model_context(context, context_limit)
                choices = self._visible_choices(user, context, payload["context"],
                                                payload["context"].get("references", {}), evict=True)
                visible_sources = {row["ref"] for row in pending}
                visible_sources.update(value["origin_ref"] for value in visible_fragments(payload["context"])
                                       if value["origin_ref"].startswith("raw:"))
                visible_sources = {ref for ref in visible_sources if (source := self.store.get(user, ref))
                                   and source.get("ordinal", watermark + 1) <= watermark}
                context["visible_source_refs"] = sorted(visible_sources)
                tools = reflection_tools(choices, sorted(visible_sources), step == self.config.reflection_steps - 1)
                if self._tool_size("reflection", prompt(), payload, tools) <= self.config.model_input_chars:
                    break
                context_limit = int(context_limit * 0.85)
            else:
                raise MemoryError("reflection_message_budget", 413)
            with self.observer.span("reflection", "reflection tool decision", inputs=payload) as event:
                name, arguments = self._call_tool("reflection", prompt(), payload, tools, deadline)
                self._record_visible(context, payload["context"], "reflection", payload["working"])
                self.observer.output(event, {"tool": name, "arguments": arguments}, kind="context", title="Reflection 工具调用")
            if name == "reflection_search":
                question = str(arguments.get("question", "")).strip()
                if not question:
                    raise MemoryError("reflection_search_invalid", 502)
                key = digest([question.casefold().strip(), context.get("old_before")])
                if key in context.get("completed_queries", []):
                    raise MemoryError("reflection_no_query_progress", 409)
                refs = self._search_refs(user, question, context, deadline, mode="reflection")
                context.setdefault("completed_queries", []).append(key)
                self._reflection_action(context, "query", question=excerpt(question, 160), candidates=len(refs))
                if arguments.get("for_new_ref"):
                    context.setdefault("identity_queries", {})[arguments["for_new_ref"]] = {
                        "question": question, "refs": [row["ref"] for row in refs]}
                self._add_context_refs(user, context, refs, deadline)
                self._save_workspace(user, state="maintenance", context=context)
                continue
            if name in {"reflection_inspect", "reflection_backlinks"}:
                if name == "reflection_inspect":
                    arguments = arguments.get("target", {})
                position = arguments.get("reference_position")
                action = "inspect" if name == "reflection_inspect" else "backlinks"
                ref = choices.resolve(position, action)
                self._explore(user, ref, action, context, context["question"], deadline, arguments.get("page_position"))
                self._reflection_action(context, action, ref=ref)
                self._refresh_context(user, context, pending)
                self._save_workspace(user, state="maintenance", context=context)
                continue
            if name == "reflection_evict":
                positions = arguments.get("reference_positions")
                if not isinstance(positions, list):
                    raise MemoryError("reflection_invalid_position", 502)
                evicted_refs = list(dict.fromkeys(choices.resolve(pos, "evict") for pos in positions))
                allowed = set(context.get("items", {})) | set(context.get("references", {}))
                context["items"] = {ref: value for ref, value in context.get("items", {}).items() if ref not in set(evicted_refs)}
                context["references"] = {ref: value for ref, value in context.get("references", {}).items() if ref not in set(evicted_refs)}
                context["disclosures"] = [value for value in context.get("disclosures", []) if value.get("item_ref") not in evicted_refs]
                context["edges"] = [edge for edge in context.get("edges", [])
                                    if edge["from_ref"] not in evicted_refs and edge["to_ref"] not in evicted_refs]
                self._refresh_context(user, context, pending)
                with self.observer.span("reflection", "reflection evict", inputs={"refs": evicted_refs}) as event:
                    self.observer.output(event, {"evicted": [ref for ref in evicted_refs if ref in allowed]}, kind="context", title="Reflection Evict")
                self._reflection_action(context, "evict", refs=evicted_refs)
                self._save_workspace(user, state="maintenance", context=context)
                continue
            if name in {"reflection_mutation", "reflection_relations"}:
                submitted_arguments = arguments
                relation_support = []
                if name == "reflection_relations":
                    pending_mutation = context.get("pending_mutation")
                    if not pending_mutation:
                        raise MemoryError("reflection_relation_state_missing", 409)
                    if (not isinstance(arguments.get('links'), list)
                            or not all(isinstance(link, dict) for link in arguments['links'])
                            or type(arguments.get('drop_invalid', False)) is not bool
                            or (arguments.get('drop_invalid') and arguments['links'])):
                        raise MemoryError('reflection_relation_output_invalid', 502)
                    relation_support = [{key: link.get(key) for key in ("from_ref", "relation", "to_ref", "source_refs", "support")}
                                        for link in arguments.get("links", [])]
                    clean_links = [] if submitted_arguments.get("drop_invalid") else [
                        {key: value for key, value in link.items() if key != "support"}
                        for link in arguments.get("links", [])]
                    arguments = {**pending_mutation, "links": clean_links}
                with self.observer.span("reflection", "reflection mutation validate", inputs={
                        "submitted": submitted_arguments, "mutation": arguments}) as event:
                    if context.get("last_gate_error") and not any(arguments.get(key) for key in ("items", "links", "forget")):
                        raise MemoryError("reflection_unresolved_evidence", 409)
                    try:
                        invalid = preflight_mutation(arguments, user=user, store=self.store)
                        if invalid:
                            context['pending_mutation'] = {key: value for key, value in arguments.items() if key != 'links'}
                            self._reflection_feedback(user, context, arguments, [], invalid,
                                                      event, step, 'reflection_invalid_relations')
                            continue
                        self._check_reflection_basis(arguments, context)
                        prepared = prepare_mutation(arguments, user=user, request_id=request.request_id, number=watermark,
                                                    context=context, store=self.store)
                        if prepared["filtered_links"]:
                            if name == "reflection_mutation":
                                context["pending_mutation"] = {
                                    "basis": arguments.get("basis", "new_information"),
                                    "inspected_refs": arguments.get("inspected_refs", []),
                                    "no_prior_match": bool(arguments.get("no_prior_match", False)),
                                    "items": arguments.get("items", []),
                                    "forget": arguments.get("forget", []),
                                }
                            self._reflection_feedback(user, context, arguments, [], prepared["filtered_links"],
                                                      event, step, "reflection_invalid_relations")
                            continue
                    except MemoryError as error:
                        if error.code == "mutation_schema_invalid":
                            # A malformed tool payload is a repairable proposal
                            # error while the current Reflection budget remains.
                            # Give the model one concrete schema task instead of
                            # turning a missing relation source list into a
                            # request failure or reopening source exploration.
                            self._reflection_feedback(user, context, arguments, [], [{
                                "reason": "mutation_schema_invalid",
                                "instruction": "Resubmit reflection_mutation with exact fields. Every item needs ref, kind, text and nonempty source_refs; every link also needs from_ref, to_ref, relation and nonempty source_refs. Do not reread material for this schema repair."
                            }], event, step, error.code)
                            continue
                        if error.code in {"mutation_fact_overwrite", "minimum_episode_immutable", "mutation_invalid_identity"}:
                            bad_refs = []
                            for item in arguments.get("items", []):
                                ref = item.get("ref") if isinstance(item, dict) else None
                                if isinstance(ref, str) and ref.startswith("memory:") and ref not in context.get("items", {}) and ref not in context.get("references", {}):
                                    bad_refs.append(ref)
                            instruction = "Reference unchanged old items without re-emitting them. New facts/events use new: refs; minimum episodes cannot be rewritten."
                            if error.code == "mutation_invalid_identity" and bad_refs:
                                instruction = ("These memory refs are not loaded old nodes: " + ", ".join(bad_refs[:8]) + ". "
                                    "Use a new: semantic placeholder for each genuinely new or changed node, or inspect/load the exact existing memory ref before referencing it. Do not invent memory: identifiers.")
                            self._reflection_feedback(user, context, arguments, [], [{"reason": error.code,
                                "instruction": instruction}],
                                event, step, error.code)
                            continue
                        if error.code != "reflection_orientation_required":
                            raise
                        missing = missing_material(arguments, context)
                        self._reflection_feedback(user, context, arguments, missing, [], event, step, error.code)
                        continue
                    self.observer.output(event, {"format_version": 1, "basis": arguments.get("basis", "new_information"),
                                                 "inspected_refs": arguments.get("inspected_refs", []),
                                                 "actual_inspections": context.get("inspections", {}),
                                                 "accepted": True}, kind="context", title="Reflection 先看再写门槛")
                    self.observer.output(event, prepared, kind="memory", title="Reflection Mutation 校验结果")
                    if relation_support:
                        self.observer.output(event, {"links": relation_support}, kind="context",
                                             title="Relation 直接来源支持说明（待人工核验）")
                context.pop("pending_mutation", None)
                self._save_workspace(user, state="mutation", context=context)
                self._commit_reflection(user, prepared, watermark, deadline, context)
                return
            if name == "reflection_stop":
                if context.get("last_gate_error"):
                    raise MemoryError("reflection_unresolved_evidence", 409)
                prepared = {"items": [], "links": [], "forget": []}
                self._commit_reflection(user, prepared, watermark, deadline, context)
                return
            raise MemoryError("unknown_reflection_tool", 502)
        raise MemoryError("reflection_tool_budget", 504)

    @staticmethod
    def _reflection_action(context, action, **details):
        context["action_log"] = [*context.get("action_log", []), {"action": action, **details}][-6:]

    def _reflection_feedback(self, user, context, arguments, missing, invalid_links, event, step, code):
        signature = digest([arguments, context.get("last_visible", []), context.get("read_ranges", []),
                            context.get("identity_queries", {})])
        problem = digest([missing, invalid_links, context.get("read_ranges", []),
                          context.get("identity_queries", {})])
        self.observer.output(event, {"format_version": 1, "accepted": False, "reason": code,
            "required": missing, "invalid_links": invalid_links}, kind="context", title="Reflection 提交前反馈")
        if signature == context.get("rejected_proposal") or problem == context.get("rejected_problem"):
            raise MemoryError("reflection_no_evidence_progress", 409)
        context["rejected_proposal"] = signature
        context["rejected_problem"] = problem
        context["last_gate_error"] = {"code": code, "missing": missing[:16], "invalid_links": invalid_links[:8]}
        if invalid_links and not missing:
            if context.get("pending_mutation"):
                context["last_gate_error"]["next_action"] = (
                    "No additional reading is required to repair these relation types. The uncommitted node proposal is under pending_mutation; grounding will be checked after repair. "
                    "Repair/remove the listed relation or return an empty links list with reflection_relations; "
                    "do not call Inspect, Backlink, Evict, or Stop.")
            else:
                context["last_gate_error"]["next_action"] = (
                    "No additional reading is required. Repair or remove the listed invalid relation/immutable-node "
                    "proposal and call reflection_mutation now; do not call Inspect, Backlink, Evict, or Stop.")
        context["protected_refs"] = [v["ref"] for v in missing if v["ref"].startswith("memory:")]
        context["protected_sources"] = [v["ref"] for v in missing if v["ref"].startswith("raw:")]
        # Load only navigation for missing targets; this is not an implicit Inspect.
        for ref in context["protected_refs"]:
            if node := self.store.get(user, ref):
                context.setdefault("references", {})[ref] = self._reference(node, context["question"], "required", user, context.get("old_before"))
        for source_ref in context["protected_sources"]:
            source = self.store.get(user, source_ref)
            if source and (source["ordinal"] < context["old_before"] or source_ref in context.get("new_refs", [])):
                for node in self.store.nodes(user):
                    if source_ref in node.get("source_refs", []):
                        context.setdefault("references", {}).setdefault(node["ref"],
                            self._reference(node, context["question"], "required_source", user, context.get("old_before")))
                        break
        self._reflection_action(context, "proposal_feedback", code=code, missing=len(missing), invalid_relations=len(invalid_links))
        self._save_workspace(user, state="maintenance", context=context)
        remaining = self.config.reflection_steps - step - 1
        # Every missing old body/source needs at least one read and one final call.
        minimum = len({v["ref"] for v in missing if v["need"] != "declare_no_prior_match"}) + 1
        if remaining < minimum:
            raise MemoryError("reflection_material_budget", 409)

    def _commit_reflection(self, user, prepared, watermark, deadline, context=None):
        if prepared.get("filtered_links"):
            raise MemoryError("reflection_invalid_relations", 409)
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
            retained["memories"] = []
            for edge in prepared["links"]:
                if edge not in retained.setdefault("edges", []):
                    retained["edges"].append(edge)
            blocked_sources = {ref for removal in prepared["forget"] for ref in removal["source_refs"] + removal["instruction_refs"]}
            blocked_items = {ref for removal in prepared["forget"] for ref in removal["memory_refs"]}
            blocked_items.update(ref for ref, item in retained.get("items", {}).items() if blocked_sources.intersection(item.get("source_refs", [])))
            for key in ("items", "references", "inspections"):
                retained[key] = {ref: value for ref, value in retained.get(key, {}).items() if ref not in blocked_items}
            for key in ("disclosures", "last_visible", "read_ranges"):
                retained[key] = [v for v in retained.get(key, []) if v["origin_ref"] not in blocked_sources | blocked_items and v.get("item_ref") not in blocked_items]
            retained["edges"] = [e for e in retained.get("edges", []) if not blocked_items.intersection((e["from_ref"], e["to_ref"])) and not blocked_sources.intersection(e["source_refs"])]
            for key in ("prefix_overview", "protected_refs", "protected_sources", "protected_bodies", "last_gate_error", "pending_mutation", "rejected_proposal", "rejected_problem", "identity_queries", "visible_source_refs", "completed_queries", "action_log", "_page_choices"):
                retained.pop(key, None)
            self._bound_workspace(retained)
            self.store.commit_mutation(user, prepared, watermark=watermark,
                                       fingerprint=self.providers.embedding_fingerprint, vectors=vectors, context=retained)
            self.observer.output(event, {"mutation": prepared, "watermark": watermark}, kind="memory", title="Reflection Mutation 提交")

    def _reflection_context(self, user, pending, deadline):
        # Orientation is a bounded discovery expression, never the entire backlog.
        query = excerpt("\n".join(row["text"] for row in pending), min(4000, self.config.batch_chars))
        context = self.store.state(user).get("context") or {"references": {}, "items": {}, "edges": []}
        if context.get("format_version", 0) not in (0, 1, 2):
            raise MemoryError("workspace_version_unknown", 503)
        if context.get("format_version", 0) < 2:
            for key in ("disclosures", "pinned", "inspections", "last_visible", "read_ranges"):
                context.pop(key, None)
        context["format_version"] = 2
        context.setdefault("read_ranges", [])
        context["old_before"] = pending[0]["ordinal"]
        context["old_scope"] = {"before": pending[0]["ordinal"], "empty": self.store.old_scope_empty(user, pending[0]["ordinal"]),
                                "basis": "database_valid_old_sources", "query_performed": False}
        context.pop("last_gate_error", None)
        for key in ("protected_refs", "protected_sources", "protected_bodies", "pending_mutation", "rejected_proposal", "rejected_problem", "completed_queries", "action_log"):
            context.pop(key, None)
        context["identity_queries"] = {}
        context["question"] = query
        context["new_refs"] = [row["ref"] for row in pending]
        context["depths"], context["explored"], context["expanded_refs"] = {}, [], []
        self._refresh_context(user, context, pending)
        with self.observer.span("reflection", "reflection orientation", inputs={
                "question": query, "pending_refs": context["new_refs"]}) as event:
            refs = [] if context["old_scope"]["empty"] else self._search_refs(user, query, context, deadline, mode="reflection")
            self.observer.output(event, {"references": [row["ref"] for row in refs],
                                         "count": len(refs), "orientation_only": True, "old_scope": context["old_scope"]}, kind="context",
                                title="Reflection Orientation 旧记忆候选")
        self._add_context_refs(user, context, refs[:self.config.old_candidates], deadline)
        context["orientation_refs"] = [row["ref"] for row in refs[:self.config.old_candidates]]
        for ref in context["references"]:
            context["depths"].setdefault(ref, 0)
        self._bound_workspace(context)
        return context

    @staticmethod
    def _check_reflection_basis(arguments, context):
        if missing_material(arguments, context):
            raise MemoryError("reflection_orientation_required", 409)

    def _reference(self, row, query, via, user=None, before=None):
        scoped_sources = None
        if user and before and self.store.is_minimum_episode(user, row["ref"]):
            scoped_sources = [s for s in self.store.raw(user, row.get("source_refs", [])) if s["ordinal"] < before]
            row = {**row, "text": episode_text(scoped_sources), "source_refs": [s["ref"] for s in scoped_sources]}
        label = excerpt(re.sub(r"\[[^\]\n]*\]", "", row["text"]).strip(), 140, query)
        reference = {"ref": row["ref"], "kind": row["kind"], "label": label,
                "narrative": f"{via} 命中 {row['kind']} {row['ref']}：{excerpt(row['text'], self.config.preview_chars, query)}",
                "source_refs": row.get("source_refs", []), "status": row.get("status", "active")}
        fragments = row.get("reference_fragments")
        coverage = row.get("reference_coverage")
        if user and row["kind"] == "episode" and self.store.is_minimum_episode(user, row["ref"]):
            sources = scoped_sources if scoped_sources is not None else self.store.raw(user, row.get("source_refs", []))
            branches = [query] + [str(entry.get("branch", "")) for entry in row.get("lineage", [])
                                  if isinstance(entry, dict) and entry.get("branch")]
            fragments, coverage = complementary_passages(sources, branches[:4],
                                                         min(2400, max(500, self.config.preview_chars * 2)),
                                                         max_fragments=4)
        elif not fragments:
            fragments, coverage = complementary_passages([row], [query], self.config.preview_chars, 1)
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
            context.setdefault("references", {})[row["ref"]] = self._reference(row, context.get("question", ""), row.get("via", "inspect"), user, context.get("old_before"))
            context.setdefault("items", {})[row["ref"]] = self._view(row)
            if context.get("old_before") and self.store.is_minimum_episode(user, row["ref"]):
                context["items"][row["ref"]]["scope_omit_body"] = True
            if self.store.get(user, row["ref"]):
                for source_ref in row.get("source_refs", []):
                    source = self.store.get(user, source_ref)
                    if source and (not context.get("old_before") or source["ordinal"] < context["old_before"] or source_ref in context.get("new_refs", [])) and source_ref not in {item["ref"] for item in context.setdefault("sources", [])}:
                        context["sources"].append(self._view(source))
                for edge in self.store.edges(user, row["ref"]):
                    value = self._edge_view(user, edge)
                    if value not in context.setdefault("edges", []):
                        context["edges"].append(value)
            context["memories"] = []

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
                if context.get("old_before") and self.store.is_minimum_episode(user, ref):
                    items[ref]["scope_omit_body"] = True
        context["items"] = items
        context["memories"] = []
        refs = {}
        for ref in context.get("references", {}):
            node = self.store.get(user, ref)
            if node:
                refs[ref] = self._reference(node, context.get("question", ""), "context", user, context.get("old_before"))
        context["references"] = refs
        sources = {row["ref"]: self._view(row) for row in pending}
        for item in items.values():
            for ref in item.get("source_refs", []):
                source = self.store.get(user, ref)
                if source and (not context.get("old_before") or source["ordinal"] < context["old_before"] or ref in context.get("new_refs", [])):
                    sources[ref] = self._view(source)
        context["sources"] = list(sources.values())
        context["edges"] = [edge for edge in context.get("edges", [])
                            if self.store.get(user, edge["from_ref"]) and self.store.get(user, edge["to_ref"])]
        valid = []
        for value in context.get("disclosures", []):
            origin = self.store.get(user, value["origin_ref"])
            owner = self.store.get(user, value.get("item_ref", value["origin_ref"]))
            if origin and owner and digest(origin["text"]) == value["content_digest"]:
                valid.append(value)
        context["disclosures"] = valid
        ids = {value["fragment_id"] for value in valid}
        context["pinned"] = [key for key in context.get("pinned", []) if key in ids]
        for key in ("last_visible", "read_ranges"):
            context[key] = [value for value in context.get(key, [])
                if (origin := self.store.get(user, value["origin_ref"])) and digest(origin["text"]) == value["content_digest"]
                and (not value.get("item_ref") or self.store.get(user, value["item_ref"]))]
        context["inspections"] = {ref: version for ref, version in context.get("inspections", {}).items()
                                   if ref in items and digest(items[ref]["text"]) == version}
        self._bound_workspace(context)

    def _bound_workspace(self, context):
        context["memories"] = []  # items is the authoritative map; do not serialize it twice.
        context["read_ranges"] = context.get("read_ranges", [])[-self.config.max_nodes * 8:]
        # Immutable episode bodies can be much larger than a page. Reflection
        # reads their scoped raw pages; retaining the entire hidden episode is
        # not required by the page pin and must not create a false hard budget.
        for item in context.get("items", {}).values():
            if item.get("scope_omit_body"):
                if item.get("text"):
                    item["content_digest"] = digest(item["text"])
                    item["body_chars"] = len(item["text"])
                item["text"] = ""
        protected = set(context.get("protected_refs", [])) | set(context.get("protected_bodies", []))
        protected.update(value.get("item_ref") for value in context.get("disclosures", [])
                         if value["fragment_id"] in context.get("pinned", []))
        # Old sources are reloadable. Keep exact short views rather than another
        # copy of long code/source bodies; current working is a separate payload.
        context["sources"] = [row if row["ref"] in context.get("new_refs", []) else
            self._model_row(row, context.get("question", ""), 240) for row in context.get("sources", [])]
        limit = 2 * self.config.context_chars
        def serialized_size():
            # WorkingMemory is durable in raw_events, never duplicated in the
            # retained Workspace. In-memory sources still serve mutation checks.
            return len(dumps({**{k: v for k, v in context.items() if not k.startswith("_")}, "sources": [v for v in context.get("sources", [])
                if v["ref"] not in context.get("new_refs", [])]}))
        while (serialized_size() > limit or len(context.get("items", {})) > self.config.max_nodes
               or len(context.get("references", {})) > self.config.candidate_limit):
            # Protect the required body/range, not every old source page of its
            # owner. Fold optional pages before evicting entire useful nodes.
            optional = [v for v in context.get("disclosures", [])
                        if v["fragment_id"] not in context.get("pinned", [])
                        and v["origin_ref"] not in protected | set(context.get("protected_sources", []))]
            if serialized_size() > limit and optional:
                value = optional[0]
                context["disclosures"].remove(value)
                context["last_visible"] = [v for v in context.get("last_visible", []) if v["fragment_id"] != value["fragment_id"]]
                continue
            visible_origins = {v["origin_ref"] for v in visible_fragments({
                "disclosures": context.get("disclosures", []), "references": context.get("references", {})})}
            source_keep = visible_origins | set(context.get("new_refs", [])) | set(context.get("protected_sources", []))
            optional_sources = [v for v in context.get("sources", []) if v["ref"] not in source_keep]
            if serialized_size() > limit and optional_sources:
                context["sources"].remove(optional_sources[0])
                continue
            refs = [ref for ref in context.get("items", {}) if ref not in protected]
            if refs:
                ref = refs[0]
                context["items"].pop(ref)
                context["disclosures"] = [v for v in context.get("disclosures", []) if v.get("item_ref") != ref]
                context["last_visible"] = [v for v in context.get("last_visible", []) if v.get("item_ref") != ref]
                source_refs = set(context.get("new_refs", [])) | {r for row in context["items"].values() for r in row.get("source_refs", [])}
                context["sources"] = [v for v in context.get("sources", []) if v["ref"] in source_refs]
                continue
            refs = [ref for ref in context.get("references", {}) if ref not in protected]
            if not refs:
                raise MemoryError("protected_workspace_budget", 413)
            ref = refs[0]
            context["references"].pop(ref)
            context["edges"] = [edge for edge in context.get("edges", []) if ref not in (edge["from_ref"], edge["to_ref"])]

    def _save_workspace(self, user, *, state=None, context=None):
        if context is not None:
            self._bound_workspace(context)
            context = {**{k: v for k, v in context.items() if not k.startswith("_")}, "sources": [v for v in context.get("sources", [])
                       if v["ref"] not in context.get("new_refs", [])]}
        self.store.save_workspace(user, state=state, context=context)

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
            before = context.get("old_before") if mode == "reflection" else None
            lexical = self.store.lexical(user, branch, self.config.candidate_limit, before=before)
            with self.observer.span("retrieve", "query.lexical", inputs={"query": branch, "mode": mode, "scope_before": before}) as event:
                self.observer.candidates(event, [self._view(row) | {"score": row["score"], "channel": "bm25"} for row in lexical])
            for row in lexical:
                current = candidates.setdefault(row["ref"], {**row, "score": 0, "lineage": []})
                current["score"] = current.get("score", 0) + row["score"]
                current["lineage"].append({"branch": branch, "channel": "bm25", "rank": row.get("lexical_rank")})
            if self.config.embedding_enabled:
                vectors = list(self.store.vector_rows(user, self.providers.embedding_fingerprint, before=before))
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
                    with self.observer.span("retrieve", "query.embedding", inputs={"query": branch, "mode": mode, "scope_before": before,
                            "mixed_episode_policy": "excluded from old vector candidates; old lexical projection remains" if before else None}) as event:
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
                reference = self._reference(row, query, reason, user, context.get("old_before"))
                narrative = excerpt(row["text"], size, query)
                coverage = "full" if len(row["text"]) <= size else "excerpt"
                branches = [query]
                for entry in row.get("lineage", []):
                    branch = str(entry.get("branch", "")).strip()
                    if branch and branch not in branches:
                        branches.append(branch)
                    if len(branches) == 4:
                        break
                # One range representation for raw and derived content. Never
                # carry coordinates from a prior, differently cropped string.
                origin_rows = self.store.raw(user, row.get("source_refs", [])) if (
                    row["kind"] == "episode" and self.store.is_minimum_episode(user, row["ref"])) else [row]
                if context.get("old_before"):
                    origin_rows = [origin for origin in origin_rows if not origin["ref"].startswith("raw:") or origin["ordinal"] < context["old_before"]]
                hit_fragments, ranges = complementary_passages(origin_rows, branches, max(160, size), max(1, min(4, len(branches))))
                narrative = excerpt(reference["label"], min(size, 140))
                coverage = {"source_count": len(origin_rows), "complete": all(v.get("complete") for v in ranges),
                            "shown_ranges": [span for v in ranges for span in v["shown_ranges"]],
                            "omitted_count": sum(not v["included"] for v in ranges)}
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
                frozen_choices = Choices.freeze(projected["candidates"])
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
                    if invalid_positions:
                        raise MemoryError("selection_invalid_position", 502)
                    raw_selected = frozen_choices.subset(positions)
                    positions = unique_positions
                else:
                    raise MemoryError("selection_invalid_position", 502)
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
        context["query_roots"] = list(pool)
        for step in range(self.config.search_steps):
            self._check_deadline(deadline)
            done = {tuple(entry) for entry in context["explored"]}
            context["frontier"] = [ref for ref in context["references"]
                if self._page_options(request.user_id, ref, context) or (ref, "backlinks") not in done]
            if not context["frontier"]:
                break
            context["terminal_step"] = step == self.config.search_steps - 1
            action = self._next_bfs_action(request.user_id, request.query, context, deadline)
            if action.action == "stop":
                break
            ref = action.ref
            if not ref or ref not in context["references"] or (action.action == "backlinks" and (ref, action.action) in done):
                with self.observer.span("retrieve", "bfs invalid or repeated action", inputs=action.model_dump()) as event:
                    self.observer.output(event, {"handled": "stop", "reason": "unknown_or_repeated_operation"}, kind="context")
                break
            neighbors = self._explore(request.user_id, ref, action.action, context, request.query, deadline, action.page_position)
            for row in neighbors:
                pool.setdefault(row["ref"], {**row, "score": pool.get(ref, {}).get("score", 0.01) * 0.8})
            with self.observer.span("retrieve", "bfs step", inputs={"step": step, "action": action.model_dump()}) as event:
                self.observer.output(event, {"explored": context["explored"],
                    "references": list(context["references"]), "edges": context["edges"],
                    "depths": context["depths"]}, kind="context", title="BFS 上下文增量")
        with self.observer.span("context", "search final pack", inputs={"candidates": list(pool)}) as event:
            rows = self._assemble(request.user_id, request.query, list(pool.values()), request.top_k, request.query, context=context)
            self.observer.output(event, {"data": rows, "explored": context["explored"]}, kind="result", title="Search 最终证据装箱")
        return {"data": rows}

    def _explore(self, user, ref, action, context, query, deadline, page_position=None):
        """Shared graph reads; Reflection and standard Search keep separate state."""
        self._check_deadline(deadline)
        key = [ref, action]
        if action != "inspect" and key in context.setdefault("explored", []):
            raise MemoryError("repeated_graph_operation", 502)
        if key not in context.setdefault("explored", []):
            context["explored"].append(key)
        depth = context.setdefault("depths", {}).get(ref, 0)
        if action == "inspect":
            self._read_page(user, ref, context, page_position)
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
            context["references"][other] = self._reference(node, query, node["via"], user, context.get("old_before"))
            context["depths"][other] = min(context["depths"].get(other, depth + 1), depth + 1)
            context.setdefault("paths", []).append({"from_ref": ref, "to_ref": other,
                "action": action, "depth": depth + 1,
                "edges": [edge for edge in edges if other in (edge["from_ref"], edge["to_ref"])],
                "selected": action == "backlinks"})
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
        projected = self._model_context(context)
        choices = self._visible_choices(user, context, projected, context.get("frontier", []))
        frontier = [row["ref"] for row in choices.rows]
        tools = [_tool("bfs_stop", "Stop exploration because evidence is sufficient or the final decision is reached.",
                       {"type": "object", "properties": {"action": {"type": "string", "enum": ["stop"]}}})]
        if not context.get("terminal_step"):
            for action in ("inspect", "backlinks"):
                allowed = [row["position"] for row in choices.rows if action in row["allowed_actions"]]
                if allowed:
                    properties = {
                            "action": {"type": "string", "enum": [action]},
                            "frontier_position": {"type": "integer", "enum": allowed},
                            "reason": {"type": ["string", "null"]}}
                    if action == "inspect":
                        properties.pop("frontier_position")
                        properties["target"] = choices.inspect_target_schema("frontier_position")
                    tools.append(_tool("bfs_" + action, "Choose one allowed reference position. Inspect target binds a reference to its offered pages; page_position=null reads next relevant unread page. Backlinks takes only frontier_position and reason.",
                        {"type": "object", "properties": properties}))
        with self.observer.span("retrieve", "bfs action", inputs={"query": query, "context": context}) as event:
            try:
                name, data = self._call_tool("bfs", "Explore the supplied memory graph. Return exactly ONE tool call and no prose. Choose a numbered context.choices entry and an allowed action. Inspect page_position=null reads the next query-relevant unread page; other positions refer to that choice's pages. Read new links or further pages as needed. Stop when evidence is sufficient; the last decision must stop. Never answer.", {"query": query, "context": projected}, tools, deadline)
            except MemoryError as error:
                # A malformed structured decision is local to optional graph
                # expansion. Preserve query/Inspect evidence already in hand;
                # provider, timeout, and other dependency errors still fail.
                if error.code != "model_tool_output_invalid":
                    raise
                context["bfs_terminal_reason"] = error.code
                with self.observer.span("retrieve", "bfs terminalized", inputs={
                        "reason": error.code}) as terminal:
                    self.observer.output(terminal, {"handled": "stop",
                        "reason": error.code, "evidence_preserved": True},
                        kind="context", title="BFS 结构化决策无效，保留已有证据")
                return BfsAction(action="stop", reason="invalid structured decision; preserve current evidence")
            self._record_visible(context, projected, "bfs")
            if name == "bfs_inspect":
                data = {**{k: v for k, v in data.items() if k != "target"}, **data.get("target", {})}
            try:
                action = BfsAction.model_validate(data)
            except ValidationError:
                # A malformed follow-up decision must not discard the query
                # candidates already collected.  The public Search contract
                # returns evidence, so terminate this bounded exploration and
                # keep the observable failure reason instead of retrying the
                # model or turning a useful partial result into a 502.
                context["bfs_terminal_reason"] = "bfs_action_invalid"
                with self.observer.span("retrieve", "bfs terminalized", inputs={
                        "reason": "bfs_action_invalid", "data": data}) as terminal:
                    self.observer.output(terminal, {"handled": "stop",
                        "reason": "bfs_action_invalid", "evidence_preserved": True},
                        kind="context", title="BFS 动作异常后保留已有证据")
                return BfsAction(action="stop", reason="invalid model action; preserve current evidence")
            if name != "bfs_" + action.action:
                context["bfs_terminal_reason"] = "bfs_action_invalid"
                with self.observer.span("retrieve", "bfs terminalized", inputs={
                        "reason": "bfs_action_invalid", "tool": name,
                        "action": action.model_dump()}) as terminal:
                    self.observer.output(terminal, {"handled": "stop",
                        "reason": "bfs_action_invalid", "evidence_preserved": True},
                        kind="context", title="BFS 工具与动作不一致")
                return BfsAction(action="stop", reason="tool/action mismatch; preserve current evidence")
            if action.action == "stop":
                action = action.model_copy(update={"ref": None})
            else:
                if context.get("terminal_step"):
                    raise MemoryError("bfs_terminal_action", 502)
                try:
                    resolved = choices.resolve(data.get("frontier_position"), action.action)
                except MemoryError as error:
                    # The model may repeat a stale choice after the preceding
                    # Inspect changed the unread-page set.  This is a local
                    # protocol miss, not a provider dependency failure: stop
                    # the graph walk with the query/Inspect evidence intact.
                    if error.code not in {"reference_invalid_position", "reference_action_not_allowed"}:
                        raise
                    context["bfs_terminal_reason"] = error.code
                    with self.observer.span("retrieve", "bfs terminalized", inputs={
                            "reason": error.code, "action": action.model_dump(),
                            "frontier": choices.rows}) as terminal:
                        self.observer.output(terminal, {"handled": "stop",
                            "reason": error.code, "evidence_preserved": True},
                            kind="context", title="BFS 过期选择后保留已有证据")
                    return BfsAction(action="stop", reason=f"{error.code}; preserve current evidence")
                action = action.model_copy(update={"ref": resolved})
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

    def _assemble(self, user, query, rows, top_k, preferred_query, *, context=None):
        frozen = freeze_pack(self.store, user, query, rows, context or {}, self.config)
        result, audit = pack_frozen(frozen, top_k)
        with self.observer.span("context", "evidence packing decisions", inputs={"top_k": top_k}) as event:
            self.observer.output(event, {"frozen_pack": frozen, "top_k": top_k}, kind="context", title="装箱对照冻结输入")
            self.observer.output(event, audit, kind="context")
        return result

    def _assemble_legacy(self, user, query, rows, top_k, preferred_query):
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

    def _record_visible(self, context, projected, purpose, working=()):
        """Receipt after a successful main decision; Select cannot release pins."""
        shown = visible_fragments(projected, working)
        context["last_visible"] = [range_receipt(v) for v in shown]
        disclosed = {v["fragment_id"]: v for v in context.get("disclosures", [])}
        context["pinned"] = [key for key in context.get("pinned", [])
                             if key in disclosed and not range_is_visible(disclosed[key], shown)]
        with self.observer.span("context", "evidence disclosure receipt", inputs={"purpose": purpose}) as event:
            self.observer.output(event, {"format_version": 1, "status": "call_returned",
                "disclosures": shown, "choices": projected.get("choices", []),
                "coverage_basis": "all_serialized_fragments", "explicit_read_ranges": context.get("read_ranges", []),
                "projection": projected.get("projection", {})}, kind="context")

    def _page_options(self, user, ref, context, shown=None):
        node = self.store.get(user, ref)
        if not node:
            return []
        mixed = context.get("old_before") and self.store.is_minimum_episode(user, ref) and any(
            row["ordinal"] >= context["old_before"] for row in self.store.raw(user, node.get("source_refs", [])))
        body = [] if mixed else [node]
        sources = body + [row for row in self.store.raw(user, node.get("source_refs", []))
                            if not context.get("old_before") or row["ordinal"] < context["old_before"] or row["ref"] in context.get("new_refs", [])]
        if shown is None:
            shown = visible_fragments(self._model_context(context))
        read = context.get("read_ranges", context.get("disclosures", []))
        width = min(1800, max(100, self.config.context_chars // 8))
        values = [value for source in sources for value in pages(source, width)
                  if not (range_is_visible(value, shown) and range_is_visible(value, read))]
        words = set(terms(context.get("question", "")))
        values.sort(key=lambda value: (value["origin_ref"] not in context.get("protected_sources", []),
                                       (value["origin_ref"] != ref) if context.get("old_before") else 0,
                                       -len(words.intersection(terms(value["text"]))),
                                       value["origin_ref"] != ref, value["start"]))
        return values

    def _read_page(self, user, ref, context, position=None):
        offered = context.get("_page_choices", {}).get(ref)
        if offered is None:
            values = self._page_options(user, ref, context)
        else:
            values = []
            for value in offered:
                source = self.store.get(user, value["origin_ref"])
                if not source or digest(source["text"]) != value["content_digest"]:
                    raise MemoryError("inspect_stale_page", 502)
                values.append(fragment(source, value["start"], value["end"]))
        if not values:
            raise MemoryError("repeated_graph_operation", 502)
        index = 0 if position is None else position
        if type(index) is not int or not 0 <= index < min(8, len(values)):
            raise MemoryError("inspect_invalid_page", 502)
        value = {**values[index], "item_ref": ref}
        context["disclosures"] = [v for v in context.get("disclosures", []) if v["fragment_id"] != value["fragment_id"]] + [value]
        context.setdefault("pinned", []).append(value["fragment_id"])
        # Decide capacity before exposing the tool result. Never silently crop it later.
        self._model_context(context)
        context.setdefault("inspections", {})[ref] = digest(self.store.get(user, ref)["text"])
        reads = context.setdefault("read_ranges", [])
        if not any(v["fragment_id"] == value["fragment_id"] and v.get("item_ref") == ref for v in reads):
            reads.append(range_receipt(value))
        if context.get("old_before") and value["origin_ref"] == ref and self.store.get(user, ref)["kind"] != "episode":
            context["protected_bodies"] = list(dict.fromkeys([*context.get("protected_bodies", []), ref]))

    def _visible_choices(self, user, context, projected, refs, *, evict=False):
        rows, allowed = [], {}
        shown = visible_fragments(projected)
        context["_page_choices"] = {}
        done = {tuple(pair) for pair in context.get("explored", [])}
        for ref in refs:
            if ref not in projected.get("references", {}):
                continue
            options = self._page_options(user, ref, context, shown)
            context["_page_choices"][ref] = [range_receipt(v) for v in options[:8]]
            reference = projected["references"][ref]
            row = {"ref": ref, "kind": reference["kind"], "label": reference.get("label", ""),
                   "narrative": excerpt(reference.get("narrative", ""), 180), "unread_page_count": len(options)}
            row["pages"] = [{"position": i, "origin_ref": value["origin_ref"],
                             "range": value["shown_range"], "view": "item body" if value["origin_ref"] == ref else "original source",
                             "preview": excerpt(value["text"], 100), "role": value.get("role"),
                             "source_time": source_date(value.get("source_time"))}
                            for i, value in enumerate(options[:8])]
            actions = (["inspect"] if options else []) + (["backlinks"] if (ref, "backlinks") not in done else [])
            if evict and not any(v.get("item_ref") == ref and v["fragment_id"] in context.get("pinned", [])
                                 for v in context.get("disclosures", [])) and ref not in context.get("protected_refs", []) and ref not in context.get("protected_bodies", []):
                actions.append("evict")
            rows.append(row)
            allowed[ref] = actions
        choices = Choices.freeze(rows, allowed)
        projected["choices"] = list(choices.rows)
        control = projected.get("reflection_control")
        if control and context.get("last_gate_error"):
            by_ref = {row["ref"]: row for row in choices.rows}
            actions = []
            for need in context["last_gate_error"].get("missing", [])[:8]:
                row = by_ref.get(need.get("ref")) or next((row for row in choices.rows
                    if any(page["origin_ref"] == need["ref"] for page in row["pages"])), {})
                ref = need["ref"]
                node = context.get("items", {}).get(ref)
                ready = False
                if need["need"] == "same_version_inspect_full_body_in_final_call" and node:
                    version = node.get("content_digest") or digest(node["text"])
                    body = {"origin_ref": ref, "content_digest": version, "start": 0,
                            "end": node.get("body_chars", len(node["text"]))}
                    ready = range_is_visible(body, shown) and range_is_visible(body, context.get("read_ranges", []))
                elif need["need"] == "newly_cited_source_visible":
                    ready = any(v["origin_ref"] == ref for v in shown) or ref in context.get("new_refs", [])
                elif need["need"] == "declare_no_prior_match":
                    ready = True  # Only the proposal flag remains; no additional read.
                actions.append({**need, "material_ready": ready,
                    "next_action": "resubmit_mutation_with_current_evidence" if ready else "supply_required_material",
                    "reference_position": row.get("position"),
                    "pages": [] if ready else [p for p in row.get("pages", []) if p["origin_ref"] == ref][:3]})
            control["required_actions"] = actions
            control["last_gate_error"] = {**control["last_gate_error"],
                "missing": [need for need in actions if not need["material_ready"]],
                "note": "Last rejected proposal only; resubmit once its required material is ready. Source pages are optional unless explicitly missing."}
        return choices


def json_load(value):
    if isinstance(value, list):
        return value
    try:
        return __import__("json").loads(value or "[]")
    except (TypeError, ValueError):
        return []
