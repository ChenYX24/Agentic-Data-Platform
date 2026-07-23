from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StaticScenePlacementTests(unittest.TestCase):
    def load_case(self, relative_path: str) -> dict:
        return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))

    def test_billiards_case_builds_valid_static_scene_layout(self) -> None:
        from harness.assets.asset_resolver import resolve_asset_intents
        from harness.planning.static_scene_builder import build_static_scene_layout
        from harness.verification.static_scene_verifier import verify_static_scene_layout

        case = self.load_case("cases/billiards/low_speed_single_contact.json")
        asset_resolution = resolve_asset_intents(case)
        layout = build_static_scene_layout(case, asset_resolution=asset_resolution)
        report = verify_static_scene_layout(case, layout)

        self.assertEqual(layout["schema_version"], "harness_scene_layout_v1")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checks"]["overlap_pair_count"], 0)
        self.assertGreaterEqual(report["checks"]["physics_critical_count"], 3)
        self.assertTrue(layout["camera_plan"]["views"])
        self.assertIn(["cue_ball", "target_ball_1"], layout["physics_graph"]["collision_edges"])

    def test_static_scene_verifier_rejects_initial_overlap(self) -> None:
        from harness.assets.asset_resolver import resolve_asset_intents
        from harness.planning.static_scene_builder import build_static_scene_layout
        from harness.verification.static_scene_verifier import verify_static_scene_layout

        case = self.load_case("cases/billiards/low_speed_single_contact.json")
        case = deepcopy(case)
        case["objects"][1]["initial_position_m"] = [-0.95, 0.0, 0.09]
        asset_resolution = resolve_asset_intents(case)

        report = verify_static_scene_layout(case, build_static_scene_layout(case, asset_resolution=asset_resolution))

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F3_invalid_initial_physics_state")
        self.assertEqual(report["first_failure"]["metric"], "initial_overlap_pair")

    def test_thin_panel_does_not_use_horizontal_bounding_circle_for_overlap(self) -> None:
        from harness.assets.asset_resolver import resolve_asset_intents
        from harness.planning.static_scene_builder import build_static_scene_layout

        case = self.load_case("cases/fracture/glass_energy_response_matrix/glass_panel_e16_shatter.json")
        layout = build_static_scene_layout(case, asset_resolution=resolve_asset_intents(case))

        self.assertEqual(layout["overlap_pairs"], [])

    def test_static_scene_verifier_rejects_missing_physics_asset_binding(self) -> None:
        from harness.planning.static_scene_builder import build_static_scene_layout
        from harness.verification.static_scene_verifier import verify_static_scene_layout

        case = self.load_case("cases/billiards/low_speed_single_contact.json")
        empty_resolution = {"schema_version": "harness_asset_resolution_v1", "assets": []}

        report = verify_static_scene_layout(case, build_static_scene_layout(case, asset_resolution=empty_resolution))

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F2_asset_missing")
        self.assertEqual(report["first_failure"]["metric"], "missing_physics_asset_binding")

    def test_falling_case_records_support_relation(self) -> None:
        from harness.assets.asset_resolver import resolve_asset_intents
        from harness.planning.static_scene_builder import build_static_scene_layout
        from harness.verification.static_scene_verifier import verify_static_scene_layout

        case = self.load_case("cases/falling/falling_block_on_floor.json")
        asset_resolution = resolve_asset_intents(case)
        layout = build_static_scene_layout(case, asset_resolution=asset_resolution)
        report = verify_static_scene_layout(case, layout)

        self.assertEqual(report["status"], "pass")
        relation = layout["support_relations"][0]
        self.assertEqual(relation["object_id"], "falling_block")
        self.assertEqual(relation["support_id"], "floor")
        self.assertIn(relation["status"], {"above_support", "contact_at_rest"})

    def test_elastic_anchor_and_suspended_payload_are_valid_free_bodies(self) -> None:
        from harness.assets.asset_resolver import resolve_asset_intents
        from harness.planning.static_scene_builder import build_static_scene_layout
        from harness.verification.static_scene_verifier import verify_static_scene_layout

        case = self.load_case("cases/elastic_constraint/bungee_rebound.json")
        layout = build_static_scene_layout(case, asset_resolution=resolve_asset_intents(case))
        report = verify_static_scene_layout(case, layout)

        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(
            {row["object_id"]: row["status"] for row in layout["support_relations"]},
            {"anchor": "free_body_allowed", "payload": "free_body_allowed"},
        )

    def test_newton_cradle_anchors_and_balls_are_valid_suspended_bodies(self) -> None:
        from harness.assets.asset_resolver import resolve_asset_intents
        from harness.planning.static_scene_builder import build_static_scene_layout
        from harness.verification.static_scene_verifier import verify_static_scene_layout

        case = self.load_case("cases/rigid_collision/newton_cradle/v001_release_angle_ofat/release_25deg.json")
        layout = build_static_scene_layout(case, asset_resolution=resolve_asset_intents(case))
        report = verify_static_scene_layout(case, layout)

        self.assertEqual(report["status"], "pass", report)
        self.assertTrue(all(row["status"] == "above_support" for row in layout["support_relations"]))

    def test_inclined_ramp_uses_surface_normal_for_support_gap(self) -> None:
        from harness.planning.static_scene_builder import build_static_scene_layout

        case = self.load_case("cases/rigid_motion/ramp_roll_slide/v001_friction_regime_ofat/medium_friction_partial_roll.json")
        layout = build_static_scene_layout(case)

        relation = next(row for row in layout["support_relations"] if row["object_id"] == "ramp_subject")
        self.assertEqual(relation["status"], "contact_at_rest")
        self.assertAlmostEqual(relation["vertical_gap_m"], 0.002, places=4)

    def test_static_scene_cli_writes_layout_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "harness_build_static_scene.py"),
                    str(ROOT / "cases" / "billiards" / "low_speed_single_contact.json"),
                    "--output-dir",
                    tmp,
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "pass")
            self.assertTrue((Path(tmp) / "scene_layout.json").exists())
            self.assertTrue((Path(tmp) / "static_scene_report.json").exists())
            self.assertTrue((Path(tmp) / "asset_resolution.json").exists())


if __name__ == "__main__":
    unittest.main()
