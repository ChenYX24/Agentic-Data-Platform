from __future__ import annotations

import unittest

from harness.runtime.camera_planner import SceneBounds, camera_plan_from_case_spec, plan_cameras_for_scene


class CameraPlannerTests(unittest.TestCase):
    def test_default_bounds_generate_canonical_five_views(self) -> None:
        plan = plan_cameras_for_scene(SceneBounds(center=(0.0, 0.0, 0.5), extent=(2.0, 2.0, 1.0)))
        self.assertEqual([view.camera_id for view in plan.views], ["front_static", "side_static", "top_down", "tracking_subject", "event_closeup"])
        self.assertEqual({view.role for view in plan.views}, {"front_static", "side_static", "top_down", "tracking_subject", "event_closeup"})

    def test_tiny_bounds_do_not_crash(self) -> None:
        plan = plan_cameras_for_scene(SceneBounds(center=(0.0, 0.0, 0.0), extent=(0.0, 0.0, 0.0)))
        self.assertEqual(len(plan.views), 5)
        self.assertTrue(plan.warnings)

    def test_planner_is_deterministic(self) -> None:
        bounds = SceneBounds(center=(1.0, 2.0, 3.0), extent=(4.0, 5.0, 6.0))
        first = plan_cameras_for_scene(bounds)
        second = plan_cameras_for_scene(bounds)
        self.assertEqual(first, second)

    def test_camera_ids_are_unique(self) -> None:
        plan = plan_cameras_for_scene(SceneBounds(center=(0.0, 0.0, 0.0), extent=(1.0, 1.0, 1.0)), requested_views=["top", "top", "side"])
        ids = [view.camera_id for view in plan.views]
        self.assertEqual(ids, ["top", "side"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_case_spec_bounds_parser_is_tolerant(self) -> None:
        case_spec = {
            "objects": [
                {"id": "a", "initial_position_m": [-1, 0, 0]},
                {"id": "b", "location": [3, 2, 1]},
            ]
        }
        plan = camera_plan_from_case_spec(case_spec, requested_views=["overview", "front", "side", "top"])
        self.assertEqual(len(plan.views), 4)
        self.assertEqual(plan.scene_bounds.center, (1.0, 1.0, 0.5))


if __name__ == "__main__":
    unittest.main()
