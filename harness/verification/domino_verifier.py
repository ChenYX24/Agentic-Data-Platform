from __future__ import annotations

from typing import Any


ROTATION_THRESHOLD_DEG = 12.0


def verify_domino(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence
    domino_ids = [str(obj.get("id")) for obj in case_spec.get("objects", []) if str(obj.get("role") or "") == "domino"]
    if len(domino_ids) < 3:
        return "F7_runtime_artifact_incomplete", failure("case_spec", 0, 0, "domino_count", len(domino_ids)), evidence
    activation = {object_id: first_activation_frame(trajectory, object_id) for object_id in domino_ids}
    contacts = contact_pairs_by_frame(trajectory)
    for idx, object_id in enumerate(domino_ids[1:], start=1):
        previous = domino_ids[idx - 1]
        pair = tuple(sorted((previous, object_id)))
        contact_frame = contacts.get(pair)
        if activation.get(object_id) is None:
            return "F4_causality_violation", failure(object_id, -1, 0, "activation_frame", None, first_broken_edge=[previous, object_id]), evidence
        if contact_frame is None:
            return "F2_missing_contact_events", failure(object_id, activation[object_id], 0, "missing_contact_edge", list(pair), first_broken_edge=[previous, object_id]), evidence
        if activation[object_id] < contact_frame:
            return "F4_causality_violation", failure(object_id, activation[object_id], 0, "activation_before_contact", contact_frame, first_broken_edge=[previous, object_id]), evidence
        evidence.append({"edge": [previous, object_id], "contact_frame": contact_frame, "activation_frame": activation[object_id]})
    passive_activations = [activation[item] for item in domino_ids[1:] if activation[item] is not None]
    if len(passive_activations) != len(set(passive_activations)):
        return "F4_causality_violation", failure("passive_dominoes", min(passive_activations), 0, "simultaneous_activation_frames", passive_activations), evidence
    return None, None, evidence


def first_activation_frame(trajectory: list[dict[str, Any]], object_id: str) -> int | None:
    for idx, frame in enumerate(trajectory):
        state = (frame.get("objects") or {}).get(object_id) or {}
        rotation = state.get("rotation_deg") or state.get("rotation_degrees") or [0, 0, 0]
        if max(abs(float(value)) for value in [*rotation, 0, 0, 0][:3]) >= ROTATION_THRESHOLD_DEG:
            return int(frame.get("frame", idx))
    return None


def contact_pairs_by_frame(trajectory: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for idx, frame in enumerate(trajectory):
        frame_id = int(frame.get("frame", idx))
        for contact in frame.get("contacts") or []:
            objects = [str(item) for item in contact.get("objects") or []]
            if len(objects) >= 2:
                result.setdefault(tuple(sorted(objects[:2])), frame_id)
    return result


def failure(object_id: str, frame: int | None, time: float, metric: str, value: Any, **extra: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value, **extra}
