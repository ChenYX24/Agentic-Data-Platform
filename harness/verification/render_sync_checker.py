from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.core.artifact_schema import read_json, write_json


ARTIFACT_SCHEMA_VERSION = "2.3"
RENDER_SYNC_SCHEMA_VERSION = "render_sync_report.v2.3"


def check_render_sync(
    run_dir: str | Path,
    *,
    camera_plan: dict[str, Any] | None = None,
    require_depth: bool = True,
    require_segmentation: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    plan = camera_plan or read_optional_json(run_dir / "camera_plan.json")
    expected_camera_ids = camera_ids_from_plan(plan)
    failures: list[dict[str, Any]] = []
    per_view: dict[str, Any] = {}

    if not expected_camera_ids:
        failures.append(
            {
                "code": "F_VIEW_MISMATCH",
                "camera_id": "",
                "message": "camera_plan.json is missing or has no views",
            }
        )

    for camera_id in expected_camera_ids:
        view_report = validate_view(run_dir, camera_id, require_depth=require_depth, require_segmentation=require_segmentation)
        per_view[camera_id] = view_report
        failures.extend(view_report["failures"])

    failure_codes = [str(item["code"]) for item in failures]
    status = "pass" if not failures else "fail"
    all_depth_from_ue = bool(expected_camera_ids) and all(
        str(view.get("depth_source")) == "ue" for view in per_view.values()
    )
    report = {
        "schema_version": RENDER_SYNC_SCHEMA_VERSION,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "status": status,
        "ue_render_real": status == "pass" and all_depth_from_ue,
        "depth_source": "ue" if all_depth_from_ue else "missing",
        "multi_view_sync_ok": status == "pass",
        "render_pass_valid": status == "pass",
        "render_observability_fail": 0 if status == "pass" else 1,
        "failure_codes": sorted(set(failure_codes)),
        "failures": failures,
        "expected_camera_ids": expected_camera_ids,
        "view_count": len(expected_camera_ids),
        "views": per_view,
        "per_camera_statistics": build_per_camera_statistics(per_view),
        "avg_render_time": average_render_time(per_view),
    }
    if write:
        write_json(run_dir / "render_sync_report.json", report)
    return report


def validate_view(run_dir: Path, camera_id: str, *, require_depth: bool, require_segmentation: bool) -> dict[str, Any]:
    view_dir = run_dir / "views" / camera_id
    rgb_path = view_dir / "rgb.mp4"
    depth_path = view_dir / "depth.exr"
    segmentation_path = view_dir / "segmentation.png"
    meta_path = view_dir / "meta.json"
    failures: list[dict[str, Any]] = []

    if not view_dir.exists():
        failures.append({"code": "F_VIEW_MISMATCH", "camera_id": camera_id, "message": "view directory missing"})
    if not file_nonempty(rgb_path):
        failures.append({"code": "F_VIEW_MISMATCH", "camera_id": camera_id, "message": "rgb.mp4 missing or empty"})
    if require_depth and not file_nonempty(depth_path):
        failures.append({"code": "F_DEPTH_MISSING", "camera_id": camera_id, "message": "depth.exr missing or empty"})
    if require_segmentation and not file_nonempty(segmentation_path):
        failures.append({"code": "F_VIEW_MISMATCH", "camera_id": camera_id, "message": "segmentation.png missing or empty"})

    meta = read_optional_json(meta_path)
    if not meta:
        failures.append({"code": "F_VIEW_MISMATCH", "camera_id": camera_id, "message": "meta.json missing or invalid"})
    frame_count_rgb = int(meta.get("frame_count_rgb") or meta.get("frame_count") or 0)
    frame_count_depth = int(meta.get("frame_count_depth") or 0)
    timestamps_rgb = list(meta.get("timestamps_rgb") or [])
    timestamps_depth = list(meta.get("timestamps_depth") or [])
    depth_source = str(meta.get("depth_source") or "missing")
    depth_variance = float(meta.get("depth_variance") or 0.0)
    segmentation_instance_level = bool(meta.get("instance_level") or meta.get("segmentation_type") == "instance")
    render_time = float(meta.get("render_time_sec") or 0.0)

    if frame_count_rgb <= 0:
        failures.append({"code": "F_RENDER_SYNC_FAIL", "camera_id": camera_id, "message": "rgb frame count is missing or zero"})
    if require_depth and frame_count_depth <= 0:
        failures.append({"code": "F_RENDER_SYNC_FAIL", "camera_id": camera_id, "message": "depth frame count is missing or zero"})
    if require_depth and frame_count_rgb != frame_count_depth:
        failures.append(
            {
                "code": "F_RENDER_SYNC_FAIL",
                "camera_id": camera_id,
                "message": "rgb/depth frame count mismatch",
                "frame_count_rgb": frame_count_rgb,
                "frame_count_depth": frame_count_depth,
            }
        )
    if require_depth and depth_source != "ue":
        failures.append({"code": "F_DEPTH_MISSING", "camera_id": camera_id, "message": "depth_source is not ue"})
    if require_depth and depth_variance <= 0:
        failures.append({"code": "F_DEPTH_MISSING", "camera_id": camera_id, "message": "depth variance is zero or missing"})
    if require_depth and not timestamps_aligned(timestamps_rgb, timestamps_depth):
        failures.append({"code": "F_RENDER_SYNC_FAIL", "camera_id": camera_id, "message": "rgb/depth timestamps are missing or not aligned"})
    if require_segmentation and not segmentation_instance_level:
        failures.append({"code": "F_VIEW_MISMATCH", "camera_id": camera_id, "message": "segmentation is not instance-level"})

    return {
        "camera_id": camera_id,
        "view_dir": relative_or_str(view_dir, run_dir),
        "rgb_path": relative_or_str(rgb_path, run_dir),
        "depth_path": relative_or_str(depth_path, run_dir),
        "segmentation_path": relative_or_str(segmentation_path, run_dir),
        "meta_path": relative_or_str(meta_path, run_dir),
        "frame_count_rgb": frame_count_rgb,
        "frame_count_depth": frame_count_depth,
        "timestamp_count_rgb": len(timestamps_rgb),
        "timestamp_count_depth": len(timestamps_depth),
        "depth_source": depth_source,
        "depth_variance": depth_variance,
        "segmentation_instance_level": segmentation_instance_level,
        "render_time_sec": render_time,
        "status": "pass" if not failures else "fail",
        "failures": failures,
    }


def camera_ids_from_plan(plan: dict[str, Any]) -> list[str]:
    views = plan.get("views") if isinstance(plan, dict) else []
    result: list[str] = []
    if isinstance(views, list):
        for view in views:
            if isinstance(view, dict) and view.get("camera_id"):
                result.append(str(view["camera_id"]))
    return result


def file_nonempty(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = read_json(path)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def timestamps_aligned(left: list[Any], right: list[Any], *, tolerance: float = 1e-6) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    for lhs, rhs in zip(left, right):
        if abs(float(lhs) - float(rhs)) > tolerance:
            return False
    return True


def build_per_camera_statistics(per_view: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for camera_id, view in per_view.items():
        result[camera_id] = {
            "status": view.get("status"),
            "frame_count_rgb": view.get("frame_count_rgb", 0),
            "frame_count_depth": view.get("frame_count_depth", 0),
            "depth_variance": view.get("depth_variance", 0.0),
            "render_time_sec": view.get("render_time_sec", 0.0),
            "failure_codes": sorted({str(item["code"]) for item in view.get("failures", [])}),
        }
    return result


def average_render_time(per_view: dict[str, Any]) -> float:
    values = [float(view.get("render_time_sec") or 0.0) for view in per_view.values()]
    values = [value for value in values if value > 0]
    return round(sum(values) / len(values), 6) if values else 0.0


def relative_or_str(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
