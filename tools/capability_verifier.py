from __future__ import annotations

import math
from typing import Any

from tools.failure_taxonomy import failure_record, first_failure_type


SPEED_EPS_M_S = 0.05
POSITION_EPS_M = 0.01
CONTACT_ACTIVE_ROLES = {"active_striker", "active_driver", "active_body", "impactor"}
CONTACT_PASSIVE_ROLES = {"passive_target", "passive_receiver", "passive_body", "target_body"}


class CapabilityVerifier:
    def verify(self, capability_plan: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
        failures: list[dict[str, Any]] = []
        layers = {
            "schema_validity": self._schema_validity(capability_plan, execution),
            "initial_physics_validity": self._initial_physics_validity(capability_plan, execution),
            "runtime_causality_validity": self._runtime_causality_validity(capability_plan, execution),
            "render_evidence_validity": self._render_evidence_validity(execution),
        }
        for layer in layers.values():
            failures.extend(layer.get("failures") or [])
        capability_ready = not failures
        evidence = execution.get("render_evidence") if isinstance(execution.get("render_evidence"), dict) else {}
        reference_video_ready = bool(evidence.get("video_available") and capability_ready)
        return {
            "schema_version": "capability_verifier_report_v1",
            "case_id": execution.get("case_id"),
            "capability_ids": capability_plan.get("matched_capabilities", []),
            "capability_ready": capability_ready,
            "reference_video_ready": reference_video_ready,
            "artifact_tier": "reference_video" if reference_video_ready else "simulated_trace_not_video",
            "layers": layers,
            "failure_modes": failures,
            "primary_failure_type": first_failure_type(failures),
            "diagnosis": self._diagnosis(failures, capability_plan),
        }

    def _schema_validity(self, capability_plan: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
        failures = []
        if capability_plan.get("schema_version") != "capability_plan_v1":
            failures.append(failure_record("F1_scene_parsing_failure", "capability plan schema_version is invalid"))
        if execution.get("schema_version") != "capability_execution_trace_v1":
            failures.append(failure_record("F1_scene_parsing_failure", "execution trace schema_version is invalid"))
        objects = execution.get("objects")
        trajectory = execution.get("trajectory")
        if not isinstance(objects, list) or not objects:
            failures.append(failure_record("F1_scene_parsing_failure", "execution trace has no objects"))
        if not isinstance(trajectory, list) or len(trajectory) < 2:
            failures.append(failure_record("F5_weak_visual_evidence", "execution trace has fewer than two trajectory frames"))
        return {"passed": not failures, "failures": failures}

    def _initial_physics_validity(self, capability_plan: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
        capability_id = str(capability_plan.get("primary_capability_id") or "")
        objects = execution_objects(execution)
        failures: list[dict[str, Any]] = []
        if capability_id in {"rigid_body_contact_causality", "billiard_causality_compiler"}:
            active = [obj for obj in objects.values() if str(obj.get("role")) in CONTACT_ACTIVE_ROLES]
            passive = [obj for obj in objects.values() if str(obj.get("role")) in CONTACT_PASSIVE_ROLES]
            if not active or not passive:
                failures.append(failure_record("F1_scene_parsing_failure", "contact causality requires active and passive rigid-body roles"))
            for obj in passive:
                speed = vector_norm(initial_velocity(obj))
                if speed > SPEED_EPS_M_S:
                    failures.append(failure_record("F3_invalid_initial_physics_state", "passive body has non-zero initial velocity", evidence={"object_id": obj.get("id"), "speed_m_s": round(speed, 4)}))
                if not physics_flag(obj, "collision_enabled", default=True):
                    failures.append(failure_record("F3_invalid_initial_physics_state", "passive body collision is disabled", evidence={"object_id": obj.get("id")}))
        elif capability_id == "rigid_body_gravity_collision":
            gravity = abs(float((execution.get("environment") or {}).get("gravity_m_s2") or 0.0))
            falling = [obj for obj in objects.values() if obj.get("role") in {"falling_body", "stack_block"}]
            if gravity <= 0.1:
                failures.append(failure_record("F3_invalid_initial_physics_state", "gravity must be enabled for falling blocks"))
            if not falling:
                failures.append(failure_record("F1_scene_parsing_failure", "falling blocks capability requires falling_body objects"))
            for obj in falling:
                if not physics_flag(obj, "gravity_enabled", default=True):
                    failures.append(failure_record("F3_invalid_initial_physics_state", "falling body gravity is disabled", evidence={"object_id": obj.get("id")}))
                if not physics_flag(obj, "collision_enabled", default=True):
                    failures.append(failure_record("F3_invalid_initial_physics_state", "falling body collision is disabled", evidence={"object_id": obj.get("id")}))
        elif capability_id == "sequential_contact_propagation":
            dominoes = sorted((obj for obj in objects.values() if obj.get("role") == "domino"), key=lambda item: str(item.get("id")))
            if len(dominoes) < 3:
                failures.append(failure_record("F1_scene_parsing_failure", "domino chain requires at least three domino objects"))
            if dominoes and max(vector_norm(initial_angular_velocity(dominoes[0])), vector_norm(initial_velocity(dominoes[0]))) <= SPEED_EPS_M_S:
                failures.append(failure_record("F3_invalid_initial_physics_state", "first domino must have an active trigger impulse or angular velocity", evidence={"object_id": dominoes[0].get("id")}))
            for obj in dominoes[1:]:
                angular_speed = vector_norm(initial_angular_velocity(obj))
                linear_speed = vector_norm(initial_velocity(obj))
                if max(angular_speed, linear_speed) > SPEED_EPS_M_S:
                    failures.append(failure_record("F3_invalid_initial_physics_state", "non-first domino has initial motion", evidence={"object_id": obj.get("id")}))
                if not physics_flag(obj, "collision_enabled", default=True):
                    failures.append(failure_record("F3_invalid_initial_physics_state", "domino collision is disabled", evidence={"object_id": obj.get("id")}))
        return {"passed": not failures, "failures": failures}

    def _runtime_causality_validity(self, capability_plan: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
        capability_id = str(capability_plan.get("primary_capability_id") or "")
        if capability_id in {"rigid_body_contact_causality", "billiard_causality_compiler"}:
            return self._verify_contact_causality(execution)
        if capability_id == "rigid_body_gravity_collision":
            return self._verify_falling_blocks(execution)
        if capability_id == "sequential_contact_propagation":
            return self._verify_domino_chain(execution)
        return {"passed": True, "failures": []}

    def _verify_contact_causality(self, execution: dict[str, Any]) -> dict[str, Any]:
        objects = execution_objects(execution)
        active_ids = {oid for oid, obj in objects.items() if str(obj.get("role")) in CONTACT_ACTIVE_ROLES}
        passive_ids = {oid for oid, obj in objects.items() if str(obj.get("role")) in CONTACT_PASSIVE_ROLES}
        trajectory = execution.get("trajectory") or []
        failures: list[dict[str, Any]] = []
        activation_frame_by_passive: dict[str, int] = {}
        activated = set(active_ids)
        for index, frame in enumerate(trajectory):
            for contact in frame.get("contacts") or []:
                pair = {str(item) for item in contact.get("objects") or []}
                if not pair & activated:
                    continue
                newly_activated = sorted((pair & passive_ids) - activated)
                for passive_id in newly_activated:
                    activation_frame_by_passive.setdefault(passive_id, index)
                activated.update(newly_activated)
        if not activation_frame_by_passive:
            failures.append(failure_record("F4_causality_violation", "no active-to-passive rigid-body contact propagation was recorded"))
        for passive_id in sorted(passive_ids):
            first_contact = activation_frame_by_passive.get(passive_id, len(trajectory))
            moved_after_contact = False
            for index, frame in enumerate(trajectory):
                state = frame_objects(frame).get(passive_id) or {}
                speed = vector_norm(state_velocity(state))
                if index < first_contact and speed > SPEED_EPS_M_S:
                    failures.append(failure_record("F4_causality_violation", "passive body moved before first active contact", evidence={"object_id": passive_id, "frame": frame.get("frame", index), "speed_m_s": round(speed, 4)}))
                    break
                if index >= first_contact and speed > SPEED_EPS_M_S:
                    moved_after_contact = True
            if first_contact < len(trajectory) and not moved_after_contact:
                failures.append(failure_record("F4_causality_violation", "passive target had contact but no post-contact motion", evidence={"object_id": passive_id}))
        return {"passed": not failures, "failures": failures}

    def _verify_falling_blocks(self, execution: dict[str, Any]) -> dict[str, Any]:
        objects = execution_objects(execution)
        falling_ids = [oid for oid, obj in objects.items() if obj.get("role") in {"falling_body", "stack_block"}]
        trajectory = execution.get("trajectory") or []
        contacts = all_contacts(trajectory)
        failures: list[dict[str, Any]] = []
        for object_id in falling_ids:
            series = object_series(trajectory, object_id)
            if len(series) < 2:
                failures.append(failure_record("F5_weak_visual_evidence", "falling body missing trajectory series", evidence={"object_id": object_id}))
                continue
            z_start = position(series[0][1])[2]
            z_min = min(position(state)[2] for _, state in series)
            if z_min >= z_start - POSITION_EPS_M:
                failures.append(failure_record("F4_causality_violation", "falling body did not descend under gravity", evidence={"object_id": object_id, "z_start": z_start, "z_min": z_min}))
        if not any({"ground", "floor", "support"} & {str(item).lower() for item in contact.get("objects") or []} for contact in contacts):
            failures.append(failure_record("F5_weak_visual_evidence", "no ground/support contact event recorded for falling blocks"))
        return {"passed": not failures, "failures": failures}

    def _verify_domino_chain(self, execution: dict[str, Any]) -> dict[str, Any]:
        objects = execution_objects(execution)
        domino_ids = sorted(oid for oid, obj in objects.items() if obj.get("role") == "domino")
        trajectory = execution.get("trajectory") or []
        failures: list[dict[str, Any]] = []
        start_times: list[float | None] = []
        for object_id in domino_ids:
            start_times.append(first_rotation_time(trajectory, object_id, threshold_degrees=12.0))
        if len([value for value in start_times if value is not None]) < len(domino_ids):
            failures.append(failure_record("F4_causality_violation", "not every domino tipped past threshold", evidence={"tip_start_times_s": start_times}))
        observed = [value for value in start_times if value is not None]
        if observed and observed != sorted(observed):
            failures.append(failure_record("F4_causality_violation", "domino tip order is not sequential", evidence={"tip_start_times_s": start_times}))
        contacts = all_contacts(trajectory)
        expected_pairs = {tuple(sorted((domino_ids[i], domino_ids[i + 1]))) for i in range(max(0, len(domino_ids) - 1))}
        observed_pairs = {tuple(sorted(str(item) for item in contact.get("objects") or [])) for contact in contacts if len(contact.get("objects") or []) >= 2}
        missing_pairs = sorted(pair for pair in expected_pairs if pair not in observed_pairs)
        if missing_pairs:
            failures.append(failure_record("F4_causality_violation", "sequential domino contact pairs are missing", evidence={"missing_pairs": missing_pairs}))
        return {"passed": not failures, "failures": failures}

    def _render_evidence_validity(self, execution: dict[str, Any]) -> dict[str, Any]:
        evidence = execution.get("render_evidence") if isinstance(execution.get("render_evidence"), dict) else {}
        failures = []
        if evidence.get("runtime_status") == "failed":
            failures.append(failure_record("F6_runtime_or_render_failure", "runtime backend reported failure"))
        if not evidence.get("trajectory_available"):
            failures.append(failure_record("F5_weak_visual_evidence", "trajectory evidence is missing"))
        if evidence.get("source_type") == "VISUAL_ONLY":
            failures.append(failure_record("F5_weak_visual_evidence", "visual-only animation cannot verify physical causality"))
        return {"passed": not failures, "failures": failures, "source_type": evidence.get("source_type"), "video_available": bool(evidence.get("video_available"))}

    def _diagnosis(self, failures: list[dict[str, Any]], capability_plan: dict[str, Any]) -> dict[str, Any]:
        if not failures:
            return {
                "root_cause": "none",
                "repair_suggestion": "capability loop passed; run UE/native render next if reference video is required",
            }
        first = failures[0]
        failure_type = str(first.get("failure_type") or "")
        suggestions = {
            "F1_scene_parsing_failure": "repair prompt expansion and object roles before execution",
            "F2_asset_missing": "resolve typed assets or controlled proxies before runtime",
            "F3_invalid_initial_physics_state": "fix initial velocities, gravity, collision flags, spacing, or rigid-body bindings",
            "F4_causality_violation": "remove hidden passive motion and require runtime contact events to trigger downstream motion",
            "F5_weak_visual_evidence": "capture trajectory/contact/render evidence or mark the run as non-reference",
            "F6_runtime_or_render_failure": "rerun backend or switch to fallback with explicit failure reason",
            "F7_verifier_false_positive_or_negative": "tighten verifier rule and add regression trace",
        }
        return {
            "root_cause": first.get("reason"),
            "repair_suggestion": suggestions.get(failure_type, "inspect verifier evidence"),
            "capability_id": capability_plan.get("primary_capability_id"),
        }


def execution_objects(execution: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(obj.get("id")): obj for obj in execution.get("objects") or [] if isinstance(obj, dict) and obj.get("id")}


def frame_objects(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = frame.get("objects")
    return objects if isinstance(objects, dict) else {}


def object_series(trajectory: list[dict[str, Any]], object_id: str) -> list[tuple[float, dict[str, Any]]]:
    series = []
    for frame in trajectory:
        state = frame_objects(frame).get(object_id)
        if isinstance(state, dict):
            series.append((float(frame.get("time_s") or frame.get("time") or 0.0), state))
    return series


def all_contacts(trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [contact for frame in trajectory for contact in frame.get("contacts") or [] if isinstance(contact, dict)]


def initial_velocity(obj: dict[str, Any]) -> list[float]:
    return vec3((obj.get("initial_state") or {}).get("linear_velocity_m_s"))


def initial_angular_velocity(obj: dict[str, Any]) -> list[float]:
    return vec3((obj.get("initial_state") or {}).get("angular_velocity_deg_s"))


def state_velocity(state: dict[str, Any]) -> list[float]:
    if isinstance(state.get("velocity_m_s"), list):
        return vec3(state.get("velocity_m_s"))
    if isinstance(state.get("velocity_cm_s"), list):
        return [value / 100.0 for value in vec3(state.get("velocity_cm_s"))]
    return [0.0, 0.0, 0.0]


def position(state: dict[str, Any]) -> list[float]:
    return vec3(state.get("position_m") or state.get("position"))


def rotation(state: dict[str, Any]) -> list[float]:
    return vec3(state.get("rotation_deg") or state.get("rotation_degrees"))


def first_rotation_time(trajectory: list[dict[str, Any]], object_id: str, *, threshold_degrees: float) -> float | None:
    for time_s, state in object_series(trajectory, object_id):
        if max(abs(value) for value in rotation(state)) >= threshold_degrees:
            return time_s
    return None


def physics_flag(obj: dict[str, Any], key: str, *, default: bool) -> bool:
    physics = obj.get("physics") if isinstance(obj.get("physics"), dict) else {}
    return bool(physics.get(key, default))


def vec3(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return [0.0, 0.0, 0.0]
    padded = [*value, 0.0, 0.0, 0.0]
    try:
        return [float(padded[0]), float(padded[1]), float(padded[2])]
    except Exception:
        return [0.0, 0.0, 0.0]


def vector_norm(value: list[float]) -> float:
    return math.sqrt(sum(float(item) * float(item) for item in value[:3]))
