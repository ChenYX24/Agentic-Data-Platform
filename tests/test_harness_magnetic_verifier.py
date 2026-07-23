from __future__ import annotations

import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import trajectory_for_case
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


class HarnessMagneticVerifierTests(unittest.TestCase):
    def verify_case(self, rel_path: str) -> dict:
        case = load_case_spec(ROOT / rel_path)
        trajectory = trajectory_for_case(case.data)
        return PhysicsVerifier().verify(case.data, trajectory)

    def test_positive_magnetic_force_cases_pass(self) -> None:
        for rel_path in (
            "cases/magnetic/attract_magnetic_body.json",
            "cases/magnetic/repel_magnetic_body.json",
        ):
            report = self.verify_case(rel_path)
            self.assertEqual(report["status"], "pass", rel_path)
            self.assertIsNone(report["failure_type"])
            self.assertTrue(report["evidence"])

    def test_wrong_magnetic_direction_is_rejected(self) -> None:
        report = self.verify_case("cases/magnetic/negative_wrong_magnetic_direction.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "magnetic_radial_direction_m")

    def test_missing_magnetic_label_is_rejected(self) -> None:
        report = self.verify_case("cases/magnetic/negative_missing_magnetic_label.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F3_invalid_initial_physics_state")
        self.assertEqual(report["first_failure"]["metric"], "magnetic_mode")

    def test_mujoco_position_and_terminal_speed_are_validated(self) -> None:
        case = load_case_spec(ROOT / "cases/field_force/magnetic/v001_attract_repel/attract.json").data
        trajectory = [
            {
                "frame": 0,
                "time": 0.0,
                "source": "mujoco_magnetic_force",
                "objects": {
                    "steel_ball": {
                        "position": [0.6, 0.0, 0.14],
                        "velocity_m_s": [0.0, 0.0, 0.0],
                        "source": "mujoco_magnetic_force",
                    }
                },
                "force_fields": [
                    {
                        "source_object_id": "magnet_source",
                        "subject_object_id": "steel_ball",
                        "mode": "attract",
                        "magnetic_force_n": 0.1,
                        "source": "mujoco_magnetic_force",
                    }
                ],
            },
            {
                "frame": 96,
                "time": 4.0,
                "source": "mujoco_magnetic_force",
                "objects": {
                    "steel_ball": {
                        "position": [0.17, 0.0, 0.14],
                        "velocity_m_s": [0.01, 0.0, 0.0],
                        "source": "mujoco_magnetic_force",
                    }
                },
                "force_fields": [
                    {
                        "source_object_id": "magnet_source",
                        "subject_object_id": "steel_ball",
                        "mode": "attract",
                        "magnetic_force_n": 0.0,
                        "source": "mujoco_magnetic_force",
                    }
                ],
            },
        ]
        report = PhysicsVerifier().verify(case, trajectory)
        self.assertEqual(report["status"], "pass", report)

        trajectory[-1]["objects"]["steel_ball"]["velocity_m_s"] = [0.2, 0.0, 0.0]
        failed = PhysicsVerifier().verify(case, trajectory)
        self.assertEqual(failed["first_failure"]["metric"], "magnetic_final_speed_m_s")

        trajectory[-1]["objects"]["steel_ball"]["velocity_m_s"] = [0.01, 0.0, 0.0]
        trajectory[-1]["objects"]["steel_ball"]["source"] = "hand_authored"
        failed = PhysicsVerifier().verify(case, trajectory)
        self.assertEqual(failed["first_failure"]["metric"], "magnetic_trajectory_source")

    def test_required_force_trace_and_finite_strength_fail_closed(self) -> None:
        case = load_case_spec(ROOT / "cases/field_force/magnetic/v001_attract_repel/attract.json").data
        trajectory = [
            {
                "frame": frame,
                "time": float(frame),
                "source": "mujoco_magnetic_force",
                "objects": {
                    "steel_ball": {
                        "position": position,
                        "velocity_m_s": [0.0, 0.0, 0.0],
                        "source": "mujoco_magnetic_force",
                    }
                },
            }
            for frame, position in ((0, [0.6, 0.0, 0.08]), (1, [0.17, 0.0, 0.08]))
        ]

        missing_trace = PhysicsVerifier().verify(case, trajectory)
        self.assertEqual(missing_trace["first_failure"]["metric"], "magnetic_force_trace")

        case["expected_physics"]["magnetic_strength"] = float("nan")
        invalid_strength = PhysicsVerifier().verify(case, trajectory)
        self.assertEqual(invalid_strength["first_failure"]["metric"], "magnetic_strength")


if __name__ == "__main__":
    unittest.main()
