from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.artifact_schema import read_json
from harness.runtime.camera_planner import SceneBounds, plan_cameras_for_scene
from harness.runtime.render_pass_contract import verify_render_observability, write_render_contract_artifacts


class RenderPassContractTests(unittest.TestCase):
    def test_fake_run_dir_can_generate_multiview_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            plan = plan_cameras_for_scene(SceneBounds(center=(0, 0, 0.5), extent=(2, 2, 1)))
            manifest = write_render_contract_artifacts(
                run_dir,
                backend="fallback",
                case_id="case_a",
                camera_plan=plan,
                render_passes=["rgb", "depth", "segmentation"],
                allow_placeholders=True,
                source="test_contract",
            )
            self.assertEqual(manifest["schema_version"], "render_pass_manifest.v2.3")
            self.assertEqual(manifest["artifact_schema_version"], "2.3")
            self.assertEqual(len(manifest["views"]), 5)
            self.assertTrue((run_dir / "views" / "front_static" / "rgb.mp4").exists())
            depth_file = run_dir / "views" / "front_static" / "depth_placeholder.json"
            self.assertTrue(depth_file.exists())
            self.assertGreater(depth_file.stat().st_size, 0)
            depth = read_json(depth_file)
            self.assertTrue(depth["placeholder"])
            self.assertFalse(manifest["ue_render_real"])
            self.assertEqual(manifest["depth_source"], "missing")

    def test_frame_count_sync_check_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            plan = plan_cameras_for_scene(SceneBounds(center=(0, 0, 0.5), extent=(2, 2, 1)))
            write_render_contract_artifacts(run_dir, backend="fallback", case_id="case_a", camera_plan=plan, render_passes=["rgb", "depth"], allow_placeholders=True, source="test_contract")
            report = verify_render_observability(run_dir, require_multiview=True, require_depth=True, min_view_count=5)
            self.assertFalse(report["depth_ready"])
            self.assertIn("F_DEPTH_MISSING", {item["code"] for item in report["failures"]})

    def test_missing_depth_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            plan = plan_cameras_for_scene(SceneBounds(center=(0, 0, 0.5), extent=(2, 2, 1)))
            write_render_contract_artifacts(run_dir, backend="ue", case_id="case_a", camera_plan=plan, render_passes=["rgb", "depth"], allow_placeholders=False, source="test_contract")
            target = run_dir / "views" / "side_static" / "depth.exr"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"depth")
            target.unlink()
            report = verify_render_observability(run_dir, require_multiview=True, require_depth=True, min_view_count=5)
            self.assertFalse(report["depth_ready"])
            self.assertIn("F_DEPTH_MISSING", {item["code"] for item in report["failures"]})


if __name__ == "__main__":
    unittest.main()
