"""Procedural grounding checks; semantic truth still requires evaluation."""
from .evidence import ranges_complete
from .reflection import parse_mutation
from .text import digest
from .projection import range_is_visible


def reusable_items(context, shown):
    """Only full, same-version bodies actually read AND present in this input."""
    result = {}
    for ref, node in context.get('items', {}).items():
        if node.get('kind') == 'episode' or not node.get('text') or node.get('scope_omit_body'):
            continue
        version = node.get('content_digest') or digest(node['text'])
        length = node.get('body_chars', len(node['text']))
        visible = [v for v in shown if v['origin_ref'] == ref and v['content_digest'] == version]
        read = [v for v in context.get('read_ranges', []) if v['origin_ref'] == ref and v['content_digest'] == version]
        read_ok = ranges_complete(read, length) if 'read_ranges' in context else context.get('inspections', {}).get(ref) == version
        if read_ok and ranges_complete(visible, length):
            result[ref] = node
    return result


def missing_material(arguments, context):
    mutation, _ = parse_mutation(arguments)
    items = context.get("items", {})
    inspected = context.get("inspections", {})
    shown = context.get("last_visible", [])
    known = set(items) | set(context.get("references", {}))
    targets = {item.ref for item in mutation.items if item.ref in known}
    targets.update(ref for edge in mutation.links for ref in (edge.from_ref, edge.to_ref) if ref in known)
    targets.update(ref for forget in mutation.forget for ref in forget.memory_refs)
    missing = []
    for ref in sorted(targets):
        node = items.get(ref)
        version = node.get("content_digest") or digest(node["text"]) if node and "text" in node else None
        body = [v for v in shown if v["origin_ref"] == ref and v["content_digest"] == version]
        read = [v for v in context.get("read_ranges", []) if v["origin_ref"] == ref and v["content_digest"] == version]
        length = node.get("body_chars", len(node["text"])) if node else 0
        read_ok = ranges_complete(read, length) if "read_ranges" in context else inspected.get(ref) == version
        # This group's newly reviewed/committed body can be read directly in
        # the next actual tool input. It is not an old target requiring recall.
        # A checkpoint alone never grants visibility: the full matching body
        # must still be present in last_visible after that call returned.
        if ref in context.get('committed_node_refs', []) and ranges_complete(body, length):
            read_ok = True
        if not version or not read_ok or not ranges_complete(body, length):
            missing.append({"ref": ref, "need": "same_version_inspect_full_body_in_final_call"})
    for item in mutation.items:
        if item.kind != "person" or item.ref in known:
            continue
        if context.get("old_scope", {}).get("empty") is True:
            continue  # Database scope receipt; not a fabricated query receipt.
        query = context.get("identity_queries", {}).get(item.ref)
        if not query:
            missing.append({"ref": item.ref, "need": "targeted_old_identity_query"})
        elif not query["refs"]:
            if not mutation.no_prior_match:
                missing.append({"ref": item.ref, "need": "declare_no_prior_match"})
        elif not any(ref in inspected and any(v.get("item_ref") == ref and
                    ("read_ranges" not in context or range_is_visible(v, context["read_ranges"]))
                    for v in shown) for ref in query["refs"]):
            missing.append({"ref": item.ref, "need": "inspect_targeted_identity_candidate"})
    visible_sources = set(context.get("visible_source_refs", []))
    if "visible_source_refs" in context:
        for change in [*mutation.items, *mutation.links]:
            inherited = set(items.get(getattr(change, "ref", None), {}).get("source_refs", []))
            for ref in set(change.source_refs) - inherited - visible_sources:
                missing.append({"ref": ref, "need": "newly_cited_source_visible"})
        # Both sides of an explicit conflict/update must have visible provenance.
        for link in mutation.links:
            if link.relation not in {"contradicts", "supersedes"}:
                continue
            new = {item.ref: item for item in mutation.items}
            for ref in (link.from_ref, link.to_ref):
                sources = new[ref].source_refs if ref in new else items.get(ref, {}).get("source_refs", [])
                if not set(sources).intersection(visible_sources):
                    missing.append({"ref": ref, "need": "conflict_side_visible_provenance"})
    return missing
