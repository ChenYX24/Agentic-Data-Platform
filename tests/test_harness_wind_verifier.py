from __future__ import annotations

import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import trajectory_for_case
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


class HarnessWindVerifierTests(unittest.TestCase):
    def verify_case(self, rel_path: str) -> dict:
        case = load_case_spec(ROOT / rel_path)
        trajectory = trajectory_for_case(case.data)
        return PhysicsVerifier().verify(case.data, trajectory)

    def test_positive_wind_drift_cases_pass(self) -> None:
        for rel_path in (
            "cases/wind/east_wind_balloon_drift.json",
            "cases/wind/northeast_wind_light_body_drift.json",
        ):
            report = self.verify_case(rel_path)
            self.assertEqual(report["status"], "pass", rel_path)
            self.assertIsNone(report["failure_type"])
            self.assertTrue(report["evidence"])

    def test_no_wind_drift_is_rejected(self) -> None:
        report = self.verify_case("cases/wind/negative_no_wind_drift.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "wind_aligned_drift_too_small_m")

    def test_wrong_direction_is_rejected(self) -> None:
        report = self.verify_case("cases/wind/negative_wrong_direction.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "wind_direction_alignment_m")

    def test_missing_wind_label_is_rejected(self) -> None:
        report = self.verify_case("cases/wind/negative_missing_wind_label.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F3_invalid_initial_physics_state")
        self.assertEqual(report["first_failure"]["metric"], "wind_vector_horizontal_m_s")


if __name__ == "__main__":
    unittest.main()
