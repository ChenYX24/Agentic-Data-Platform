from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import FallbackBackend
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


class HarnessDominoVerifierTests(unittest.TestCase):
    def test_domino_positive_and_negative(self) -> None:
        self.assertEqual(run_case("cases/domino/five_domino_chain.json")["status"], "pass")
        negative = run_case("cases/domino/negative_simultaneous_motion.json")
        self.assertEqual(negative["status"], "fail")
        self.assertEqual(negative["failure_type"], "F4_causality_violation")


def run_case(rel_path: str) -> dict:
    case = load_case_spec(ROOT / rel_path)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = FallbackBackend().run_case(case, tmp)
        return PhysicsVerifier().verify_run_dir(run_dir)


if __name__ == "__main__":
    unittest.main()
