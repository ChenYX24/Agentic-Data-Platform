from __future__ import annotations

from typing import Any


CAMERA_SYNC_SCHEMA_VERSION = "camera_sync.v2.3"


def frame_time_map(frame_count: int, fps: int | float) -> list[dict[str, Any]]:
    safe_fps = max(float(fps or 0), 1.0)
    return [
        {"frame_id": index, "timestamp_s": round(index / safe_fps, 6)}
        for index in range(max(0, int(frame_count)))
    ]


def camera_trajectory_from_plan(camera_plan: dict[str, Any], *, frame_count: int, fps: int | float) -> dict[str, Any]:
    mapping = frame_time_map(frame_count, fps)
    views = []
    for view in camera_plan.get("views", []) if isinstance(camera_plan, dict) else []:
        camera_id = str(view.get("camera_id") or view.get("role") or "camera")
        pose = {
            "location": view.get("location") or view.get("position_m"),
            "rotation": view.get("rotation"),
            "target": view.get("target"),
            "fov": view.get("fov"),
        }
        views.append(
            {
                "camera_id": camera_id,
                "timebase": "frame_id / fps",
                "frames": [
                    {
                        "frame_id": item["frame_id"],
                        "timestamp_s": item["timestamp_s"],
                        **pose,
                    }
                    for item in mapping
                ],
            }
        )
    return {
        "schema_version": CAMERA_SYNC_SCHEMA_VERSION,
        "frame_count": len(mapping),
        "fps": fps,
        "frame_time_map": mapping,
        "views": views,
    }


def camera_sync_summary(camera_trajectory: dict[str, Any]) -> dict[str, Any]:
    views = camera_trajectory.get("views") if isinstance(camera_trajectory, dict) else []
    counts = {
        str(view.get("camera_id")): len(view.get("frames") or [])
        for view in views
        if isinstance(view, dict)
    }
    unique_counts = {count for count in counts.values()}
    return {
        "schema_version": "camera_sync_summary.v2.3",
        "view_count": len(counts),
        "frame_counts": counts,
        "frame_count_consistent": len(unique_counts) <= 1,
    }
