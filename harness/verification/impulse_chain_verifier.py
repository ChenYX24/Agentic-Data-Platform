from __future__ import annotations

import math
from typing import Any


SPEED_EPS = 0.05


def verify_impulse_chain(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence

    expected = dict(case_spec.get("expected_physics") or {})
    chain = [str(item) for item in expected.get("chain_objects") or []]
    if len(chain) < 3:
        chain = [str(obj.get("id")) for obj in case_spec.get("objects", []) if str(obj.get("role") or "") in {"active_chain_driver", "constrained_chain_body"}]
    if len(chain) < 3:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "chain_object_count", len(chain)), evidence

    active_id = str(expected.get("active_object_id") or chain[0])
    receiver_id = str(expected.get("receiver_object_id") or chain[-1])
    if active_id not in chain or receiver_id not in chain:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "active_receiver_in_chain", False), evidence

    first_objects = frame_objects(trajectory[0])
    object_specs = {str(obj.get("id")): obj for obj in case_spec.get("objects", []) if isinstance(obj, dict)}
    for object_id in chain:
        if object_id not in first_objects:
            return "F7_runtime_artifact_incomplete", failure(object_id, frame_id(trajectory[0]), frame_time(trajectory[0]), "initial_state_present", False), evidence
        state = first_objects[object_id]
        if not finite_vec3(state.get("position_m") or state.get("position")) or not finite_vec3(state.get("velocity_m_s")):
            return "F3_invalid_initial_physics_state", failure(object_id, frame_id(trajectory[0]), frame_time(trajectory[0]), "finite_initial_state", False), evidence
        declared_position = (object_specs.get(object_id) or {}).get("initial_position_m")
        if declared_position is not None and dist(position(state), vec3(declared_position)) > 1e-4:
            return "F3_invalid_initial_physics_state", failure(object_id, frame_id(trajectory[0]), frame_time(trajectory[0]), "initial_position_matches_case_spec", False), evidence

    release_angle = abs(float(expected.get("active_release_angle_degrees") or 0.0))
    if not math.isfinite(release_angle):
        return "F3_invalid_initial_physics_state", failure(active_id, 0, 0, "active_release_angle_degrees", release_angle), evidence
    for object_id in chain:
        speed = norm(first_objects[object_id].get("velocity_m_s"))
        if object_id == active_id:
            if speed <= SPEED_EPS and release_angle <= 1e-6:
                return "F3_invalid_initial_physics_state", failure(object_id, frame_id(trajectory[0]), frame_time(trajectory[0]), "active_initial_speed_m_s", round(speed, 6)), evidence
            continue
        if speed > SPEED_EPS:
            return "F5_passive_precontact_motion", failure(object_id, frame_id(trajectory[0]), frame_time(trajectory[0]), "velocity_m_s", round(speed, 6)), evidence

    contact_chain = normalized_contact_chain(expected, chain)
    required_source = str(expected.get("required_trajectory_source") or "")
    if required_source and any(
        str(frame.get("source") or "") != required_source
        or any(str((frame_objects(frame).get(object_id) or {}).get("source") or "") != required_source for object_id in chain)
        for frame in trajectory
    ):
        return "F7_runtime_artifact_incomplete", failure("chain", 0, 0, "impulse_chain_trajectory_source", required_source), evidence
    if required_source and any(
        {str(item.get("body_id") or "") for item in frame.get("constraints") or [] if isinstance(item, dict)} != set(chain)
        or any(str(item.get("source") or "") != required_source for item in frame.get("constraints") or [] if isinstance(item, dict))
        for frame in trajectory
    ):
        return "F7_runtime_artifact_incomplete", failure("chain", 0, 0, "impulse_chain_constraint_trace", required_source), evidence
    if required_source and any(
        str(contact.get("source") or "") != required_source
        for frame in trajectory
        for contact in frame.get("contacts") or []
        if isinstance(contact, dict)
    ):
        return "F7_runtime_artifact_incomplete", failure("chain", 0, 0, "impulse_chain_contact_source", required_source), evidence
    contact_frames = contact_frames_by_pair(trajectory)
    previous_frame = -1
    for edge in contact_chain:
        pair = tuple(sorted(edge))
        contact_frame = contact_frames.get(pair)
        if contact_frame is None:
            return "F2_missing_contact_events", failure(":".join(pair), 0, 0, "missing_contact_edge", list(edge)), evidence
        if contact_frame < previous_frame:
            detail = failure(":".join(pair), contact_frame, frame_time_by_id(trajectory, contact_frame), "contact_chain_order", {"previous_frame": previous_frame, "current_frame": contact_frame})
            detail["edge"] = list(edge)
            return "F4_causality_violation", detail, evidence
        evidence.append({"edge": list(edge), "contact_frame": contact_frame})
        previous_frame = contact_frame

    receiver_speed = max(
        norm((frame_objects(frame).get(receiver_id) or {}).get("velocity_m_s"))
        for frame in trajectory
        if frame_id(frame) >= previous_frame and receiver_id in frame_objects(frame)
    )
    min_receiver_speed = float(expected.get("expected_min_receiver_speed_m_s") or 0.1)
    if receiver_speed < min_receiver_speed:
        return "F4_causality_violation", failure(receiver_id, frame_id(trajectory[-1]), frame_time(trajectory[-1]), "receiver_post_chain_speed_m_s", round(receiver_speed, 6)), evidence

    max_intermediate_displacement = float(expected.get("expected_max_intermediate_displacement_m") or 0.2)
    for object_id in chain[1:-1]:
        displacement = max(
            dist(position(first_objects[object_id]), position(frame_objects(frame).get(object_id) or {}))
            for frame in trajectory
            if object_id in frame_objects(frame)
        )
        if displacement > max_intermediate_displacement:
            return "F4_causality_violation", failure(object_id, frame_id(trajectory[-1]), frame_time(trajectory[-1]), "intermediate_displacement_m", round(displacement, 6)), evidence

    objects = {str(obj.get("id")): obj for obj in case_spec.get("objects", []) if isinstance(obj, dict)}
    initial_energy = chain_energy(trajectory[0], chain, objects, expected)
    maximum_energy = max(chain_energy(frame, chain, objects, expected) for frame in trajectory)
    energy_ratio = maximum_energy / initial_energy if initial_energy > 1e-9 else 0.0
    max_energy_ratio = float(expected.get("expected_energy_ratio_max") or 1.1)
    if energy_ratio > max_energy_ratio:
        return "F4_causality_violation", failure("chain", frame_id(trajectory[-1]), frame_time(trajectory[-1]), "energy_ratio", round(energy_ratio, 6)), evidence

    evidence.insert(
        0,
        {
            "active_object_id": active_id,
            "receiver_object_id": receiver_id,
            "chain_length": len(chain),
            "receiver_post_chain_speed_m_s": round(receiver_speed, 6),
            "energy_ratio": round(energy_ratio, 6),
            "trajectory_source": required_source or None,
        },
    )
    return None, None, evidence


def normalized_contact_chain(expected: dict[str, Any], chain: list[str]) -> list[list[str]]:
    graph = expected.get("expected_contact_chain")
    if isinstance(graph, list) and graph:
        return [[str(edge[0]), str(edge[1])] for edge in graph if isinstance(edge, list) and len(edge) >= 2]
    return [[chain[idx], chain[idx + 1]] for idx in range(len(chain) - 1)]


def contact_frames_by_pair(trajectory: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for frame in trajectory:
        current_frame = frame_id(frame)
        for contact in frame.get("contacts") or []:
            objects = [str(item) for item in contact.get("objects") or []]
            if len(objects) >= 2:
                result.setdefault(tuple(sorted(objects[:2])), current_frame)
    return result


def frame_objects(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = frame.get("objects")
    return objects if isinstance(objects, dict) else {}


def last_state(trajectory: list[dict[str, Any]], object_id: str) -> dict[str, Any]:
    for frame in reversed(trajectory):
        objects = frame_objects(frame)
        if object_id in objects:
            return objects[object_id]
    return {}


def position(state: dict[str, Any]) -> list[float]:
    return vec3(state.get("position_m") or state.get("position") or [0, 0, 0])


def mass_for(objects: dict[str, dict[str, Any]], object_id: str) -> float:
    value = (objects.get(object_id) or {}).get("mass_kg")
    try:
        mass = float(value)
    except (TypeError, ValueError):
        mass = 1.0
    return mass if mass > 0.0 else 1.0


def kinetic_energy(mass: float, velocity: list[float]) -> float:
    return 0.5 * mass * sum(item * item for item in velocity)


def chain_energy(frame: dict[str, Any], chain: list[str], objects: dict[str, dict[str, Any]], expected: dict[str, Any]) -> float:
    rope_length = float(expected.get("rope_length_m") or 0.0)
    by_id = frame_objects(frame)
    total = 0.0
    for object_id in chain:
        spec = objects.get(object_id) or {}
        state = by_id.get(object_id) or {}
        mass = mass_for(objects, object_id)
        total += kinetic_energy(mass, vec3(state.get("velocity_m_s")))
        anchor_id = str(spec.get("constraint_anchor_id") or "")
        anchor = objects.get(anchor_id) or {}
        if rope_length > 0.0 and anchor:
            low_z = position({"position_m": anchor.get("initial_position_m")})[2] - rope_length
            total += mass * 9.81 * max(0.0, position(state)[2] - low_z)
    return total


def norm(value: Any) -> float:
    return math.sqrt(sum(item * item for item in vec3(value)))


def dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((a[idx] - b[idx]) ** 2 for idx in range(3)))


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def finite_vec3(value: Any) -> bool:
    try:
        return all(math.isfinite(item) for item in vec3(value))
    except (TypeError, ValueError):
        return False


def frame_id(frame: dict[str, Any]) -> int:
    return int(frame.get("frame") or 0)


def frame_time(frame: dict[str, Any]) -> float:
    return float(frame.get("time_s") or frame.get("time") or 0.0)


def frame_time_by_id(trajectory: list[dict[str, Any]], target_frame: int) -> float:
    for frame in trajectory:
        if frame_id(frame) == target_frame:
            return frame_time(frame)
    return 0.0


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}
