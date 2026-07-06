from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PATHS = [
    "README.md",
    "docs/HARNESS_ARCHITECTURE.md",
    "docs/AGENT_USAGE.md",
    "docs/CASE_SPEC_SCHEMA.md",
    "docs/ARTIFACT_SCHEMA.md",
    "docs/CAPABILITY_AUTHORING.md",
    "docs/OPTIONAL_VIEWER.md",
    "docs/LEGACY_NOTES.md",
    "docs/PHYSICS_CASE_TARGETS.md",
    "config/harness_capability_profile.json",
]


class HarnessPublishScanTests(unittest.TestCase):
    def test_public_docs_do_not_contain_secret_patterns(self) -> None:
        forbidden = [
            "s" + "k-",
            "m" + "s-",
            "gh" + "p_",
            "gh" + "o_",
            "gh" + "u_",
            "gh" + "s_",
            "gh" + "r_",
            "/Users/" + "cyx/" + "Downloads",
            "agent" + "会话",
        ]
        for rel_path in PUBLIC_PATHS:
            text = (ROOT / rel_path).read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(path=rel_path, token=token):
                    self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
