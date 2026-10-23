"""Bounded path groups and two-pass evidence packing; no generation by default."""
from copy import deepcopy

from .evidence import complementary_passages, fragment, ranges_complete, render_fragment, pages
from .text import digest, dumps, terms
from .errors import MemoryError


def freeze_pack(store, user, query, rows, context, config):
    nodes = {row["ref"]: store.get(user, row["ref"]) for row in rows}
    nodes = {ref: node for ref, node in nodes.items() if node}
    roots = context.get("query_roots", list(nodes))
    metadata = {row["ref"]: row for row in rows}
    rank = {ref: index for index, ref in enumerate(roots)}
    branch_terms = [set(terms(entry["branch"])) for row in rows for entry in row.get("lineage", []) if entry.get("branch")]
    paths = context.get("paths", [])
    inspected = set(context.get("inspections", {}))
    groups, assigned = [], set()
    for root in roots:
        if root not in nodes or root in assigned:
            continue
        routes = {root: []}
        for _ in range(config.max_hops):
            for path in paths:
                a, b = path["from_ref"], path["to_ref"]
                if a in routes and b in nodes and b not in routes:
                    routes[b] = routes[a] + [path]
        root_words = set(terms(nodes[root]["text"]))
        gain = {ref: sum(bool(words.intersection(terms(nodes[ref]["text"]))) and not bool(words.intersection(root_words))
                         for words in branch_terms) for ref in routes}
        useful = [ref for ref, route in routes.items() if ref == root or ref in inspected or gain[ref] or any(
            p.get("selected") or any(e["relation"] in {"contradicts", "supersedes"} for e in p["edges"])
            for p in route)]
        useful.sort(key=lambda ref: (ref != root,
            not any(e["relation"] in {"contradicts", "supersedes"} for p in routes[ref] for e in p["edges"]),
            ref not in inspected, -gain[ref], len(routes[ref]), rank.get(ref, len(rank)), ref))
        members, edges = [root], []
        for ref in useful:
            for path in routes[ref]:
                for endpoint in (path["from_ref"], path["to_ref"]):
                    if endpoint not in members:
                        members.append(endpoint)
                for edge in path["edges"]:
                    if edge not in edges:
                        edges.append(edge)
        assigned.update(members)
        group_nodes = [nodes[ref] for ref in members]
        source_refs = list(dict.fromkeys([r for node in group_nodes for r in node["source_refs"]] +
                                        [r for edge in edges for r in edge["source_refs"]]))
        sources = [store.get(user, ref) for ref in source_refs]
        sources = [source for source in sources if source]
        queries = list(dict.fromkeys([query] + [entry["branch"] for row in rows if row["ref"] in members
                                               for entry in row.get("lineage", []) if entry.get("branch")]))
        units = []
        for source in sources:
            if len(source["text"]) <= 1000:
                values = [fragment(source, 0, len(source["text"]))]
            else:
                values, _ = complementary_passages([source], queries, min(config.result_chars, 1000 * max(1, len(queries))), max(1, len(queries)))
                values += pages(source, 800)[:max(1, config.result_chars // 800)]
            # Actual inspected source windows remain available to packing.
            values += [v for v in context.get("disclosures", []) if v["origin_ref"] == source["ref"]
                       and v["content_digest"] == digest(source["text"])]
            units.extend({v["fragment_id"]: v for v in values}.values())
        # Derived node bodies are distinct evidence; never call them source originals.
        bodies = []
        for node in group_nodes:
            if not store.is_minimum_episode(user, node["ref"]):
                values, _ = complementary_passages([node], queries, min(2000, config.result_chars // 3), max(1, len(queries)))
                bodies.extend(values)
        groups.append({"ref": root, "members": members, "nodes": group_nodes,
                       "edges": edges, "source_refs": source_refs,
                       "fragments": bodies + units, "paths": [p for ref in useful for p in routes[ref]]})
    return {"format_version": 1, "packing_unit": "evidence_group", "question": query,
            "groups": groups, "result_chars": config.result_chars, "context_chars": config.context_chars}


def pack_frozen(frozen, top_k):
    groups = deepcopy(frozen["groups"])
    chosen, decisions, used_chars = [], [], 0
    total_limit, card_limit = frozen["context_chars"], frozen["result_chars"]

    def header(group):
        nodes = [f"[{n['kind']}] {n['ref']} [status={n.get('status', 'active')}]" for n in group["nodes"]]
        edges = [f"{e['from_ref']} --{e['relation']}--> {e['to_ref']} [sources={','.join(e['source_refs'])}]"
                 for e in group["edges"]]
        return "\n".join(nodes + edges)

    def render(group, values):
        return header(group) + "\n" + "\n".join(render_fragment(v) for v in values)

    # Pass 1: reserve one complete (when short) support window per origin.
    for group in groups:
        decision = {"ref": group["ref"], "members": group["members"], "included": False,
                    "reason": "top_k", "evidence_units": []}
        decisions.append(decision)
        if len(chosen) >= top_k:
            continue
        by_origin = {}
        for value in group["fragments"]:
            by_origin.setdefault(value["origin_ref"], value)
        base = list(by_origin.values())
        available = min(card_limit, max(0, (total_limit - used_chars) // max(1, min(top_k - len(chosen), len(groups) - len(decisions) + 1))))
        admitted = []
        for value in base:
            if len(render(group, admitted + [value])) <= available:
                admitted.append(value)
        content = render(group, admitted)
        if not admitted or len(content) > available:
            decision["reason"] = "minimum_group_budget"
            continue
        chosen.append((group, admitted, decision))
        used_chars += len(content)
        decision.update(included=True, reason="packed")
    # Pass 2: spend spare space on complementary windows, preserving upstream order.
    for group, admitted, decision in chosen:
        for value in group["fragments"]:
            if any(v["origin_ref"] == value["origin_ref"] and v["content_digest"] == value["content_digest"]
                   and v["start"] <= value["start"] and value["end"] <= v["end"] for v in admitted):
                continue
            old = render(group, admitted)
            new = render(group, admitted + [value])
            if len(new) <= card_limit and used_chars + len(new) - len(old) <= total_limit:
                admitted.append(value)
                used_chars += len(new) - len(old)
    result, prior = [], {}
    # Deduplicate only after final inclusion: reuse can point only to an earlier card.
    for group, admitted, decision in chosen:
        text_parts, kept = [], []
        for value in admitted:
            previous = prior.get(value["fragment_id"])
            if previous:
                shared = f"[shared {value['origin_ref']} {value['start']}:{value['end']} in {previous}]"
                text_parts.append(shared if len(shared) < len(render_fragment(value)) else render_fragment(value))
            else:
                text_parts.append(render_fragment(value))
                kept.append(value)
        content = header(group) + "\n" + "\n".join(text_parts)
        for ref in group["source_refs"]:
            values = [v for v in admitted if v["origin_ref"] == ref]
            all_values = [v for v in group["fragments"] if v["origin_ref"] == ref]
            complete = bool(values) and ranges_complete(values, values[0]["source_chars"])
            reuse = next((prior[v["fragment_id"]] for v in values if v["fragment_id"] in prior), None)
            decision["evidence_units"].append({"source_ref": ref, "included": bool(values), "complete": complete,
                "shown_ranges": [v["shown_range"] for v in values], "reused_from": reuse,
                "reason": "source_unavailable" if not all_values else "full_message" if complete else "source_content_budget"})
        required_relation_sources = {ref for edge in group["edges"] for ref in edge["source_refs"]}
        shown_sources = {u["source_ref"] for u in decision["evidence_units"] if u["included"]}
        shown_nodes = {v["origin_ref"] for v in admitted if v["origin_kind"] == "item"}
        path_closed = required_relation_sources.issubset(shown_sources) and all(
            ref in shown_nodes for edge in group["edges"] for ref in (edge["from_ref"], edge["to_ref"]))
        decision.update(chars=len(content), closure="complete" if decision["evidence_units"] and all(
            v["complete"] for v in decision["evidence_units"]) else "partial",
            fragments=admitted, path_closed=path_closed,
            answer_evidence_complete="unknown")
        result.append({"id": group["ref"], "content": content, "score": round(1 / (len(result) + 1), 8),
                       "created_at": group["nodes"][0].get("created_at")})
        for value in kept:
            prior[value["fragment_id"]] = group["ref"]
    return result, {"format_version": 1, "packing_unit": "evidence_group", "decisions": decisions,
                    "output_chars": sum(len(row["content"]) for row in result)}


def restrict_frozen(frozen, selection):
    """Validate offline LLM choices; never accept generated evidence or an answer."""
    if set(selection) != {"groups"} or not isinstance(selection["groups"], list):
        raise MemoryError("packing_selection_invalid", 502)
    result = {**deepcopy(frozen), "groups": []}
    seen = set()
    for selected in selection["groups"]:
        if set(selected) != {"position", "fragment_positions"}:
            raise MemoryError("packing_selection_invalid", 502)
        pos = selected["position"]
        if type(pos) is not int or not 0 <= pos < len(frozen["groups"]) or pos in seen:
            raise MemoryError("packing_selection_invalid", 502)
        seen.add(pos)
        group = deepcopy(frozen["groups"][pos])
        positions = selected["fragment_positions"]
        if not isinstance(positions, list) or any(type(p) is not int or not 0 <= p < len(group["fragments"]) for p in positions):
            raise MemoryError("packing_selection_invalid", 502)
        group["fragments"] = [group["fragments"][p] for p in dict.fromkeys(positions)]
        result["groups"].append(group)
    return result
