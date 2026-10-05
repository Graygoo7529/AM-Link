from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from casestudies.build import load_catalog, render_fragment


class BuildTests(unittest.TestCase):
    def test_case_text_cannot_close_script_and_is_preserved(self):
        content = {"question": "</script><script>alert(1)</script>\u2028原文"}
        rendered = render_fragment(content, "<script>const catalog=__AML_CATALOG_JSON__;</script>")
        self.assertEqual(rendered.count("</script>"), 1)
        payload = rendered.removeprefix("<script>const catalog=").removesuffix(";</script>")
        self.assertEqual(json.loads(payload), content)

    def test_unknown_case_rejects_stale_catalog(self):
        catalog = copy.deepcopy(load_catalog())
        catalog["datasets"]["beam"]["cases"].append("missing-case")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown case"):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
