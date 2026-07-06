from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.artifact_schema import read_json, write_json
from harness.runtime.camera_planner import SceneBounds, camera_plan_to_dict, plan_cameras_for_scene
from harness.verification.render_sync_checker import check_render_sync


class RenderSyncCheckerTests(unittest.TestCase):
    def test_valid_multiview_ue_outputs_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_valid_views(run_dir)
            report = check_render_sync(run_dir)
            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["ue_render_real"])
            self.assertEqual(report["depth_source"], "ue")
            self.assertTrue(report["multi_view_sync_ok"])
            self.assertTrue((run_dir / "render_sync_report.json").exists())

    def test_depth_missing_is_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_valid_views(run_dir)
            (run_dir / "views" / "overview" / "depth.exr").unlink()
            report = check_render_sync(run_dir)
            self.assertEqual(report["status"], "fail")
            self.assertIn("F_DEPTH_MISSING", report["failure_codes"])
            self.assertEqual(report["render_observability_fail"], 1)

    def test_timestamp_mismatch_is_sync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_valid_views(run_dir)
            meta_path = run_dir / "views" / "overview" / "meta.json"
            meta = read_json(meta_path)
            meta["timestamps_depth"] = [0.0, 0.1, 0.3]
            write_json(meta_path, meta)
            report = check_render_sync(run_dir)
            self.assertEqual(report["status"], "fail")
            self.assertIn("F_RENDER_SYNC_FAIL", report["failure_codes"])

    def test_missing_view_is_view_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_valid_views(run_dir)
            for path in (run_dir / "views" / "side").iterdir():
                path.unlink()
            (run_dir / "views" / "side").rmdir()
            report = check_render_sync(run_dir)
            self.assertEqual(report["status"], "fail")
            self.assertIn("F_VIEW_MISMATCH", report["failure_codes"])


def write_valid_views(run_dir: Path) -> None:
    plan = plan_cameras_for_scene(SceneBounds(center=(0, 0, 0.5), extent=(2, 2, 1)), requested_views=["overview", "side"])
    write_json(run_dir / "camera_plan.json", camera_plan_to_dict(plan))
    for camera_id in ("overview", "side"):
        view_dir = run_dir / "views" / camera_id
        view_dir.mkdir(parents=True, exist_ok=True)
        (view_dir / "rgb.mp4").write_bytes(b"rgb")
        (view_dir / "depth.exr").write_bytes(b"depth")
        (view_dir / "segmentation.png").write_bytes(b"seg")
        write_json(
            view_dir / "meta.json",
            {
                "camera_id": camera_id,
                "frame_count_rgb": 3,
                "frame_count_depth": 3,
                "timestamps_rgb": [0.0, 0.1, 0.2],
                "timestamps_depth": [0.0, 0.1, 0.2],
                "depth_source": "ue",
                "depth_variance": 1.25,
                "segmentation_type": "instance",
                "instance_level": True,
                "render_time_sec": 0.05,
            },
        )


if __name__ == "__main__":
    unittest.main()
