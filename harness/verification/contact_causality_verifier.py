from __future__ import annotations

import math
from typing import Any


SPEED_EPS = 0.05
DISPLACEMENT_EPS = 0.01
COMPLETE_PASSIVE_PROPAGATION_SPREADS = frozenset({"full_rack_break", "angled_rack_break"})


def requires_complete_passive_propagation(case_spec: dict[str, Any]) -> bool:
    expected = case_spec.get("expected_physics") or {}
    explicit = expected.get("require_all_passive_contact_and_motion")
    if explicit is not None:
        return bool(explicit)
    return str(expected.get("expected_spread") or "") in COMPLETE_PASSIVE_PROPAGATION_SPREADS


def verify_contact_causality(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence
    contacts = all_contacts(trajectory)
    if not contacts:
        return "F2_missing_contact_events", failure("contact_events", 0, 0, "contact_count", 0), evidence
    missing_edge = missing_expected_collision_edge(case_spec, contacts)
    if missing_edge:
        return "F2_missing_contact_events", missing_edge, evidence
    overlap = initial_overlap(case_spec)
    if overlap:
        return "F3_initial_overlap", overlap, evidence
    active = set(str(item) for item in case_spec.get("active_objects", []))
    passive = set(str(item) for item in case_spec.get("passive_objects", []))
    if not active or not passive:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "active_passive_sets", 0), evidence
    first_frame = trajectory[0]
    active_motion = max(
        (
            distance(
                position(frame_objects(frame).get(object_id) or {}),
                position(frame_objects(first_frame).get(object_id) or {}),
            )
            for object_id in active
            for frame in trajectory[1:]
        ),
        default=0.0,
    )
    if active_motion <= DISPLACEMENT_EPS:
        return "F4_causality_violation", failure("active_objects", 0, 0, "active_displacement_m", round(active_motion, 6)), evidence
    for object_id in sorted(passive):
        state = frame_objects(first_frame).get(object_id) or {}
        speed = norm(state.get("velocity_m_s"))
        if speed > SPEED_EPS:
            return "F5_passive_precontact_motion", failure(object_id, first_frame_id(first_frame), frame_time(first_frame), "velocity_m_s", speed), evidence
    contact_frame_by_passive = first_activation_contacts(trajectory, active, passive)
    if not contact_frame_by_passive:
        return "F4_causality_violation", failure("passive_targets", 0, 0, "active_contact_count", 0), evidence
    complete_passive_propagation = requires_complete_passive_propagation(case_spec)
    first_positions = {oid: position(frame_objects(first_frame).get(oid) or {}) for oid in passive}
    for object_id in sorted(passive):
        contact_index = contact_frame_by_passive.get(object_id)
        nearest_contact_frame = first_frame_id(trajectory[contact_index]) if contact_index is not None else None
        if complete_passive_propagation and contact_index is None:
            return "F4_causality_violation", failure(object_id, 0, 0, "full_rack_passive_contact_missing", 0), evidence
        frames_to_check = trajectory[:contact_index] if contact_index is not None else trajectory
        for idx, frame in enumerate(frames_to_check):
            state = frame_objects(frame).get(object_id) or {}
            speed = norm(state.get("velocity_m_s"))
            displacement = distance(position(state), first_positions.get(object_id, [0, 0, 0]))
            if speed > SPEED_EPS or displacement > DISPLACEMENT_EPS:
                detail = failure(object_id, first_frame_id(frame), frame_time(frame), "precontact_velocity_m_s", speed)
                detail["nearest_contact_frame"] = nearest_contact_frame
                detail["displacement_m"] = round(displacement, 6)
                return "F4_causality_violation", detail, evidence
        if contact_index is None:
            for frame in frames_to_check:
                state = frame_objects(frame).get(object_id) or {}
                speed = norm(state.get("velocity_m_s"))
                displacement = distance(position(state), first_positions.get(object_id, [0, 0, 0]))
                if speed > SPEED_EPS or displacement > DISPLACEMENT_EPS:
                    detail = failure(object_id, first_frame_id(frame), frame_time(frame), "unexplained_passive_motion_without_contact", speed)
                    detail["nearest_contact_frame"] = None
                    detail["displacement_m"] = round(displacement, 6)
                    return "F4_causality_violation", detail, evidence
        max_displacement = max(
            (
                distance(position(frame_objects(frame).get(object_id) or {}), first_positions.get(object_id, [0, 0, 0]))
                for frame in trajectory
            ),
            default=0.0,
        )
        if complete_passive_propagation and max_displacement + 1e-9 < DISPLACEMENT_EPS:
            return "F4_causality_violation", failure(object_id, 0, 0, "full_rack_passive_displacement_m", round(max_displacement, 6)), evidence
        evidence.append({"object_id": object_id, "first_contact_frame": nearest_contact_frame, "max_displacement_m": round(max_displacement, 6)})
    return None, None, evidence


def first_activation_contacts(trajectory: list[dict[str, Any]], active: set[str], passive: set[str]) -> dict[str, int]:
    activated = set(active)
    result: dict[str, int] = {}
    for idx, frame in enumerate(trajectory):
        for contact in frame.get("contacts") or []:
            pair = {str(item) for item in contact.get("objects") or []}
            if not pair & activated:
                continue
            for object_id in sorted((pair & passive) - activated):
                result.setdefault(object_id, idx)
            activated.update(pair & passive)
    return result


def initial_overlap(case_spec: dict[str, Any]) -> dict[str, Any] | None:
    objects = [item for item in case_spec.get("objects", []) if isinstance(item, dict)]
    for i, a in enumerate(objects):
        for b in objects[i + 1 :]:
            if "support" in {a.get("role"), b.get("role")}:
                continue
            ra = float(a.get("radius_m") or 0.0)
            rb = float(b.get("radius_m") or 0.0)
            if not ra or not rb:
                continue
            pa = a.get("initial_position_m") or [0, 0, 0]
            pb = b.get("initial_position_m") or [0, 0, 0]
            gap = distance(pa, pb) - (ra + rb)
            if gap < -0.001:
                return failure(f"{a.get('id')}:{b.get('id')}", 0, 0, "initial_overlap_gap_m", round(gap, 6))
    return None


def all_contacts(trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [contact for frame in trajectory for contact in frame.get("contacts") or [] if isinstance(contact, dict)]


def missing_expected_collision_edge(case_spec: dict[str, Any], contacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    graph = (case_spec.get("expected_physics") or {}).get("collision_graph") or []
    if not isinstance(graph, list):
        return None
    observed = {tuple(sorted(str(item) for item in contact.get("objects") or [])) for contact in contacts if len(contact.get("objects") or []) >= 2}
    for edge in graph:
        if not isinstance(edge, list) or len(edge) < 2:
            continue
        pair = tuple(sorted(str(item) for item in edge[:2]))
        if pair not in observed:
            return failure(":".join(pair), 0, 0, "missing_expected_collision_edge", list(pair))
    return None


def frame_objects(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = frame.get("objects")
    return objects if isinstance(objects, dict) else {}


def position(state: dict[str, Any]) -> list[float]:
    value = state.get("position_m") or state.get("position") or [0, 0, 0]
    return vec3(value)


def first_frame_id(frame: dict[str, Any]) -> int:
    return int(frame.get("frame") or 0)


def frame_time(frame: dict[str, Any]) -> float:
    return float(frame.get("time_s") or frame.get("time") or 0.0)


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}


def norm(value: Any) -> float:
    return math.sqrt(sum(item * item for item in vec3(value)))


def distance(a: Any, b: Any) -> float:
    av = vec3(a)
    bv = vec3(b)
    return math.sqrt(sum((av[i] - bv[i]) ** 2 for i in range(3)))


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    return [float(padded[0]), float(padded[1]), float(padded[2])]
