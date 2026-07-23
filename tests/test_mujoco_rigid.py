from __future__ import annotations

import importlib.util
import json
import copy
import unittest
from pathlib import Path

from harness.assets.asset_resolver import resolve_asset_intents
from harness.planning.static_scene_builder import build_static_scene_layout
from harness.runtime.actor_placement import compile_runtime_actor_placement
from harness.runtime.mujoco_rigid import simulate_rigid_case
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "MuJoCo is an optional simulation dependency")
class MuJoCoRigidTests(unittest.TestCase):
    def test_falling_and_ball_contact_cases_pass_the_existing_verifiers(self) -> None:
        for relative_path in (
            "cases/falling/falling_block_on_floor.json",
            "cases/billiards/low_speed_single_contact.json",
        ):
            case = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
            assets = resolve_asset_intents(case)
            layout = build_static_scene_layout(case, asset_resolution=assets)
            placement = compile_runtime_actor_placement(case, layout, asset_resolution=assets)

            trajectory = simulate_rigid_case(case, placement, fps=24, duration_s=4.0)
            report = PhysicsVerifier().verify(case, trajectory or [])

            self.assertEqual(report["status"], "pass", report)
            self.assertTrue(all(state.get("source") == "mujoco_rigid" for frame in trajectory or [] for state in frame["objects"].values()))
            self.assertEqual((trajectory or [])[0]["solver_state"]["backend"], "mujoco_rigid")
            self.assertAlmostEqual((trajectory or [])[0]["solver_state"]["objects"][next(iter((trajectory or [])[0]["objects"]))]["mass_kg"], 1.0 if "falling" in relative_path else 0.17)

    def test_gravity_damping_angular_velocity_and_inertia_are_echoed(self) -> None:
        case = copy.deepcopy(json.loads((ROOT / "cases/billiards/low_speed_single_contact.json").read_text(encoding="utf-8")))
        case["physical_parameters"] = {"gravity_m_s2": [0.0, 0.0, 0.0]}
        cue = next(obj for obj in case["objects"] if obj["id"] == "cue_ball")
        cue.update(
            {
                "initial_angular_velocity_rad_s": [1.0, 2.0, 3.0],
                "linear_damping": 0.2,
                "angular_damping": 0.3,
            }
        )
        assets = resolve_asset_intents(case)
        layout = build_static_scene_layout(case, asset_resolution=assets)
        placement = compile_runtime_actor_placement(case, layout, asset_resolution=assets)

        trajectory = simulate_rigid_case(case, placement, fps=24, duration_s=0.1) or []
        solver = trajectory[0]["solver_state"]

        self.assertEqual(solver["gravity_m_s2"], [0.0, 0.0, 0.0])
        self.assertEqual(solver["objects"]["cue_ball"]["linear_damping"], [0.2, 0.2, 0.2])
        self.assertEqual(solver["objects"]["cue_ball"]["angular_damping"], [0.3, 0.3, 0.3])
        self.assertTrue(all(value > 0.0 for value in solver["objects"]["cue_ball"]["inertia_diagonal_kg_m2"]))
        self.assertEqual(trajectory[0]["objects"]["cue_ball"]["angular_velocity_rad_s"], [1.0, 2.0, 3.0])

    def test_elastic_tendon_generates_bounded_constraint_trace_and_rebound(self) -> None:
        case = json.loads((ROOT / "cases/elastic_constraint/bungee_rebound.json").read_text(encoding="utf-8"))
        assets = resolve_asset_intents(case)
        layout = build_static_scene_layout(case, asset_resolution=assets)
        placement = compile_runtime_actor_placement(case, layout, asset_resolution=assets)

        trajectory = simulate_rigid_case(case, placement, fps=24, duration_s=5.0) or []
        report = PhysicsVerifier().verify(case, trajectory)

        self.assertEqual(report["status"], "pass", report)
        self.assertTrue(all(frame.get("source") == "mujoco_rigid" for frame in trajectory))
        self.assertTrue(all(frame.get("constraints") for frame in trajectory))
        extensions = [float(frame["constraints"][0]["extension_m"]) for frame in trajectory]
        self.assertGreaterEqual(max(extensions), case["expected_physics"]["expected_min_extension_m"])
        self.assertLessEqual(max(extensions), case["expected_physics"]["max_extension_m"])
        self.assertEqual(trajectory[0]["solver_state"]["model"], "spatial_tendon_spring_damper")
        evidence = report["evidence"][0]
        self.assertGreater(evidence["first_peak_to_peak_amplitude_m"], 0.2)
        self.assertGreater(evidence["observed_oscillation_period_s"], 0.8)
        self.assertGreater(evidence["settling_time_s"], 2.0)

    def test_elastic_height_mass_and_rest_length_change_solver_response(self) -> None:
        base = json.loads((ROOT / "cases/elastic_constraint/bungee_rebound.json").read_text(encoding="utf-8"))

        def max_extension(*, height: float = 1.0, mass: float = 0.8, rest_length: float = 1.2) -> float:
            case = copy.deepcopy(base)
            payload = next(obj for obj in case["objects"] if obj["id"] == "payload")
            payload["initial_position_m"][2] = height
            payload["mass_kg"] = mass
            case["expected_physics"]["rest_length_m"] = rest_length
            trajectory = simulate_rigid_case(case, {}, fps=24, duration_s=5.0) or []
            return max(float(frame["constraints"][0]["extension_m"]) for frame in trajectory)

        self.assertGreater(max_extension(height=1.2), max_extension(height=0.8))
        self.assertGreater(max_extension(mass=0.95), max_extension(mass=0.65))
        self.assertGreater(max_extension(rest_length=1.4), max_extension(rest_length=1.0))

    def test_magnetic_force_solver_attracts_and_repels(self) -> None:
        for name, mode in (("attract", "attract"), ("repel", "repel")):
            case = json.loads(
                (ROOT / f"cases/field_force/magnetic/v001_attract_repel/{name}.json").read_text(encoding="utf-8")
            )
            trajectory = simulate_rigid_case(case, {}, fps=24, duration_s=4.0) or []
            report = PhysicsVerifier().verify(case, trajectory)

            self.assertEqual(report["status"], "pass", report)
            self.assertTrue(all(frame.get("force_fields") for frame in trajectory))
            self.assertEqual(trajectory[0]["solver_state"]["model"], "finite_range_softened_inverse_square")
            self.assertEqual(trajectory[0]["force_fields"][0]["mode"], mode)

    def test_magnetic_force_solver_rejects_nonfinite_inputs(self) -> None:
        case = json.loads(
            (ROOT / "cases/field_force/magnetic/v001_attract_repel/attract.json").read_text(encoding="utf-8")
        )
        case["expected_physics"]["magnetic_strength"] = float("nan")
        with self.assertRaisesRegex(ValueError, "must be finite"):
            simulate_rigid_case(case, {}, fps=24, duration_s=4.0)

        case["expected_physics"]["magnetic_strength"] = -0.08
        with self.assertRaisesRegex(ValueError, "must be positive"):
            simulate_rigid_case(case, {}, fps=24, duration_s=4.0)

    def test_newton_cradle_release_angle_drives_ordered_terminal_response(self) -> None:
        peaks = []
        for name in ("release_25deg", "release_35deg", "release_45deg"):
            case = json.loads(
                (ROOT / f"cases/rigid_collision/newton_cradle/v001_release_angle_ofat/{name}.json").read_text(encoding="utf-8")
            )
            trajectory = simulate_rigid_case(case, {}, fps=24, duration_s=5.0) or []
            report = PhysicsVerifier().verify(case, trajectory)

            self.assertEqual(report["status"], "pass", report)
            self.assertTrue(all(frame.get("constraints") for frame in trajectory))
            self.assertEqual(trajectory[0]["solver_state"]["model"], "hinged_sphere_impulse_chain")
            peaks.append(report["evidence"][0]["receiver_post_chain_speed_m_s"])
        self.assertEqual(peaks, sorted(peaks))
        self.assertEqual(len(set(peaks)), 3)

        forged_state = copy.deepcopy(trajectory)
        forged_state[-1]["objects"]["ball_4"]["source"] = "hand_authored"
        failed = PhysicsVerifier().verify(case, forged_state)
        self.assertEqual(failed["first_failure"]["metric"], "impulse_chain_trajectory_source")

        forged_contact = copy.deepcopy(trajectory)
        next(contact for frame in forged_contact for contact in frame.get("contacts") or [])["source"] = "hand_authored"
        failed = PhysicsVerifier().verify(case, forged_contact)
        self.assertEqual(failed["first_failure"]["metric"], "impulse_chain_contact_source")

        mismatched_initial_state = copy.deepcopy(trajectory)
        mismatched_initial_state[0]["objects"]["ball_0"]["position"][0] += 0.01
        failed = PhysicsVerifier().verify(case, mismatched_initial_state)
        self.assertEqual(failed["first_failure"]["metric"], "initial_position_matches_case_spec")

    def test_ramp_friction_matrix_separates_sliding_mixed_and_rolling(self) -> None:
        slips = []
        for name in ("low_friction_slide", "medium_friction_partial_roll", "high_friction_roll"):
            case = json.loads(
                (ROOT / f"cases/rigid_motion/ramp_roll_slide/v001_friction_regime_ofat/{name}.json").read_text(encoding="utf-8")
            )
            duration_s = case["scene"]["duration_s"] + case["scene"]["post_event_tail_s"]
            trajectory = simulate_rigid_case(case, {}, fps=24, duration_s=duration_s) or []
            report = PhysicsVerifier().verify(case, trajectory)

            self.assertEqual(report["status"], "pass", report)
            self.assertEqual(trajectory[0]["solver_state"]["model"], "inclined_plane_roll_slide_with_runout")
            slips.append(report["evidence"][0]["median_slip_ratio"])
        self.assertGreater(slips[0], slips[1])
        self.assertGreater(slips[1], slips[2])


if __name__ == "__main__":
    unittest.main()
