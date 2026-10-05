from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataset import fetch


class FetchTests(unittest.TestCase):
    def test_github_api_rejects_corrupt_blob_content(self) -> None:
        data = b'{"value":1}'
        correct_hash = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        payload = {"encoding": "base64", "content": base64.b64encode(data + b' ').decode(), "sha": correct_hash}
        with patch.object(fetch.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaisesRegex(ValueError, "blob hash mismatch"):
                fetch._github_asset("https://raw.githubusercontent.com/owner/repo/revision/data.json")

    def test_sample_rejects_truncated_history_without_creating_a_pack(self) -> None:
        payload = {"rows": [{"row_idx": 0, "row": {"chat": "incomplete"}, "truncated_cells": ["chat"]}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(fetch, "ROOT", root), patch.object(
                fetch.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())
            ):
                with self.assertRaisesRegex(ValueError, "truncated"):
                    fetch.fetch_sample("beam", offset=0, limit=1)
            self.assertEqual(list(root.iterdir()), [])

    def test_full_json_validation_rejects_a_truncated_array(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json.partial"
            path.write_text('[{"valid":1},', encoding="utf-8")
            with self.assertRaises(ValueError):
                fetch._validate_format(path, "json-array")


if __name__ == "__main__":
    unittest.main()
