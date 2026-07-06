from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import FallbackBackend
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


class HarnessBounceVerifierTests(unittest.TestCase):
    def test_bounce_positive_and_negative(self) -> None:
        self.assertEqual(run_case("cases/bounce/high_restitution_bounce.json")["status"], "pass")
        self.assertEqual(run_case("cases/bounce/low_restitution_bounce.json")["status"], "pass")
        no_rebound = run_case("cases/bounce/negative_no_rebound.json")
        self.assertEqual(no_rebound["status"], "fail")
        self.assertEqual(no_rebound["failure_type"], "F4_causality_violation")
        energy_gain = run_case("cases/bounce/negative_energy_gain.json")
        self.assertEqual(energy_gain["status"], "fail")
        self.assertEqual(energy_gain["failure_type"], "F4_causality_violation")
        missing_contact = run_case("cases/bounce/negative_missing_contact.json")
        self.assertEqual(missing_contact["status"], "fail")
        self.assertEqual(missing_contact["failure_type"], "F2_missing_contact_events")


def run_case(rel_path: str) -> dict:
    case = load_case_spec(ROOT / rel_path)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = FallbackBackend().run_case(case, tmp)
        return PhysicsVerifier().verify_run_dir(run_dir)


if __name__ == "__main__":
    unittest.main()
