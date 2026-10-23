from dataclasses import replace
from contextlib import contextmanager

import pytest

from amlink.config import Config
from amlink.engine import Engine
from amlink.evidence import complementary_passages, passages, fragment
from amlink.text import digest
from amlink.errors import MemoryError
from amlink.observation import Observer
from amlink.store import Store
from amlink.schemas import AddRequest


def source(ref, text, ordinal):
    return {"ref": ref, "text": text, "role": "user", "ordinal": ordinal,
            "session_id": "s", "source_time": None}


def test_complementary_passages_reports_multiple_sources_and_ranges():
    rows = [source("raw:a", "Maya met Robin at the studio.", 1),
            source("raw:b", "The meeting moved to Friday afternoon.", 2),
            source("raw:c", "They agreed to use the blue notebook.", 3)]
    fragments, coverage = complementary_passages(rows, ["Maya Robin", "Friday", "blue notebook"], 900)
    assert len(fragments) == 3
    assert {fragment["source_ref"] for fragment in fragments} == {"raw:a", "raw:b", "raw:c"}
    assert all(fragment["shown_range"][0] >= 0 for fragment in fragments)
    assert all(entry["included"] and entry["shown_ranges"] for entry in coverage)


def test_passages_keeps_partial_ranges_for_each_source():
    rows = [source("raw:a", "alpha " * 200, 1), source("raw:b", "beta " * 200, 2)]
    _, coverage = passages(rows, "alpha beta", 500)
    assert any(entry["included"] and not entry["complete"] for entry in coverage)
    assert all("shown_range" in entry for entry in coverage if entry["included"])


def test_empty_mutation_is_not_risky_just_because_of_basis_label(tmp_path):
    engine = Engine(replace(Config(mode="graph", embedding_enabled=False),
                            db_path=str(tmp_path / "memory.sqlite3")),
                    Store(tmp_path / "memory.sqlite3"), object(), Observer())
    try:
        context = {"items": {}, "explored": []}
        engine._check_reflection_basis({"basis": "add_relation", "links": [],
                                       "items": [], "inspected_refs": []}, context)
        context["explored"] = [["memory:fact-old", "inspect"]]
        engine._check_reflection_basis({"basis": "add_relation", "links": [],
                                        "items": [], "inspected_refs": ["memory:fact-old"]}, context)
    finally:
        engine.store.close()


def test_reference_projection_carries_fragments_into_context(tmp_path):
    store = Store(tmp_path / "memory.sqlite3")
    class Provider:
        embedding_fingerprint = "test"
    engine = Engine(replace(Config(mode="raw", embedding_enabled=False),
                            db_path=str(tmp_path / "memory.sqlite3")),
                    store, Provider(), Observer())
    try:
        engine.add(AddRequest(request_id="a", user_id="u", session_id="s", messages=[
            {"role": "user", "content": "Maya met Robin on Friday at the studio."},
            {"role": "assistant", "content": "They agreed to use the blue notebook."},
        ]))
        node = store.nodes("u")[0]
        reference = engine._reference(node, "Friday blue notebook", "query", "u")
        assert reference["evidence_fragments"]
        assert reference["coverage"]
        assert all("source_ref" in fragment for fragment in reference["evidence_fragments"])
        projected = engine._model_context({"question": "Friday", "references": {
            reference["ref"]: {**reference, "evidence_fragments": [fragment(source("raw:long", "x" * 900, 1), 0, 900)]},
        }, "items": {}, "sources": [], "edges": []})
        shown = projected["references"][reference["ref"]]["evidence_fragments"][0]
        assert shown["model_projection"]["shown_chars"] < shown["model_projection"]["source_text_chars"]
        assert shown["model_projection"]["complete"] is False
        assert shown["end"] - shown["start"] == len(shown["text"])
    finally:
        store.close()


class PackingObserver(Observer):
    def __init__(self):
        super().__init__()
        self.outputs = {}

    @contextmanager
    def span(self, operation, name, inputs=None):
        yield name

    def output(self, event, value, **kwargs):
        self.outputs[event] = value


@pytest.fixture
def packing_engine():
    store = Store(":memory:")
    observer = PackingObserver()
    class Provider:
        embedding_fingerprint = "test"
    engine = Engine(Config(mode="raw", embedding_enabled=False), store, Provider(), observer)
    yield engine, observer
    store.close()


def test_final_pack_keeps_all_short_sources_when_the_card_has_room(packing_engine):
    engine, observer = packing_engine
    texts = [f"Archive evidence {index}: the parcel has code marker{index}." for index in range(6)]
    engine.add(AddRequest(request_id="six", user_id="u", session_id="s",
                         messages=[{"role": "user", "content": text} for text in texts]))
    rows = engine._assemble("u", "Archive evidence", engine.store.nodes("u"), 1, "Archive evidence")
    assert all(text in rows[0]["content"] for text in texts)
    decision = observer.outputs["evidence packing decisions"]["decisions"][0]
    assert decision["closure"] == "complete"
    assert len(decision["evidence_units"]) == 6


def test_final_pack_records_reused_and_unavailable_sources(packing_engine):
    engine, observer = packing_engine
    engine.add(AddRequest(request_id="one", user_id="u", session_id="s",
                         messages=[{"role": "user", "content": "The parcel is red."}]))
    episode = engine.store.nodes("u")[0]
    raw_ref = episode["source_refs"][0]
    items = [{"ref": "memory:fact-parcel", "kind": "fact", "text": "Parcel colour.",
              "source_refs": [raw_ref]},
             {"ref": "memory:fact-missing", "kind": "fact", "text": "Missing provenance.",
              "source_refs": ["raw:missing"]}]
    engine.store.commit_mutation("u", {"items": items, "links": [], "forget": []},
                                 watermark=1, fingerprint="test", vectors={})
    engine._assemble("u", "parcel", [episode, *items], 3, "parcel")
    decisions = observer.outputs["evidence packing decisions"]["decisions"]
    reused = decisions[1]["evidence_units"]
    assert len(reused) == 1 and reused[0]["source_ref"] == raw_ref
    assert reused[0]["complete"] and reused[0]["reused_from"] == episode["ref"]
    assert decisions[1]["closure"] == "complete"
    assert decisions[2]["closure"] == "partial"
    assert decisions[2]["evidence_units"][0]["reason"] == "source_unavailable"


def test_reflection_gate_rejects_an_unrelated_explored_ref_for_an_update():
    change = {"basis": "update_existing", "inspected_refs": ["memory:other"],
              "items": [{"ref": "memory:target", "kind": "entity", "text": "Updated description.",
                         "source_refs": ["raw:a"]}]}
    context = {"items": {"memory:target": {}, "memory:other": {}},
               "explored": [["memory:other", "inspect"]]}
    with pytest.raises(MemoryError, match="reflection_orientation_required"):
        Engine._check_reflection_basis(change, context)
    change["inspected_refs"] = ["memory:target"]
    context["explored"].append(["memory:target", "backlinks"])
    with pytest.raises(MemoryError, match="reflection_orientation_required"):
        Engine._check_reflection_basis(change, context)
    node = {"ref": "memory:target", "text": "Original description", "source_refs": ["raw:a"]}
    context["items"][node["ref"]] = node
    context["inspections"] = {node["ref"]: digest(node["text"])}
    context["last_visible"] = [fragment(node, 0, len(node["text"]))]
    Engine._check_reflection_basis(change, context)


def test_reflection_gate_requires_each_existing_relation_endpoint():
    change = {"basis": "add_relation", "inspected_refs": ["memory:left"],
              "links": [{"from_ref": "memory:left", "to_ref": "memory:right",
                         "relation": "contradicts", "source_refs": ["raw:a"]}]}
    context = {"items": {"memory:left": {}, "memory:right": {}},
               "explored": [["memory:left", "inspect"]]}
    with pytest.raises(MemoryError, match="reflection_orientation_required"):
        Engine._check_reflection_basis(change, context)
    change["inspected_refs"].append("memory:right")
    context["explored"].append(["memory:right", "backlinks"])
    with pytest.raises(MemoryError, match="reflection_orientation_required"):
        Engine._check_reflection_basis(change, context)
    context["inspections"], context["last_visible"] = {}, []
    for ref in context["items"]:
        node = {"ref": ref, "text": "A grounded claim", "source_refs": ["raw:a"]}
        context["items"][ref] = node
        context["inspections"][ref] = digest(node["text"])
        context["last_visible"].append(fragment(node, 0, len(node["text"])))
    Engine._check_reflection_basis(change, context)


@pytest.mark.parametrize("bad", [{"items": None}, {"inspected_refs": [{}]}])
def test_reflection_gate_validates_shape_before_set_operations(bad):
    with pytest.raises(MemoryError, match="mutation_schema_invalid"):
        Engine._check_reflection_basis(bad, {"items": {}, "explored": []})
