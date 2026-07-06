from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import FallbackBackend
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


class HarnessBilliardsVerifierTests(unittest.TestCase):
    def test_low_speed_single_contact_passes(self) -> None:
        report = run_case("cases/billiards/low_speed_single_contact.json")
        self.assertEqual(report["status"], "pass")

    def test_negative_precontact_motion_fails(self) -> None:
        report = run_case("cases/billiards/negative_precontact_motion.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F5_passive_precontact_motion")
        self.assertEqual(report["first_failure"]["object_id"], "target_ball_1")


def run_case(rel_path: str) -> dict:
    case = load_case_spec(ROOT / rel_path)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = FallbackBackend().run_case(case, tmp)
        return PhysicsVerifier().verify_run_dir(run_dir)


if __name__ == "__main__":
    unittest.main()
