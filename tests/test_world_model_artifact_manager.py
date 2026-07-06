from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.artifact_manager import ArtifactManager
from harness.core.artifact_schema import read_json, write_json


class WorldModelArtifactManagerTests(unittest.TestCase):
    def test_finalize_writes_canonical_dataset_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            camera_plan = {
                "views": [
                    {"camera_id": "front_static", "location": [1, -1, 1], "rotation": [0, 0, 0], "target": [0, 0, 0], "fov": 60},
                ]
            }
            render_config = {"fps": 60, "width": 320, "height": 180, "mode": "both"}
            manager = ArtifactManager(run_dir)
            manager.write_inputs(case_spec={"case_id": "case_a"}, scene_spec={"case_id": "case_a"}, camera_plan=camera_plan, render_config=render_config)
            write_json(
                run_dir / "trajectory.json",
                [
                    {"frame": 0, "time": 0.0, "objects": {"body": {"position": [0, 0, 1], "velocity": [0, 0, 0]}}},
                    {"frame": 1, "time": 1 / 60, "objects": {"body": {"position": [0, 0, 0.9], "velocity": [0, 0, -1]}}},
                ],
            )
            write_json(run_dir / "contact_events.json", [{"frame": 1, "objects": ["body", "floor"]}])
            write_json(
                run_dir / "render_sync_report.json",
                {
                    "status": "pass",
                    "multi_view_sync_ok": True,
                    "render_pass_valid": True,
                    "per_camera_statistics": {"front_static": {"frame_count_rgb": 2}},
                },
            )
            view_dir = run_dir / "views" / "front_static"
            view_dir.mkdir(parents=True)
            (view_dir / "rgb.mp4").write_bytes(b"rgb")
            (view_dir / "depth.exr").write_bytes(b"depth")
            (view_dir / "segmentation.png").write_bytes(b"mask")
            write_json(view_dir / "meta.json", {"instance_level": True, "instance_count": 1, "instance_mapping": [{"id": 1, "actor": "body"}]})
            (run_dir / "video.mp4").write_bytes(b"hero rgb")

            manifest = manager.finalize(
                run_id="run_a",
                case_id="case_a",
                mode="both",
                seed=42,
                camera_plan=camera_plan,
                render_config=render_config,
            )

            self.assertEqual(manifest["schema_version"], "world_model_run.v2.3")
            for rel in (
                "manifest.json",
                "inputs/case.json",
                "inputs/scene.json",
                "inputs/camera.json",
                "inputs/render_config.json",
                "passes/rgb/video.mp4",
                "passes/data/depth.exr",
                "passes/data/mask.png",
                "passes/data/instance.json",
                "sync/camera_trajectory.json",
                "sync/physics_trace.json",
                "sync/sync_report.json",
            ):
                self.assertTrue((run_dir / rel).exists(), rel)
                self.assertGreater((run_dir / rel).stat().st_size, 0, rel)
            sync = read_json(run_dir / "sync" / "sync_report.json")
            self.assertEqual(sync["status"], "pass")


if __name__ == "__main__":
    unittest.main()
