from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.datasets import build_retrieval_manifest
from dataset.perltqa import build_perltqa


class PerltqaTests(unittest.TestCase):
    def test_paired_sources_keep_labels_out_of_add_and_reject_dangling_references(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mem.json"
            qa = Path(directory) / "qa.json"
            path.write_text(json.dumps([{"profile": {"Protagonist": "甲", "Age": 28},
                "events": {"e1": {"content": "甲参加了摄影展", "Creation Time": "某年"}},
                "dialogues": {}, "social_relationship": {}}]), encoding="utf-8")
            qa.write_text(json.dumps([{"甲": {"events": {"e1": [
                {"Question": "参加了什么？", "Answer": "GOLD_ONLY", "Reference Memory": "['e1']",
                    "Memory Anchors": [{"SECRET_ANCHOR": [-1, -1]}]},
                {"Question": "不存在的事件？", "Answer": "BAD", "Reference Memory": "['missing']"}
            ]}}}]), encoding="utf-8")
            pack = build_perltqa(path=path, qa_path=qa)
            plan = build_retrieval_manifest(pack, chunk_size=20, top_k=5)
            adds = json.dumps([c["adds"] for c in plan["cases"]], ensure_ascii=False)
            self.assertNotIn("GOLD_ONLY", adds)
            self.assertNotIn("SECRET_ANCHOR", adds)
            self.assertIn("某年", adds)
            self.assertEqual(len(plan["cases"][0]["searches"]), 1)
            self.assertEqual(pack["preparation"]["excluded_tasks"][0]["missing_turn_ids"], ["events:missing"])
            self.assertIn("qa", pack["preparation"]["inputs"])
            self.assertFalse(pack["records"][0]["tasks"][0]["annotations"]["anchor_offsets_verified"])

    def test_changed_paired_qa_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mem.json"
            qa = Path(directory) / "qa.json"
            path.write_text("[]", encoding="utf-8")
            qa.write_text("[]", encoding="utf-8")
            qa.with_suffix(".json.receipt.json").write_text('{"sha256":"wrong"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt"):
                build_perltqa(path=path, qa_path=qa)


if __name__ == "__main__":
    unittest.main()
