from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from harness.core.artifact_schema import read_json, write_json
from harness.core.camera_sync import camera_trajectory_from_plan
from harness.core.physics_logger import build_physics_trace
from harness.core.sync_validator import validate_world_model_run


WORLD_MODEL_SCHEMA_VERSION = "world_model_run.v2.3"


class ArtifactManager:
    """Owns the canonical M2.3 run layout.

    Existing harness files at the run root remain for backward compatibility,
    but dataset consumers should use manifest.json plus inputs/, passes/,
    sync/, and logs/.
    """

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)

    def prepare(self) -> None:
        for rel in (
            "inputs",
            "passes/rgb/frames",
            "passes/data",
            "sync",
            "logs",
        ):
            (self.run_dir / rel).mkdir(parents=True, exist_ok=True)

    def write_inputs(
        self,
        *,
        case_spec: dict[str, Any],
        scene_spec: dict[str, Any],
        camera_plan: dict[str, Any],
        render_config: dict[str, Any],
    ) -> None:
        self.prepare()
        write_json(self.run_dir / "inputs" / "case.json", case_spec)
        write_json(self.run_dir / "inputs" / "scene.json", scene_spec)
        write_json(self.run_dir / "inputs" / "camera.json", camera_plan)
        write_json(self.run_dir / "inputs" / "render_config.json", render_config)

    def finalize(
        self,
        *,
        run_id: str,
        case_id: str,
        mode: str,
        seed: int,
        camera_plan: dict[str, Any],
        render_config: dict[str, Any],
        rgb_video_source: str | Path | None = None,
    ) -> dict[str, Any]:
        self.prepare()
        fps = int(render_config.get("fps") or 60)
        frame_count = infer_frame_count(self.run_dir, fps)
        self.copy_rgb_pass(rgb_video_source)
        self.copy_data_pass()
        self.write_sync_payloads(camera_plan=camera_plan, fps=fps, frame_count=frame_count)
        self.copy_logs()
        sync_report = validate_world_model_run(self.run_dir, write=True)
        manifest = {
            "schema_version": WORLD_MODEL_SCHEMA_VERSION,
            "artifact_schema_version": "2.3",
            "run_id": run_id,
            "case_id": case_id,
            "mode": mode,
            "seed": seed,
            "deterministic": True,
            "ue_renderer_only": True,
            "layout": {
                "inputs": "inputs/",
                "rgb_pass": "passes/rgb/",
                "data_pass": "passes/data/",
                "sync": "sync/",
                "logs": "logs/",
            },
            "render_config": render_config,
            "camera_count": len(camera_plan.get("views", [])) if isinstance(camera_plan, dict) else 0,
            "frame_count": frame_count,
            "sync_report": "sync/sync_report.json",
            "sync_status": sync_report["status"],
            "artifacts": {
                "case": "inputs/case.json",
                "scene": "inputs/scene.json",
                "camera": "inputs/camera.json",
                "render_config": "inputs/render_config.json",
                "rgb_video": "passes/rgb/video.mp4",
                "depth": "passes/data/depth.exr",
                "mask": "passes/data/mask.png",
                "instance": "passes/data/instance.json",
                "camera_trajectory": "sync/camera_trajectory.json",
                "physics_trace": "sync/physics_trace.json",
                "sync_report": "sync/sync_report.json",
            },
        }
        write_json(self.run_dir / "manifest.json", manifest)
        return manifest

    def copy_rgb_pass(self, source: str | Path | None) -> None:
        target = self.run_dir / "passes" / "rgb" / "video.mp4"
        source_path = Path(source) if source else self.run_dir / "video.mp4"
        if source_path.exists() and source_path.stat().st_size > 0:
            shutil.copyfile(source_path, target)

    def copy_data_pass(self) -> None:
        first = first_view_dir(self.run_dir)
        if not first:
            return
        copy_if_present(first / "depth.exr", self.run_dir / "passes" / "data" / "depth.exr")
        copy_if_present(first / "segmentation.png", self.run_dir / "passes" / "data" / "mask.png")
        meta = read_optional_json(first / "meta.json")
        write_json(
            self.run_dir / "passes" / "data" / "instance.json",
            {
                "schema_version": "instance_mask.v2.3",
                "source_view": first.name,
                "segmentation_type": meta.get("segmentation_type", "instance"),
                "instance_level": bool(meta.get("instance_level")),
                "instance_count": int(meta.get("instance_count") or 0),
                "instance_mapping": meta.get("instance_mapping") or [],
            },
        )

    def write_sync_payloads(self, *, camera_plan: dict[str, Any], fps: int, frame_count: int) -> None:
        camera_source = self.run_dir / "camera_trajectory.json"
        if camera_source.exists() and camera_source.stat().st_size > 0:
            copy_if_present(camera_source, self.run_dir / "sync" / "camera_trajectory.json")
        else:
            write_json(
                self.run_dir / "sync" / "camera_trajectory.json",
                camera_trajectory_from_plan(camera_plan, frame_count=frame_count, fps=fps),
            )
        trajectory = read_optional_list(self.run_dir / "trajectory.json")
        contacts = read_optional_list(self.run_dir / "contact_events.json")
        write_json(self.run_dir / "sync" / "physics_trace.json", build_physics_trace(trajectory, contacts, fps=fps))

    def copy_logs(self) -> None:
        for name in ("runner_stdout.json", "runner_stderr.json", "ue_backend_report.json", "local_ue_runner_report.json"):
            copy_if_present(self.run_dir / name, self.run_dir / "logs" / name)
        for source_name, target_name in (
            ("logs/native_rgb/ue_process_stdout.log", "ue_rgb_stdout.log"),
            ("logs/native_rgb/ue_process_stderr.log", "ue_rgb_stderr.log"),
            ("logs/native_data/ue_process_stdout.log", "ue_data_stdout.log"),
            ("logs/native_data/ue_process_stderr.log", "ue_data_stderr.log"),
            ("ue_native_output/ue_process_stdout.log", "ue_stdout.log"),
            ("ue_native_output/ue_process_stderr.log", "ue_stderr.log"),
        ):
            copy_if_present(self.run_dir / source_name, self.run_dir / "logs" / target_name)


def infer_frame_count(run_dir: Path, fps: int) -> int:
    sync = read_optional_json(run_dir / "render_sync_report.json")
    stats = sync.get("per_camera_statistics") if isinstance(sync.get("per_camera_statistics"), dict) else {}
    counts = [int(row.get("frame_count_rgb") or 0) for row in stats.values() if isinstance(row, dict)]
    if counts:
        return max(counts)
    trajectory = read_optional_list(run_dir / "trajectory.json")
    if trajectory:
        return len(trajectory)
    return max(1, fps)


def first_view_dir(run_dir: Path) -> Path | None:
    views_root = run_dir / "views"
    if not views_root.exists():
        return None
    for path in sorted(views_root.iterdir()):
        if path.is_dir():
            return path
    return None


def copy_if_present(source: Path, target: Path) -> None:
    if source.exists() and source.is_file() and source.stat().st_size > 0:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = read_json(path)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def read_optional_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = read_json(path)
    except Exception:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
