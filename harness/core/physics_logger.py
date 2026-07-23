from __future__ import annotations

from typing import Any


PHYSICS_TRACE_SCHEMA_VERSION = "physics_trace.v2.3"


def build_physics_trace(
    trajectory: list[dict[str, Any]],
    contact_events: list[dict[str, Any]],
    *,
    fps: int | float,
    timebase: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frames = []
    for frame in trajectory:
        frame_id = int(frame.get("frame") or frame.get("frame_id") or 0)
        time_s = float(frame.get("time_s") if frame.get("time_s") is not None else frame.get("time") or 0.0)
        objects = frame.get("objects") if isinstance(frame.get("objects"), dict) else {}
        frames.append(
            {
                "frame_id": frame_id,
                "timestamp_s": round(time_s, 6),
                "actors": {
                    str(actor_id): {
                        "position": payload.get("position") or payload.get("position_m"),
                        "velocity": payload.get("velocity") or payload.get("velocity_m_s") or payload.get("velocity_cm_s"),
                        "rotation": payload.get("rotation") or payload.get("rotation_degrees"),
                        "source": payload.get("source"),
                    }
                    for actor_id, payload in objects.items()
                    if isinstance(payload, dict)
                },
            }
        )
    return {
        "schema_version": PHYSICS_TRACE_SCHEMA_VERSION,
        "fps": fps,
        "frame_count": len(frames),
        "timestep_s": round(1.0 / max(float(fps or 0), 1.0), 8),
        "physics_timestep_s": (timebase or {}).get("physics_dt_s"),
        "timebase": timebase or {},
        "strict_timestep": True,
        "frames": frames,
        "contact_events": contact_events,
    }


def physics_trace_hash_payload(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "physics_trace_hash_payload.v2.3",
        "frame_count": trace.get("frame_count", 0),
        "contact_count": len(trace.get("contact_events") or []),
        "fps": trace.get("fps"),
    }
