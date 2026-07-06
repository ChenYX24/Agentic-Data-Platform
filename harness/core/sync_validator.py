from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.core.artifact_schema import read_json, write_json


SYNC_REPORT_SCHEMA_VERSION = "world_model_sync_report.v2.3"


def validate_world_model_run(run_dir: str | Path, *, write: bool = True) -> dict[str, Any]:
    run_dir = Path(run_dir)
    failures: list[dict[str, Any]] = []
    manifest = read_optional_json(run_dir / "manifest.json")
    camera = read_optional_json(run_dir / "sync" / "camera_trajectory.json")
    physics = read_optional_json(run_dir / "sync" / "physics_trace.json")
    sync_report = read_optional_json(run_dir / "render_sync_report.json")

    require_file(run_dir / "inputs" / "case.json", "F_INPUT_MISSING", failures)
    require_file(run_dir / "inputs" / "scene.json", "F_INPUT_MISSING", failures)
    require_file(run_dir / "inputs" / "camera.json", "F_INPUT_MISSING", failures)
    require_file(run_dir / "inputs" / "render_config.json", "F_INPUT_MISSING", failures)
    require_file(run_dir / "passes" / "rgb" / "video.mp4", "F_RGB_MISSING", failures)
    require_file(run_dir / "passes" / "data" / "depth.exr", "F_DEPTH_MISSING", failures)
    require_file(run_dir / "passes" / "data" / "mask.png", "F_MASK_MISSING", failures)
    require_file(run_dir / "passes" / "data" / "instance.json", "F_MASK_MISSING", failures)
    require_file(run_dir / "sync" / "camera_trajectory.json", "F_SYNC_MISSING", failures)
    require_file(run_dir / "sync" / "physics_trace.json", "F_SYNC_MISSING", failures)

    camera_frame_count = int(camera.get("frame_count") or 0)
    physics_frame_count = int(physics.get("frame_count") or 0)
    if camera_frame_count and physics_frame_count and camera_frame_count != physics_frame_count:
        failures.append(
            {
                "code": "F_RENDER_SYNC_FAIL",
                "message": "camera and physics frame counts differ",
                "camera_frame_count": camera_frame_count,
                "physics_frame_count": physics_frame_count,
            }
        )
    if sync_report and sync_report.get("status") != "pass":
        failures.append(
            {
                "code": "F_RENDER_SYNC_FAIL",
                "message": "render_sync_report did not pass",
                "failure_codes": sync_report.get("failure_codes", []),
            }
        )

    report = {
        "schema_version": SYNC_REPORT_SCHEMA_VERSION,
        "artifact_schema_version": "2.3",
        "status": "pass" if not failures else "fail",
        "frame_mismatch_count": 0 if camera_frame_count == physics_frame_count else 1,
        "camera_frame_count": camera_frame_count,
        "physics_frame_count": physics_frame_count,
        "multi_view_sync_ok": bool(sync_report.get("multi_view_sync_ok")) if sync_report else not failures,
        "render_pass_valid": bool(sync_report.get("render_pass_valid")) if sync_report else not failures,
        "manifest_schema": manifest.get("schema_version"),
        "failures": failures,
    }
    if write:
        write_json(run_dir / "sync" / "sync_report.json", report)
    return report


def require_file(path: Path, code: str, failures: list[dict[str, Any]]) -> None:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        failures.append({"code": code, "path": str(path), "message": "required world-model artifact missing or empty"})


def read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = read_json(path)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
