from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import FallbackBackend
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


class HarnessProjectileVerifierTests(unittest.TestCase):
    def test_projectile_positive_and_negative(self) -> None:
        self.assertEqual(run_case("cases/projectile/upward_throw_arc.json")["status"], "pass")
        self.assertEqual(run_case("cases/projectile/low_angle_forward_throw.json")["status"], "pass")
        no_gravity = run_case("cases/projectile/negative_no_gravity_float.json")
        self.assertEqual(no_gravity["status"], "fail")
        self.assertEqual(no_gravity["failure_type"], "F4_causality_violation")
        missing_contact = run_case("cases/projectile/negative_missing_landing_contact.json")
        self.assertEqual(missing_contact["status"], "fail")
        self.assertEqual(missing_contact["failure_type"], "F2_missing_contact_events")


def run_case(rel_path: str) -> dict:
    case = load_case_spec(ROOT / rel_path)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = FallbackBackend().run_case(case, tmp)
        return PhysicsVerifier().verify_run_dir(run_dir)


if __name__ == "__main__":
    unittest.main()
