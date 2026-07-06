from __future__ import annotations

from typing import Any


FAILURE_TAXONOMY: dict[str, dict[str, str]] = {
    "F1_scene_parsing_failure": {
        "stage": "planner",
        "description": "Prompt or scene intent could not be converted into a valid object-level plan.",
    },
    "F2_asset_missing": {
        "stage": "asset_resolution",
        "description": "A required asset, collider, or binding is missing for execution.",
    },
    "F3_invalid_initial_physics_state": {
        "stage": "initial_physics",
        "description": "Initial positions, velocities, gravity, collision flags, or rigid-body settings are invalid.",
    },
    "F4_causality_violation": {
        "stage": "runtime_causality",
        "description": "Passive objects move before the runtime contact or event that should cause their motion.",
    },
    "F5_weak_visual_evidence": {
        "stage": "render_evidence",
        "description": "Trajectory, contact, render, or synchronized evidence is missing or too weak.",
    },
    "F6_runtime_or_render_failure": {
        "stage": "runtime",
        "description": "The simulation or render backend failed to produce usable artifacts.",
    },
    "F7_verifier_false_positive_or_negative": {
        "stage": "verifier",
        "description": "Verifier output conflicts with available evidence and needs rule repair.",
    },
}


VALID_FAILURE_TYPES = frozenset(FAILURE_TAXONOMY)


def is_valid_failure_type(value: str) -> bool:
    return value in VALID_FAILURE_TYPES


def require_valid_failure_type(value: str) -> str:
    if not is_valid_failure_type(value):
        raise ValueError(f"unknown failure type: {value}")
    return value


def failure_record(failure_type: str, reason: str, *, stage: str | None = None, evidence: Any = None) -> dict[str, Any]:
    require_valid_failure_type(failure_type)
    meta = FAILURE_TAXONOMY[failure_type]
    record: dict[str, Any] = {
        "failure_type": failure_type,
        "stage": stage or meta["stage"],
        "reason": reason,
        "description": meta["description"],
    }
    if evidence is not None:
        record["evidence"] = evidence
    return record


def first_failure_type(records: list[dict[str, Any]]) -> str | None:
    for record in records:
        value = str(record.get("failure_type") or "")
        if value in VALID_FAILURE_TYPES:
            return value
    return None
