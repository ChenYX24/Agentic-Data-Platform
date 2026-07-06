from __future__ import annotations

from typing import Any


APEX_EPS = 0.03
DESCENT_EPS = 0.03
FORWARD_EPS = 0.03


def verify_projectile(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence

    projectile_ids = [
        str(obj.get("id"))
        for obj in case_spec.get("objects", [])
        if str(obj.get("role") or "") in {"projectile", "thrown_body", "launched_body"}
    ]
    if not projectile_ids:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "projectile_count", 0), evidence

    contacts = [contact for frame in trajectory for contact in frame.get("contacts") or [] if isinstance(contact, dict)]
    expected = dict(case_spec.get("expected_physics") or {})
    min_forward = float(expected.get("expected_min_forward_displacement_m", FORWARD_EPS))

    for object_id in projectile_ids:
        series = [(frame, (frame.get("objects") or {}).get(object_id) or {}) for frame in trajectory if object_id in (frame.get("objects") or {})]
        if len(series) < 3:
            return "F1_missing_trajectory", failure(object_id, 0, 0, "series_length", len(series)), evidence
        positions = [vec3(state.get("position_m")) for _, state in series]
        z0 = positions[0][2]
        zmax = max(pos[2] for pos in positions)
        zend = positions[-1][2]
        x_displacement = positions[-1][0] - positions[0][0]
        if zmax < z0 + APEX_EPS:
            return "F4_causality_violation", failure(object_id, int(series[0][0].get("frame", 0)), float(series[0][0].get("time_s", 0)), "apex_gain_m", round(zmax - z0, 6)), evidence
        if zend > zmax - DESCENT_EPS:
            return "F4_causality_violation", failure(object_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "descent_from_apex_m", round(zmax - zend, 6)), evidence
        if x_displacement < min_forward:
            return "F4_causality_violation", failure(object_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "forward_displacement_m", round(x_displacement, 6)), evidence
        evidence.append(
            {
                "object_id": object_id,
                "z_start": round(z0, 6),
                "z_apex": round(zmax, 6),
                "z_end": round(zend, 6),
                "forward_displacement_m": round(x_displacement, 6),
            }
        )

    if not contacts:
        return "F2_missing_contact_events", failure("ground", 0, 0, "contact_count", 0), evidence
    return None, None, evidence


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}
