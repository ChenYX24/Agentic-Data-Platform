from __future__ import annotations

import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec


ROOT = Path(__file__).resolve().parents[1]


class HarnessCaseSpecSchemaTests(unittest.TestCase):
    def test_all_case_specs_are_schema_valid(self) -> None:
        paths = [
            path
            for path in sorted((ROOT / "cases").glob("*/*.json"))
            if "templates" not in path.parts and "generated" not in path.parts and path.name != "manifest.json"
        ]
        self.assertGreaterEqual(len(paths), 8)
        for path in paths:
            with self.subTest(path=path):
                case = load_case_spec(path)
                self.assertTrue(case.case_id)
                self.assertTrue(case.capability_id)

    def test_case_templates_have_required_controls(self) -> None:
        paths = sorted((ROOT / "cases" / "templates").glob("*.template.json"))
        self.assertGreaterEqual(len(paths), 5)
        for path in paths:
            with self.subTest(path=path):
                import json

                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["schema_version"], "harness_case_template_v1")
                self.assertIn("capability_id", data)
                self.assertIn("parameter_ranges", data)
                self.assertIn("expected_invariants", data)
                self.assertIn("negative_modes", data)


if __name__ == "__main__":
    unittest.main()
