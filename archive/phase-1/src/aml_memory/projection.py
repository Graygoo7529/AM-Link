from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

from .repository import EventRecord, NodeRecord, utc_now


def user_scope_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]


class MarkdownProjector:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def project(
        self,
        *,
        user_id: str,
        working_memory: str,
        events: tuple[EventRecord, ...],
        nodes: tuple[NodeRecord, ...] = (),
    ) -> None:
        if self.root is None:
            return
        with self._lock:
            scope = user_scope_hash(user_id)
            user_root = self.root / scope
            user_root.mkdir(parents=True, exist_ok=True)
            rendered = (
                "---\n"
                f"user_scope: {scope}\n"
                f"generated_at: {utc_now()}\n"
                "view: working-memory\n"
                "---\n\n"
                f"{working_memory}"
            )
            self._atomic_write(user_root / "Memory.md", rendered)
            for event in events:
                self._append_daily(user_root, event)
            for node in nodes:
                self._write_node(user_root, node)

    def _append_daily(self, user_root: Path, event: EventRecord) -> None:
        date_label = (event.source_time or "undated")[:10]
        daily_dir = user_root / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        path = daily_dir / f"{date_label}.md"
        marker = f"<!-- memory-id:{event.memory_id} -->"
        if path.exists() and marker in path.read_text(encoding="utf-8"):
            return
        source_time = event.source_time or "unknown"
        block = (
            f"\n{marker}\n"
            f"## {source_time} · {event.role}\n\n"
            f"{event.content}\n\n"
            f"- session: `{event.session_id}`\n"
            f"- request: `{event.request_id}`\n"
        )
        if path.exists():
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(block)
            return
        header = (
            "---\n"
            f"memory: memory:daily@{date_label}\n"
            f"created_at: {utc_now()}\n"
            "append_only: true\n"
            "---\n"
        )
        self._atomic_write(path, header + block)

    def _write_node(self, user_root: Path, node: NodeRecord) -> None:
        if node.kind not in {"entity", "concept", "fact"}:
            return
        path = user_root / node.kind / f"{node.memory_id}.md"
        sources = json.loads(node.source_event_ids)
        source_lines = "\n".join(f"  - {source}" for source in sources) or "  - none"
        rendered = (
            "---\n"
            f"memory_id: {node.memory_id}\n"
            f"kind: {node.kind}\n"
            f"status: {node.status}\n"
            f"version: {node.version}\n"
            f"event_time: {node.event_time or 'unknown'}\n"
            f"time_expression: {node.time_expression or 'unknown'}\n"
            f"resolved_time_start: {node.resolved_time_start or 'unknown'}\n"
            f"resolved_time_end: {node.resolved_time_end or 'unknown'}\n"
            f"time_precision: {node.time_precision or 'unknown'}\n"
            f"valid_from: {node.valid_from or 'unknown'}\n"
            f"valid_to: {node.valid_to or 'open'}\n"
            f"updated_at: {node.updated_at}\n"
            "source_event_ids:\n"
            f"{source_lines}\n"
            "---\n\n"
            f"# {node.title}\n\n"
            f"{node.content}\n"
        )
        self._atomic_write(path, rendered)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
