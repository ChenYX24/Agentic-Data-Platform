from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class ParameterMatrixTests(unittest.TestCase):
    def make_run(
        self,
        root: Path,
        *,
        value: float,
        contact_frame: int,
        physics_hz: int = 120,
        restitution: float = 0.88,
    ) -> Path:
        run_dir = root / f"speed_{str(value).replace('.', 'p')}"
        run_dir.mkdir()
        self.write_json(
            run_dir / "case_spec.json",
            {
                "case_id": f"break_speed_{value}",
                "sweep_metadata": {"parameter": "cue_speed_m_s", "value": value},
                "initial_state": {"active_striker": "cue_ball"},
                "active_objects": ["cue_ball"],
                "physical_parameters": {"cue_speed_m_s": value, "restitution": restitution},
                "scene": {"layout": "triangle_rack", "duration_s": 5.0},
                "objects": [
                    {
                        "id": "cue_ball",
                        "shape": "sphere",
                        "radius_m": 0.09,
                        "initial_position_m": [-1.25, 0.0, 0.09],
                        "initial_velocity_m_s": [value, 0.0, 0.0],
                    },
                    {
                        "id": "target_ball_01",
                        "shape": "sphere",
                        "radius_m": 0.09,
                        "initial_position_m": [0.15, 0.0, 0.09],
                        "initial_velocity_m_s": [0.0, 0.0, 0.0],
                    },
                ],
            },
        )
        self.write_json(
            run_dir / "quality_report.json",
            {
                "status": "pass",
                "hard_gate_passed": True,
                "hard_gate": {"passed": True, "status": "pass", "failure_count": 0},
                "ranking": {"technical_score": 85.0 + value / 100.0},
                "contacts": {
                    "first_positive_contact_frame": contact_frame,
                    "complete_passive_propagation": {
                        "required_passive_count": 15,
                        "positively_contacted_count": 15,
                        "moved_at_least_1cm_count": 15,
                        "missing_contacts": [],
                        "insufficient_motion": [],
                    },
                },
            },
        )
        self.write_json(
            run_dir / "run_readiness.json",
            {
                "backend": "ue",
                "quality_gate_passed": True,
                "verifier_status": "pass",
                "publication_tier": "local_preview",
                "local_preview_ready": True,
                "reference_ready": False,
                "physics_provenance": {
                    "status": "pass",
                    "timebase": {"physics_hz": physics_hz, "render_fps": 24},
                },
            },
        )
        return run_dir

    def test_passes_strictly_decreasing_speed_matrix(self) -> None:
        from harness.verification.parameter_matrix import evaluate_parameter_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [
                (1.8, self.make_run(root, value=1.8, contact_frame=17)),
                (2.8, self.make_run(root, value=2.8, contact_frame=11)),
                (4.2, self.make_run(root, value=4.2, contact_frame=7)),
            ]

            report = evaluate_parameter_matrix(
                parameter="cue_speed_m_s",
                expected="decreasing",
                runs=runs,
            )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["failure_codes"], [])
        self.assertEqual(report["publication_tier"], "local_preview")
        self.assertEqual(report["shared_contract"], {"physics_hz": 120, "render_fps": 24})
        self.assertEqual([row["first_contact_frame"] for row in report["runs"]], [17, 11, 7])
        self.assertTrue(report["directional_check"]["strict_monotonic"])

    def test_rejects_timebase_mismatch(self) -> None:
        from harness.verification.parameter_matrix import evaluate_parameter_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [
                (1.8, self.make_run(root, value=1.8, contact_frame=17)),
                (2.8, self.make_run(root, value=2.8, contact_frame=11, physics_hz=24)),
            ]

            report = evaluate_parameter_matrix("cue_speed_m_s", "decreasing", runs)

        self.assertEqual(report["status"], "fail")
        self.assertIn("F_TIMEBASE_MISMATCH", report["failure_codes"])

    def test_rejects_non_monotonic_contact_time(self) -> None:
        from harness.verification.parameter_matrix import evaluate_parameter_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [
                (1.8, self.make_run(root, value=1.8, contact_frame=17)),
                (2.8, self.make_run(root, value=2.8, contact_frame=9)),
                (4.2, self.make_run(root, value=4.2, contact_frame=12)),
            ]

            report = evaluate_parameter_matrix("cue_speed_m_s", "decreasing", runs)

        self.assertEqual(report["status"], "fail")
        self.assertIn("F_DIRECTIONAL_MONOTONICITY", report["failure_codes"])

    def test_rejects_non_parameter_case_drift(self) -> None:
        from harness.verification.parameter_matrix import evaluate_parameter_matrix

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [
                (1.8, self.make_run(root, value=1.8, contact_frame=17)),
                (2.8, self.make_run(root, value=2.8, contact_frame=11, restitution=0.7)),
            ]

            report = evaluate_parameter_matrix("cue_speed_m_s", "decreasing", runs)

        self.assertEqual(report["status"], "fail")
        self.assertIn("F_CASE_SPEC_DRIFT", report["failure_codes"])

    def test_rejects_unsupported_parameter_contract(self) -> None:
        from harness.verification.parameter_matrix import evaluate_parameter_matrix

        with self.assertRaisesRegex(ValueError, "unsupported parameter"):
            evaluate_parameter_matrix("restitution", "increasing", [])

    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
