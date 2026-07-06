from __future__ import annotations

import math
from typing import Any


SPEED_EPS = 0.05


def verify_elastic_launch(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence

    expected = dict(case_spec.get("expected_physics") or {})
    launcher_id = str(expected.get("launcher_object_id") or first_role(case_spec, {"elastic_launcher", "spring_launcher"}) or "launcher")
    payload_id = str(expected.get("launched_object_id") or first_role(case_spec, {"launched_body", "projectile"}) or "payload")
    mass = positive_float(expected.get("payload_mass_kg")) or object_mass(case_spec, payload_id)
    spring_constant = positive_float(expected.get("spring_constant_n_m"))
    compression = positive_float(expected.get("compression_m"))
    if mass is None:
        return "F3_invalid_initial_physics_state", failure(payload_id, 0, 0, "payload_mass_kg", expected.get("payload_mass_kg")), evidence
    if spring_constant is None:
        return "F3_invalid_initial_physics_state", failure(launcher_id, 0, 0, "spring_constant_n_m", expected.get("spring_constant_n_m")), evidence
    if compression is None:
        return "F3_invalid_initial_physics_state", failure(launcher_id, 0, 0, "compression_m", expected.get("compression_m")), evidence

    first = trajectory[0]
    first_payload = frame_objects(first).get(payload_id)
    if not first_payload:
        return "F7_runtime_artifact_incomplete", failure(payload_id, frame_id(first), frame_time(first), "initial_state_present", False), evidence
    initial_speed = norm(first_payload.get("velocity_m_s"))
    if initial_speed > SPEED_EPS:
        return "F5_passive_precontact_motion", failure(payload_id, frame_id(first), frame_time(first), "initial_velocity_m_s", round(initial_speed, 6)), evidence

    release = first_release_event(trajectory, launcher_id, payload_id)
    if release is None:
        return "F7_runtime_artifact_incomplete", failure(launcher_id, 0, 0, "release_event_present", False), evidence
    release_frame = int(release.get("frame") or 0)

    post_frames = [frame for frame in trajectory if frame_id(frame) >= release_frame]
    if not post_frames:
        return "F7_runtime_artifact_incomplete", failure(payload_id, release_frame, 0, "post_release_frames", 0), evidence
    release_state = first_payload_state(post_frames, payload_id)
    final_state = last_state(trajectory, payload_id)
    release_speed = norm(release_state.get("velocity_m_s"))
    min_speed = float(expected.get("expected_min_launch_speed_m_s") or 0.1)
    if release_speed < min_speed:
        return "F4_causality_violation", failure(payload_id, release_frame, float(release.get("time_s") or 0.0), "post_release_speed_m_s", round(release_speed, 6)), evidence

    initial_pos = position(first_payload)
    final_pos = position(final_state)
    height_gain = final_pos[2] - initial_pos[2]
    forward_displacement = math.sqrt((final_pos[0] - initial_pos[0]) ** 2 + (final_pos[1] - initial_pos[1]) ** 2)
    min_height_gain = float(expected.get("expected_min_height_gain_m") or 0.0)
    min_forward = float(expected.get("expected_min_forward_displacement_m") or 0.0)
    if height_gain < min_height_gain:
        return "F4_causality_violation", failure(payload_id, frame_id(trajectory[-1]), frame_time(trajectory[-1]), "height_gain_m", round(height_gain, 6)), evidence
    if forward_displacement < min_forward:
        return "F4_causality_violation", failure(payload_id, frame_id(trajectory[-1]), frame_time(trajectory[-1]), "forward_displacement_m", round(forward_displacement, 6)), evidence

    stored_energy = 0.5 * spring_constant * compression * compression
    max_speed = max(norm(frame_objects(frame).get(payload_id, {}).get("velocity_m_s")) for frame in post_frames)
    kinetic = 0.5 * mass * max_speed * max_speed
    energy_ratio = kinetic / stored_energy if stored_energy > 1e-9 else 0.0
    max_energy_ratio = float(expected.get("expected_max_energy_ratio") or 1.25)
    if energy_ratio > max_energy_ratio:
        return "F4_causality_violation", failure(payload_id, frame_id(trajectory[-1]), frame_time(trajectory[-1]), "energy_ratio", round(energy_ratio, 6)), evidence

    evidence.append(
        {
            "launcher_object_id": launcher_id,
            "launched_object_id": payload_id,
            "release_frame": release_frame,
            "release_speed_m_s": round(release_speed, 6),
            "height_gain_m": round(height_gain, 6),
            "forward_displacement_m": round(forward_displacement, 6),
            "stored_energy_j": round(stored_energy, 6),
            "energy_ratio": round(energy_ratio, 6),
        }
    )
    return None, None, evidence


def first_release_event(trajectory: list[dict[str, Any]], launcher_id: str, payload_id: str) -> dict[str, Any] | None:
    for frame in trajectory:
        for event in frame.get("spring_events") or frame.get("elastic_events") or []:
            if not isinstance(event, dict):
                continue
            if str(event.get("event_type") or "") != "release":
                continue
            if str(event.get("launcher_id") or launcher_id) != launcher_id:
                continue
            if str(event.get("target_id") or payload_id) != payload_id:
                continue
            result = dict(event)
            result.setdefault("frame", frame_id(frame))
            result.setdefault("time_s", frame_time(frame))
            return result
    return None


def first_payload_state(frames: list[dict[str, Any]], payload_id: str) -> dict[str, Any]:
    for frame in frames:
        state = frame_objects(frame).get(payload_id)
        if state:
            return state
    return {}


def last_state(trajectory: list[dict[str, Any]], object_id: str) -> dict[str, Any]:
    for frame in reversed(trajectory):
        state = frame_objects(frame).get(object_id)
        if state:
            return state
    return {}


def first_role(case_spec: dict[str, Any], roles: set[str]) -> str | None:
    for obj in case_spec.get("objects") or []:
        if isinstance(obj, dict) and str(obj.get("role") or "") in roles:
            return str(obj.get("id"))
    return None


def object_mass(case_spec: dict[str, Any], object_id: str) -> float | None:
    for obj in case_spec.get("objects") or []:
        if isinstance(obj, dict) and str(obj.get("id")) == object_id:
            return positive_float(obj.get("mass_kg"))
    return None


def positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0.0 else None


def frame_objects(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = frame.get("objects")
    return objects if isinstance(objects, dict) else {}


def position(state: dict[str, Any]) -> list[float]:
    return vec3(state.get("position_m") or state.get("position") or [0, 0, 0])


def norm(value: Any) -> float:
    return math.sqrt(sum(item * item for item in vec3(value)))


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def frame_id(frame: dict[str, Any]) -> int:
    return int(frame.get("frame") or 0)


def frame_time(frame: dict[str, Any]) -> float:
    return float(frame.get("time_s") or frame.get("time") or 0.0)


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}
