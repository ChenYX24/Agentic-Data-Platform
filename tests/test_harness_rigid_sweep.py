from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "MuJoCo is an optional simulation dependency")
class HarnessRigidSweepTests(unittest.TestCase):
    def test_core_sweeps_have_expected_direction_and_solver_echo(self) -> None:
        from scripts.harness_sweep_rigid import run_sweeps

        case = json.loads((ROOT / "cases/billiards/low_speed_single_contact.json").read_text(encoding="utf-8"))
        report = run_sweeps(case, fps=24, duration_s=4.0)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(set(report["sweeps"]), {"speed_m_s", "mass_ratio", "restitution_control", "friction", "incidence_angle_deg"})
        self.assertTrue(all(sweep["directional_pass"] for sweep in report["sweeps"].values()))
        self.assertTrue(all(row["solver_parameter_echo"]["backend"] == "mujoco_rigid" for sweep in report["sweeps"].values() for row in sweep["rows"]))
        self.assertIn("incidence_angle_deg__negative_high", report["representative_cases"])

        speed_only = run_sweeps(case, fps=24, duration_s=4.0, parameters={"speed_m_s"})
        self.assertEqual(set(speed_only["sweeps"]), {"speed_m_s"})


class HarnessReferenceBilliardsSweepTests(unittest.TestCase):
    def test_reference_case_mutators_use_declared_object_ids(self) -> None:
        from scripts.harness_sweep_rigid import mutate_incidence_angle, mutate_mass_ratio, mutate_speed

        case = json.loads((ROOT / "cases/billiards/sixteen_ball_reference_break.json").read_text(encoding="utf-8"))
        mutate_mass_ratio(case, 2.0)
        mutate_incidence_angle(case, 12.0)
        mutate_speed(case, 4.2)

        objects = {obj["id"]: obj for obj in case["objects"]}
        self.assertEqual(objects["target_ball_01"]["mass_kg"], 0.34)
        self.assertLess(objects["cue_ball"]["initial_position_m"][1], 0.0)
        self.assertAlmostEqual(sum(value * value for value in objects["cue_ball"]["initial_velocity_m_s"]) ** 0.5, 4.2)


if __name__ == "__main__":
    unittest.main()
