"""Offline comparison using the exact frozen packing inputs. Not the Search API."""
import time

from .packing import pack_frozen, restrict_frozen
from .text import digest


def compare(engine, frozen, top_k):
    from .engine import _tool
    deterministic, baseline_audit = pack_frozen(frozen, top_k)
    groups = [{"position": i, "root": group["ref"], "members": group["members"],
               "edges": group["edges"], "fragments": [{"position": j, **value} for j, value in enumerate(group["fragments"])]}
              for i, group in enumerate(frozen["groups"])]
    schema = {"type": "object", "properties": {"groups": {"type": "array", "maxItems": top_k,
        "items": {"type": "object", "properties": {"position": {"type": "integer"},
                "fragment_positions": {"type": "array", "items": {"type": "integer"}}}}}}}
    payload = {"question": frozen["question"], "groups": groups, "top_k": top_k,
               "context_chars": frozen["context_chars"], "result_chars": frozen["result_chars"]}
    start = time.monotonic()
    _, selection = engine._call_tool("packing_comparison", "Choose and order supplied groups and existing fragment positions to preserve complementary evidence and graph support. Do not write evidence, infer facts or answer. This is an offline comparison.",
                                    payload, [_tool("packing_comparison", "Select existing evidence positions only.", schema)],
                                    start + engine.config.request_seconds)
    with engine.observer.span("context", "offline packing selection", inputs={"frozen_sha256": digest(frozen)}) as event:
        engine.observer.output(event, selection, kind="context")
    restricted = restrict_frozen(frozen, selection)
    candidate, candidate_audit = pack_frozen(restricted, top_k)
    result = {"format_version": 1, "frozen_sha256": digest(frozen), "selection": selection,
              "deterministic": {"data": deterministic, "audit": baseline_audit},
              "llm": {"data": candidate, "audit": candidate_audit},
              "model_calls": 1, "elapsed_seconds": time.monotonic() - start,
              "semantic_quality": "not_evaluated", "packing_unit": "evidence_group"}
    with engine.observer.span("context", "offline packing comparison", inputs={"frozen_sha256": result["frozen_sha256"]}) as event:
        engine.observer.output(event, result, kind="result")
    return result
