from __future__ import annotations

import math
import statistics
from typing import Any


DOWNHILL_EPS = 0.02
Z_DROP_EPS = 0.01


def verify_ramp(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence

    subject_ids = [
        str(obj.get("id"))
        for obj in case_spec.get("objects", [])
        if str(obj.get("role") or "") in {"rolling_subject", "sliding_subject", "ramp_subject"}
    ]
    if not subject_ids:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "ramp_subject_count", 0), evidence

    expected = dict(case_spec.get("expected_physics") or {})
    min_distance = float(expected.get("expected_min_downhill_displacement_m", DOWNHILL_EPS))
    max_distance = float(expected.get("expected_max_downhill_displacement_m", 1000.0))
    contacts = [contact for frame in trajectory for contact in frame.get("contacts") or [] if isinstance(contact, dict)]
    required_source = str(expected.get("required_trajectory_source") or "")
    if required_source and any(
        str(frame.get("source") or "") != required_source
        or any(str(state.get("source") or "") != required_source for state in (frame.get("objects") or {}).values())
        or any(str(contact.get("source") or "") != required_source for contact in frame.get("contacts") or [])
        for frame in trajectory
    ):
        return "F7_runtime_artifact_incomplete", failure("ramp_subject", 0, 0, "ramp_trajectory_source", required_source), evidence

    for subject_id in subject_ids:
        series = [(frame, (frame.get("objects") or {}).get(subject_id) or {}) for frame in trajectory if subject_id in (frame.get("objects") or {})]
        if len(series) < 2:
            return "F1_missing_trajectory", failure(subject_id, 0, 0, "series_length", len(series)), evidence
        start = vec3(series[0][1].get("position_m") or series[0][1].get("position"))
        end = vec3(series[-1][1].get("position_m") or series[-1][1].get("position"))
        downhill_displacement = end[0] - start[0]
        z_drop = start[2] - end[2]
        if downhill_displacement < min_distance:
            return "F4_causality_violation", failure(subject_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "downhill_displacement_m", round(downhill_displacement, 6)), evidence
        if downhill_displacement > max_distance:
            return "F4_causality_violation", failure(subject_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "friction_bounded_displacement_m", round(downhill_displacement, 6)), evidence
        if z_drop < Z_DROP_EPS:
            return "F4_causality_violation", failure(subject_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time_s", 0)), "z_drop_m", round(z_drop, 6)), evidence
        slope_angle = math.radians(float(expected.get("slope_angle_deg") or 0.0))
        radius = float(next((obj.get("radius_m") for obj in case_spec.get("objects", []) if obj.get("id") == subject_id), 0.0) or 0.0)
        slip_samples = []
        peak_angular_speed = 0.0
        for frame, state in series:
            velocity = vec3(state.get("velocity_m_s"))
            angular = vec3(state.get("angular_velocity_rad_s"))
            tangent_speed = velocity[0] * math.cos(slope_angle) - velocity[2] * math.sin(slope_angle)
            peak_angular_speed = max(peak_angular_speed, abs(angular[1]))
            if radius > 0.0 and abs(tangent_speed) > 0.1 and has_contact(frame, subject_id, str(expected.get("contact_surface") or "ramp")):
                slip_samples.append(abs(abs(tangent_speed) - radius * abs(angular[1])) / abs(tangent_speed))
        median_slip_ratio = statistics.median(slip_samples) if slip_samples else None
        min_slip = expected.get("expected_min_slip_ratio")
        max_slip = expected.get("expected_max_slip_ratio")
        if min_slip is not None and (median_slip_ratio is None or median_slip_ratio < float(min_slip)):
            return "F4_causality_violation", failure(subject_id, 0, 0, "median_slip_ratio_too_low", None if median_slip_ratio is None else round(median_slip_ratio, 6)), evidence
        if max_slip is not None and (median_slip_ratio is None or median_slip_ratio > float(max_slip)):
            return "F4_causality_violation", failure(subject_id, 0, 0, "median_slip_ratio_too_high", None if median_slip_ratio is None else round(median_slip_ratio, 6)), evidence
        final_speed = math.sqrt(sum(value * value for value in vec3(series[-1][1].get("velocity_m_s"))))
        if expected.get("expected_final_speed_max_m_s") is not None and final_speed > float(expected["expected_final_speed_max_m_s"]):
            return "F4_causality_violation", failure(subject_id, int(series[-1][0].get("frame", 0)), float(series[-1][0].get("time", 0)), "final_speed_m_s", round(final_speed, 6)), evidence
        evidence.append(
            {
                "object_id": subject_id,
                "downhill_displacement_m": round(downhill_displacement, 6),
                "z_drop_m": round(z_drop, 6),
                "friction_dynamic": expected.get("friction_dynamic"),
                "slope_angle_deg": expected.get("slope_angle_deg"),
                "median_slip_ratio": None if median_slip_ratio is None else round(median_slip_ratio, 6),
                "peak_angular_speed_rad_s": round(peak_angular_speed, 6),
                "final_speed_m_s": round(final_speed, 6),
                "motion_mode": expected.get("expected_motion_mode"),
                "trajectory_source": required_source or None,
            }
        )

    if not contacts:
        return "F2_missing_contact_events", failure("ramp", 0, 0, "contact_count", 0), evidence
    return None, None, evidence


def has_contact(frame: dict[str, Any], subject_id: str, surface_id: str) -> bool:
    expected = {subject_id, surface_id}
    return any(expected.issubset({str(item) for item in contact.get("objects") or []}) for contact in frame.get("contacts") or [])


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}
