"""Artifact-backed API observations and a transparent local BM25 reference method."""
from __future__ import annotations

import hashlib
import json
import uuid

from benchmark.core import _add_error, _search_results
from benchmark.lexical_study import rank
from benchmark.targets import TargetResponse
from dataset.selection import canonical_hash


class Artifacts:
    def __init__(self, directory):
        self.directory = directory
        (directory / "artifacts").mkdir(exist_ok=True)

    def write(self, kind, value):
        identity = uuid.uuid4().hex
        relative = f"artifacts/{identity}.json"
        data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (self.directory / relative).write_bytes(data)
        return {"id": identity, "kind": kind, "artifact": relative,
                "sha256": hashlib.sha256(data).hexdigest(), "locator": "/"}

    def text(self, kind, text, *, title):
        """Opt-in display contract for native methods; never pass credentials here."""
        if not isinstance(text, str) or not isinstance(title, str) or not title.strip():
            raise ValueError("display artifacts require text and a title")
        return self.write(kind, {"schema_version": "amlink.artifact.v1", "title": title, "text": text})


class ObservedTarget:
    """Method receives API payloads and execution IDs only, never annotations/gold.

    Wrapping a remote adapter captures its boundary; it does not claim to see its
    internal model calls. Native methods can emit children via set_observation_parent.
    """
    def __init__(self, target, recorder, artifacts, target_name):
        self.target, self.recorder, self.artifacts, self.target_name = target, recorder, artifacts, target_name

    def set_observation_context(self, **context):
        self.context = context

    def _call(self, operation, request):
        with self.recorder.span(operation, name=f"{operation} API 边界", **self.context) as root:
            root["inputs"] = [self.artifacts.write("source" if operation == "add" else "query", request)]
            if hasattr(self.target, "set_observation_parent"):
                self.target.set_observation_parent(root)
            response = getattr(self.target, operation)(request)
            root["outputs"] = [self.artifacts.write("memory" if operation == "add" else "result", response.body)]
            error = _add_error(response, request, self.target_name) if operation == "add" else _search_results(response, self.target_name, request["top_k"])[0]
            if error:
                retryable = response.status_code in {408, 425, 429, 500, 502, 503, 504}
                if operation == "add" and response.status_code in {409, 524}:
                    retryable = True
                root["status"], root["error"] = "error", {"code": error, "retryable": retryable}
            return response

    def add(self, request):
        return self._call("add", request)

    def search(self, request):
        return self._call("search", request)


class LexicalMemory:
    """In-memory, per-user raw-message store. No inference, vector model, or Answer."""
    def __init__(self, recorder, artifacts):
        self.recorder, self.artifacts = recorder, artifacts
        self.users, self.replays = {}, {}

    def set_observation_parent(self, parent):
        self.parent = parent

    def span(self, operation, name):
        return self.recorder.span(operation, name=name, parent=self.parent,
            **{k: self.parent[k] for k in ("record_id", "task_id", "request_id")})

    def add(self, request):
        key, digest = request["request_id"], canonical_hash(request)
        response = {"success": True, **{k: request[k] for k in ("request_id", "user_id", "session_id")}}
        if key in self.replays:
            if self.replays[key] != digest:
                return TargetResponse(409, error_code="idempotency_conflict")
            self.parent["replay"] = "cached"
            return TargetResponse(200, response)
        with self.span("store", "保存原始消息及角色、来源时间") as event:
            event["inputs"] = self.parent["inputs"]
            rows = self.users.setdefault(request["user_id"], [])
            new = [{"id": f"{key}:{i}", "content": m["content"], "role": m["role"],
                    "timestamp": m.get("timestamp"), "session_id": request["session_id"]}
                   for i, m in enumerate(request["messages"])]
            ref = self.artifacts.write("memory", {"operation": "append", "items": new, "user_total": len(rows)+len(new)})
            event["outputs"] = [ref]
            event["links"] = [{"from_id": ref["id"], "to_id": event["inputs"][0]["id"], "relation": "derived_from"}]
            rows.extend({**r, "ref": ref} for r in new)
            self.replays[key] = digest
        return TargetResponse(200, response)

    def search(self, request):
        rows = self.users.get(request["user_id"], [])
        by_id = {r["id"]: r for r in rows}
        with self.span("retrieve", "BM25 对已存消息打分；保留前 20 个正分候选") as event:
            ranked = rank([(r["id"], r["content"]) for r in rows], request["query"])
            result = [{"id": key, "content": by_id[key]["content"], "score": score}
                      for key, score in ranked[:request["top_k"]]]
            event["inputs"] = list(self.parent["inputs"])
            for i, (key, score) in enumerate(ranked[:max(20, request["top_k"])], 1):
                memory = by_id[key]["ref"]
                if memory not in event["inputs"]:
                    event["inputs"].append(memory)
                ref = self.artifacts.write("result", {"rank": i, "score": score, "memory_id": key,
                    "selected": i <= request["top_k"], "content": by_id[key]["content"],
                    "corpus_size": len(rows), "positive_candidates": len(ranked)})
                event["outputs"].append(ref)
                event["links"].append({"from_id": ref["id"], "to_id": memory["id"], "relation": "retrieved_from"})
                event["candidates"].append({"ref_id": ref["id"], "rank": i, "score": score, "selected": i <= request["top_k"]})
        return TargetResponse(200, {"data": result})
