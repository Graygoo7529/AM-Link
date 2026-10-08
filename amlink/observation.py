"""Native observation v1 bridge; no private model reasoning is requested."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from .errors import MemoryError
from .text import dumps


class Observer:
    def __init__(self, recorder=None, artifacts=None):
        self.recorder, self.artifacts = recorder, artifacts
        self.current = ContextVar(f"amlink_span_{id(self)}", default=None)

    def bind(self, parent):
        self.current.set(parent)

    @contextmanager
    def span(self, operation, name, inputs=None):
        parent = self.current.get()
        if self.recorder is None or parent is None:
            yield None
            return
        with self.recorder.span(operation, name=name, parent=parent,
                **{k: parent[k] for k in ("record_id", "task_id", "request_id")}) as event:
            token = self.current.set(event)
            try:
                if inputs is not None:
                    event["inputs"] = [self.artifacts.text(
                        "source" if operation == "store" else "context", dumps(inputs), title=name + " 输入")]
                else:
                    event["inputs"] = list(parent["inputs"])
                yield event
            except MemoryError as error:
                event["error"] = {"code": error.code, "retryable": error.retryable}
                raise
            finally:
                self.current.reset(token)

    def output(self, event, value, *, kind="memory", title="记忆步骤产物"):
        if event is None:
            return
        ref = self.artifacts.text(kind, dumps(value), title=title)
        event["outputs"].append(ref)
        for source in event["inputs"]:
            event["links"].append({"from_id": ref["id"], "to_id": source["id"], "relation": "derived_from"})

    def candidates(self, event, rows, selected=()):
        if event is None:
            return
        for rank, row in enumerate(rows, 1):
            ref = self.artifacts.text("memory", dumps(row), title=row.get("ref", "记忆候选"))
            event["outputs"].append(ref)
            event["candidates"].append({"ref_id": ref["id"], "rank": rank,
                "score": row.get("score"), "selected": row.get("ref") in selected})

