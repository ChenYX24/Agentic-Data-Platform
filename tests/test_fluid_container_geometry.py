from __future__ import annotations

import copy
import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec, validate_case_spec
from harness.runtime.fluid_container_geometry import (
    add,
    compile_container_transfer,
    matrix_vector,
    point_inside_profile,
    rotation_matrix_xyz,
)
from harness.runtime.genesis_sph_backend import genesis_command, genesis_parameters
from scripts.harness_genesis_container_transfer import container_pose_at_time, set_container_pose


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/fluid/container_to_container_transfer/v002_wine_glass_to_teacup.json"


class FluidContainerGeometryTests(unittest.TestCase):
    def test_real_asset_pair_compiles_to_one_shared_solver_render_binding(self) -> None:
        case = load_case_spec(CASE)
        compiled = compile_container_transfer(case.data)

        self.assertEqual(compiled["solver_mode"], "container_transfer")
        self.assertEqual(case.data["passive_objects"], ["source_wine_glass", "receiver_teacup"])
        self.assertEqual(compiled["source"]["asset"]["ue_path"], "/Game/Props/Dining/SM_Glass04.SM_Glass04")
        self.assertEqual(compiled["receiver"]["asset"]["ue_path"], "/Game/Props/Dining/SM_TeaCup.SM_TeaCup")
        self.assertFalse(compiled["source"]["asset"]["proxy"])
        self.assertTrue(compiled["source"]["collision"]["asset_geometry_match"])
        self.assertEqual(len(compiled["source"]["collision"]["parts"]), 73)
        self.assertEqual(len(compiled["receiver"]["collision"]["parts"]), 49)
        self.assertAlmostEqual(compiled["fluid"]["world_position_m"][0], -0.25)
        self.assertAlmostEqual(compiled["fluid"]["world_position_m"][2], 0.1825)
        self.assertEqual(len(compiled["source"]["collision"]["inner_profile"]), 4)
        self.assertEqual(compiled["source"]["kinematic_motion"]["solver_end_rotation_xyz_deg"], [0.0, 98.0, 0.0])
        self.assertEqual(compiled["source"]["kinematic_motion"]["ue_end_rotation_pyr_deg"], [-98.0, 0.0, 0.0])
        self.assertEqual(compiled["source"]["kinematic_motion"]["pivot_local_m"], [0.052, 0.0, 0.225])
        self.assertEqual(compiled["source"]["kinematic_motion"]["pivot_world_m"], [-0.198, 0.0, 0.225])
        self.assertEqual(compiled["pour_alignment"]["method"], "solver_probe_stream_landing_v3")
        self.assertTrue(compiled["pour_alignment"]["pass"])
        self.assertEqual(compiled["pour_alignment"]["xy_distance_m"], 0.0)

    def test_backend_selects_container_transfer_solver_without_large_cli_payload(self) -> None:
        case = load_case_spec(CASE)
        parameters = genesis_parameters(case.data)
        command = genesis_command(Path("/isolated/python"), Path("/runs/transfer"), case.data["backend_options"], parameters)

        self.assertIn("harness_genesis_container_transfer.py", command[1])
        self.assertEqual(command[command.index("--case") + 1], "/runs/transfer/case_spec.json")
        self.assertEqual(command[-1], "--skip-publish")

    def test_convex_or_unbound_container_is_rejected_before_solver(self) -> None:
        case = copy.deepcopy(load_case_spec(CASE).data)
        source = next(item for item in case["objects"] if item["role"] == "source_container")
        source["asset"]["proxy"] = True
        source["collision"]["type"] = "convex_hull"

        with self.assertRaisesRegex(ValueError, "non-proxy"):
            validate_case_spec(case)

    def test_profile_membership_uses_container_transform(self) -> None:
        compiled = compile_container_transfer(load_case_spec(CASE).data)

        self.assertTrue(point_inside_profile(compiled["fluid"]["world_position_m"], compiled["source"]))
        self.assertFalse(point_inside_profile(compiled["fluid"]["world_position_m"], compiled["receiver"]))

    def test_drop_line_that_misses_receiver_is_rejected_before_solver(self) -> None:
        case = copy.deepcopy(load_case_spec(CASE).data)
        receiver = next(item for item in case["objects"] if item["role"] == "receiver_container")
        receiver["initial_position_m"][0] = 0.0

        with self.assertRaisesRegex(ValueError, "drop line misses receiver"):
            compile_container_transfer(case)

    def test_asset_bound_transfer_requires_real_support_surface(self) -> None:
        case = copy.deepcopy(load_case_spec(CASE).data)
        case["scene"]["support_surface"]["asset"]["proxy"] = True

        with self.assertRaisesRegex(ValueError, "non-proxy /Game support surface"):
            validate_case_spec(case)

    def test_solver_tilt_uses_opposite_ue_pitch_sign(self) -> None:
        case = copy.deepcopy(load_case_spec(CASE).data)
        source = next(item for item in case["objects"] if item["role"] == "source_container")
        source["kinematic_motion"]["ue_end_rotation_pyr_deg"] = [98.0, 0.0, 0.0]

        with self.assertRaisesRegex(ValueError, "negative UE pitch"):
            validate_case_spec(case)

    def test_moving_container_reports_boundary_velocity_to_solver(self) -> None:
        compiled = compile_container_transfer(load_case_spec(CASE).data)

        class Entity:
            velocity = None

            def set_pos(self, *_args, **_kwargs) -> None:
                pass

            def set_quat(self, *_args, **_kwargs) -> None:
                pass

            def set_dofs_velocity(self, velocity, **_kwargs) -> None:
                self.velocity = velocity

        entity = Entity()
        set_container_pose(entity, compiled["source"], 0.3, next_time_s=0.31)

        self.assertIsNotNone(entity.velocity)
        self.assertGreater(max(abs(value) for value in entity.velocity[:3]), 0.0)
        self.assertGreater(max(abs(value) for value in entity.velocity[3:]), 0.0)

    def test_moving_container_keeps_declared_rim_pivot_fixed(self) -> None:
        source = compile_container_transfer(load_case_spec(CASE).data)["source"]

        position, rotation, _ue_rotation = container_pose_at_time(source, 1.0)
        pivot_world = add(position, matrix_vector(rotation_matrix_xyz(rotation), source["kinematic_motion"]["pivot_local_m"]))

        for actual, expected in zip(pivot_world, source["kinematic_motion"]["pivot_world_m"], strict=True):
            self.assertAlmostEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
