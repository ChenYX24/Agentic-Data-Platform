from __future__ import annotations

from typing import Any


DESCENT_EPS = 0.03
REBOUND_EPS = 0.02


def verify_bounce(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence

    body_ids = [
        str(obj.get("id"))
        for obj in case_spec.get("objects", [])
        if str(obj.get("role") or "") in {"bouncing_body", "restitution_subject", "bounce_subject"}
    ]
    if not body_ids:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "bouncing_body_count", 0), evidence

    contacts = [contact for frame in trajectory for contact in frame.get("contacts") or [] if isinstance(contact, dict)]
    if not contacts:
        return "F2_missing_contact_events", failure("support", 0, 0, "contact_count", 0), evidence

    first_contact_frame = min(int(contact.get("frame", 0)) for contact in contacts)
    expected = dict(case_spec.get("expected_physics") or {})
    configured_drop_height = float(expected.get("drop_height_m") or 0.0)

    for object_id in body_ids:
        series = [(frame, (frame.get("objects") or {}).get(object_id) or {}) for frame in trajectory if object_id in (frame.get("objects") or {})]
        if len(series) < 4:
            return "F1_missing_trajectory", failure(object_id, 0, 0, "series_length", len(series)), evidence
        z_values = [vec3(state.get("position_m"))[2] for _, state in series]
        frames = [int(frame.get("frame", index)) for index, (frame, _) in enumerate(series)]
        z_start = z_values[0]
        contact_indices = [index for index, frame_id in enumerate(frames) if frame_id >= first_contact_frame]
        if not contact_indices:
            return "F2_missing_contact_events", failure(object_id, first_contact_frame, 0, "contact_frame_in_series", first_contact_frame), evidence
        contact_index = contact_indices[0]
        z_contact = min(z_values[: contact_index + 1])
        if z_start - z_contact < DESCENT_EPS:
            return "F4_causality_violation", failure(object_id, frames[contact_index], float(series[contact_index][0].get("time_s", 0)), "pre_contact_descent_m", round(z_start - z_contact, 6)), evidence
        post_contact_values = z_values[contact_index + 1 :]
        if not post_contact_values:
            return "F1_missing_trajectory", failure(object_id, frames[contact_index], float(series[contact_index][0].get("time_s", 0)), "post_contact_frames", 0), evidence
        rebound_height = max(post_contact_values) - z_contact
        drop_height = configured_drop_height or (z_start - z_contact)
        rebound_ratio = rebound_height / max(drop_height, 1e-6)
        restitution = float(expected.get("restitution") or object_restitution(case_spec, object_id) or 0.5)
        min_ratio = float(expected.get("expected_min_rebound_ratio") or max(0.02, restitution * restitution * 0.45))
        max_ratio = float(expected.get("expected_max_rebound_ratio") or min(1.0, restitution * restitution * 1.45 + 0.05))
        if rebound_ratio < min_ratio - REBOUND_EPS:
            return "F4_causality_violation", failure(object_id, frames[-1], float(series[-1][0].get("time_s", 0)), "rebound_ratio_too_low", round(rebound_ratio, 6)), evidence
        if rebound_ratio > max_ratio + REBOUND_EPS:
            return "F4_causality_violation", failure(object_id, frames[-1], float(series[-1][0].get("time_s", 0)), "rebound_ratio_too_high", round(rebound_ratio, 6)), evidence
        evidence.append(
            {
                "object_id": object_id,
                "z_start": round(z_start, 6),
                "z_contact": round(z_contact, 6),
                "rebound_height_m": round(rebound_height, 6),
                "drop_height_m": round(drop_height, 6),
                "rebound_ratio": round(rebound_ratio, 6),
                "restitution": restitution,
                "expected_ratio_range": [round(min_ratio, 6), round(max_ratio, 6)],
            }
        )

    return None, None, evidence


def object_restitution(case_spec: dict[str, Any], object_id: str) -> float | None:
    for obj in case_spec.get("objects", []):
        if isinstance(obj, dict) and str(obj.get("id")) == object_id and obj.get("restitution") is not None:
            return float(obj["restitution"])
    return None


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}
