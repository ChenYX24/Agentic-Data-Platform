from __future__ import annotations

import math
from typing import Any


DRIFT_EPS_M = 0.02
WIND_EPS_M_S = 0.01


def verify_wind(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence

    body_ids = [
        str(obj.get("id"))
        for obj in case_spec.get("objects", [])
        if str(obj.get("role") or "") in {"wind_drift_body", "wind_subject", "balloon", "light_body"}
    ]
    if not body_ids:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "wind_subject_count", 0), evidence

    expected = dict(case_spec.get("expected_physics") or {})
    wind = vec3(expected.get("wind_vector_m_s") or expected.get("wind_vector"))
    wind_horizontal = math.sqrt(wind[0] * wind[0] + wind[1] * wind[1])
    if wind_horizontal <= WIND_EPS_M_S:
        return "F3_invalid_initial_physics_state", failure("force_field", 0, 0, "wind_vector_horizontal_m_s", round(wind_horizontal, 6)), evidence

    unit = [wind[0] / wind_horizontal, wind[1] / wind_horizontal]
    min_drift = float(expected.get("expected_min_wind_aligned_drift_m") or 0.0)
    max_drift = float(expected.get("expected_max_wind_aligned_drift_m") or 1000.0)
    min_altitude = expected.get("expected_min_altitude_m")
    max_altitude = expected.get("expected_max_altitude_m")

    for object_id in body_ids:
        series = [(frame, (frame.get("objects") or {}).get(object_id) or {}) for frame in trajectory if object_id in (frame.get("objects") or {})]
        if len(series) < 2:
            return "F1_missing_trajectory", failure(object_id, 0, 0, "series_length", len(series)), evidence
        positions = [vec3(state.get("position_m")) for _, state in series]
        displacement = [positions[-1][0] - positions[0][0], positions[-1][1] - positions[0][1], positions[-1][2] - positions[0][2]]
        projected = displacement[0] * unit[0] + displacement[1] * unit[1]
        if projected < -DRIFT_EPS_M:
            return "F4_causality_violation", failure(object_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "wind_direction_alignment_m", round(projected, 6)), evidence
        if projected < min_drift:
            return "F4_causality_violation", failure(object_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "wind_aligned_drift_too_small_m", round(projected, 6)), evidence
        if projected > max_drift:
            return "F4_causality_violation", failure(object_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "wind_aligned_drift_too_large_m", round(projected, 6)), evidence
        z_values = [pos[2] for pos in positions]
        if min_altitude is not None and min(z_values) < float(min_altitude):
            return "F4_causality_violation", failure(object_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "altitude_below_min_m", round(min(z_values), 6)), evidence
        if max_altitude is not None and max(z_values) > float(max_altitude):
            return "F4_causality_violation", failure(object_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "altitude_above_max_m", round(max(z_values), 6)), evidence
        evidence.append(
            {
                "object_id": object_id,
                "wind_vector_m_s": [round(wind[0], 6), round(wind[1], 6), round(wind[2], 6)],
                "projected_drift_m": round(projected, 6),
                "xy_displacement_m": [round(displacement[0], 6), round(displacement[1], 6)],
                "altitude_range_m": [round(min(z_values), 6), round(max(z_values), 6)],
            }
        )

    return None, None, evidence


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}
