from __future__ import annotations

from math import dist, isclose, isfinite
from typing import Any

from harness.core.case_spec import fracture_response_for_energy


def verify_brittle_fracture(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    if not trajectory:
        return "F1_missing_trajectory", failure("trajectory", 0, 0, "frame_count", 0), evidence

    expected = dict(case_spec.get("expected_physics") or {})
    impactor_id = str(expected.get("impactor_object_id") or first_role(case_spec, {"active_impactor", "active_striker"}) or "impactor")
    brittle_id = str(expected.get("brittle_object_id") or first_role(case_spec, {"brittle_fracture_body", "breakable_body", "destructible_body"}) or "brittle_body")
    response = object_fracture_response(case_spec, brittle_id)
    if str(response.get("mode") or "") == "contact_external_strain":
        impactor_id = str(response.get("impactor_id") or impactor_id)
        return verify_external_strain_fracture(case_spec, trajectory, impactor_id, brittle_id, response)
    threshold = positive_float(expected.get("fracture_threshold_j")) or object_threshold(case_spec, brittle_id)
    if threshold is None:
        return "F3_invalid_initial_physics_state", failure(brittle_id, 0, 0, "fracture_threshold_j", expected.get("fracture_threshold_j")), evidence
    min_fragments = int(expected.get("expected_min_fragment_count") or 2)

    contact = first_contact_event(trajectory, impactor_id, brittle_id)
    fracture = first_fracture_event(trajectory, brittle_id)
    if fracture and contact and int(fracture.get("frame") or 0) < int(contact.get("frame") or 0):
        detail = failure(brittle_id, int(fracture.get("frame") or 0), float(fracture.get("time_s") or 0.0), "fracture_frame_before_contact", int(fracture.get("frame") or 0))
        detail["contact_frame"] = int(contact.get("frame") or 0)
        return "F4_causality_violation", detail, evidence
    if contact is None:
        if fracture:
            return "F4_causality_violation", failure(brittle_id, int(fracture.get("frame") or 0), float(fracture.get("time_s") or 0.0), "fracture_without_contact", True), evidence
        return "F2_missing_contact_events", failure(f"{impactor_id}:{brittle_id}", 0, 0, "contact_event_present", False), evidence

    impact_energy = positive_float(contact.get("impact_energy_j") or contact.get("energy_j"))
    if impact_energy is None:
        return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", int(contact.get("frame") or 0), float(contact.get("time_s") or 0.0), "impact_energy_j_present", False), evidence

    if fracture is None:
        if impact_energy >= threshold:
            return "F7_runtime_artifact_incomplete", failure(brittle_id, int(contact.get("frame") or 0), float(contact.get("time_s") or 0.0), "fracture_event_present", False), evidence
        return None, None, [{"brittle_object_id": brittle_id, "impact_energy_j": round(impact_energy, 6), "fractured": False}]

    fracture_frame = int(fracture.get("frame") or 0)
    contact_frame = int(contact.get("frame") or 0)
    if fracture_frame < contact_frame:
        detail = failure(brittle_id, fracture_frame, float(fracture.get("time_s") or 0.0), "fracture_frame_before_contact", fracture_frame)
        detail["contact_frame"] = contact_frame
        return "F4_causality_violation", detail, evidence
    event_energy = positive_float(fracture.get("impact_energy_j") or fracture.get("energy_j")) or impact_energy
    if event_energy < threshold:
        detail = failure(brittle_id, fracture_frame, float(fracture.get("time_s") or 0.0), "impact_energy_j", round(event_energy, 6))
        detail["fracture_threshold_j"] = round(threshold, 6)
        return "F4_causality_violation", detail, evidence

    manifest_count, lineage_complete = fragment_manifest_summary(trajectory, brittle_id, fracture_frame)
    if not lineage_complete:
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, float(fracture.get("time_s") or 0.0), "fragment_lineage_complete", False), evidence
    fragment_count = int(fracture.get("fragment_count") or manifest_count)
    if fragment_count != manifest_count:
        detail = failure(brittle_id, fracture_frame, float(fracture.get("time_s") or 0.0), "fragment_count_matches_manifest", fragment_count)
        detail["fragment_manifest_count"] = manifest_count
        return "F7_runtime_artifact_incomplete", detail, evidence
    if fragment_count < min_fragments:
        detail = failure(brittle_id, fracture_frame, float(fracture.get("time_s") or 0.0), "fragment_count", fragment_count)
        detail["expected_min_fragment_count"] = min_fragments
        return "F4_causality_violation", detail, evidence

    evidence.append(
        {
            "impactor_object_id": impactor_id,
            "fractured_object_id": brittle_id,
            "contact_frame": contact_frame,
            "fracture_frame": fracture_frame,
            "impact_energy_j": round(event_energy, 6),
            "fracture_threshold_j": round(threshold, 6),
            "fragment_count": fragment_count,
        }
    )
    return None, None, evidence


def verify_external_strain_fracture(
    case_spec: dict[str, Any],
    trajectory: list[dict[str, Any]],
    impactor_id: str,
    brittle_id: str,
    response: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    contact = first_contact_event(trajectory, impactor_id, brittle_id, native_only=True)
    fracture = first_fracture_event(trajectory, brittle_id)
    if contact is None:
        diagnostic_contact = first_contact_event(trajectory, impactor_id, brittle_id)
        if diagnostic_contact is not None:
            return "F7_runtime_artifact_incomplete", failure(
                f"{impactor_id}:{brittle_id}",
                int(diagnostic_contact.get("frame") or 0),
                float(diagnostic_contact.get("time_s") or 0.0),
                "native_collision_present",
                False,
            ), evidence
        if fracture:
            return "F4_causality_violation", failure(brittle_id, int(fracture.get("frame") or 0), float(fracture.get("time_s") or 0.0), "fracture_without_contact", True), evidence
        return "F2_missing_contact_events", failure(f"{impactor_id}:{brittle_id}", 0, 0, "contact_event_present", False), evidence

    if contact.get("native_collision") is not True:
        return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", int(contact.get("frame") or 0), float(contact.get("time_s") or 0.0), "native_collision_present", False), evidence
    expected_fracture = (case_spec.get("expected_physics") or {}).get("expected_fracture")
    levels = response.get("energy_response_levels")
    minimum_impact_energy_j = positive_float(response.get("minimum_impact_energy_j"))
    impact_energy_j = None
    if minimum_impact_energy_j is not None or isinstance(levels, list):
        try:
            impact_energy_j = float(contact.get("impact_energy_j"))
        except (TypeError, ValueError):
            pass
        if impact_energy_j is None or impact_energy_j < 0.0:
            return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", int(contact.get("frame") or 0), float(contact.get("time_s") or 0.0), "impact_energy_j_present", False), evidence
        selected_response = fracture_response_for_energy(response, impact_energy_j)
        if isinstance(levels, list):
            if selected_response is not None:
                minimum_impact_energy_j = positive_float(selected_response.get("minimum_impact_energy_j"))
            else:
                minimum_impact_energy_j = min(
                    float(level.get("minimum_impact_energy_j") or 0.0)
                    for level in levels
                    if isinstance(level, dict)
                )
        else:
            selected_response = response
        contact_frame = int(contact.get("frame") or 0)
        if contact.get("energy_model") != "ue_component_precontact_sample_translational_energy":
            return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "energy_model", contact.get("energy_model")), evidence
        try:
            energy_sample_frame = int(contact["energy_sample_frame"])
        except (KeyError, TypeError, ValueError):
            return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "energy_sample_frame_present", False), evidence
        if energy_sample_frame >= contact_frame:
            detail = failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "energy_sample_frame_before_contact", energy_sample_frame)
            detail["contact_frame"] = contact_frame
            return "F4_causality_violation", detail, evidence
        try:
            recorded_threshold = float(contact["minimum_impact_energy_j"])
        except (KeyError, TypeError, ValueError):
            return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "minimum_impact_energy_j_present", False), evidence
        if not isclose(recorded_threshold, minimum_impact_energy_j, rel_tol=1e-6, abs_tol=1e-6):
            detail = failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "minimum_impact_energy_j_matches_config", recorded_threshold)
            detail["configured_minimum_impact_energy_j"] = minimum_impact_energy_j
            return "F4_causality_violation", detail, evidence
        if not isinstance(contact.get("energy_gate_passed"), bool):
            return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "energy_gate_passed_present", False), evidence
        expected_gate = selected_response is not None and impact_energy_j >= minimum_impact_energy_j
        if contact["energy_gate_passed"] is not expected_gate:
            detail = failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "energy_gate_matches_measurement", contact["energy_gate_passed"])
            detail["expected_energy_gate_passed"] = expected_gate
            return "F4_causality_violation", detail, evidence
        if not isinstance(contact.get("external_strain_applied"), bool):
            return "F7_runtime_artifact_incomplete", failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "external_strain_applied_present", False), evidence
        if contact["external_strain_applied"] is not expected_gate:
            detail = failure(f"{impactor_id}:{brittle_id}", contact_frame, float(contact.get("time_s") or 0.0), "external_strain_applied_matches_gate", contact["external_strain_applied"])
            detail["expected_external_strain_applied"] = expected_gate
            return "F4_causality_violation", detail, evidence
    else:
        selected_response = response

    configured_response = selected_response
    if configured_response is None and isinstance(levels, list) and levels:
        configured_response = levels[0]
    configured_strain = positive_float((configured_response or {}).get("external_strain"))
    thresholds = response.get("damage_thresholds") or []
    damage_threshold = positive_float(thresholds[0] if isinstance(thresholds, list) and thresholds else None)
    if configured_strain is None or damage_threshold is None:
        return "F3_invalid_initial_physics_state", failure(brittle_id, 0, 0, "external_strain_configuration", response), evidence
    if configured_strain < damage_threshold:
        detail = failure(brittle_id, 0, 0, "external_strain_below_damage_threshold", configured_strain)
        detail["damage_threshold"] = damage_threshold
        return "F3_invalid_initial_physics_state", detail, evidence
    if fracture is None:
        if expected_fracture is True:
            return "F7_runtime_artifact_incomplete", failure(brittle_id, int(contact.get("frame") or 0), float(contact.get("time_s") or 0.0), "expected_fracture", False), evidence
        if minimum_impact_energy_j is not None and impact_energy_j < minimum_impact_energy_j:
            return None, None, [{"impactor_object_id": impactor_id, "brittle_object_id": brittle_id, "impact_energy_j": round(impact_energy_j, 6), "minimum_impact_energy_j": minimum_impact_energy_j, "energy_sample_frame": energy_sample_frame, "energy_gate_passed": False, "external_strain_applied": False, "expected_fracture": expected_fracture, "fractured": False}]
        return "F7_runtime_artifact_incomplete", failure(brittle_id, int(contact.get("frame") or 0), float(contact.get("time_s") or 0.0), "fracture_event_present", False), evidence
    if minimum_impact_energy_j is not None and impact_energy_j < minimum_impact_energy_j:
        detail = failure(brittle_id, int(fracture.get("frame") or 0), float(fracture.get("time_s") or 0.0), "fracture_below_impact_energy_gate", impact_energy_j)
        detail["minimum_impact_energy_j"] = minimum_impact_energy_j
        return "F4_causality_violation", detail, evidence
    if expected_fracture is False:
        return "F4_causality_violation", failure(brittle_id, int(fracture.get("frame") or 0), float(fracture.get("time_s") or 0.0), "unexpected_fracture", True), evidence

    if response.get("center_source") == "native_contact_impact_point":
        contact_center = finite_point3(contact.get("impact_point_cm"))
        fracture_center = finite_point3(fracture.get("fracture_center_cm"))
        if contact_center is None or fracture_center is None:
            return "F7_runtime_artifact_incomplete", failure(
                brittle_id,
                int(fracture.get("frame") or 0),
                float(fracture.get("time_s") or 0.0),
                "native_impact_fracture_center_present",
                False,
            ), evidence
        if fracture.get("fracture_center_source") != "native_contact_impact_point":
            return "F7_runtime_artifact_incomplete", failure(
                brittle_id,
                int(fracture.get("frame") or 0),
                float(fracture.get("time_s") or 0.0),
                "fracture_center_source",
                fracture.get("fracture_center_source"),
            ), evidence
        tolerance_cm = positive_float(response.get("fracture_center_tolerance_cm")) or 0.1
        center_error_cm = dist(contact_center, fracture_center)
        if center_error_cm > tolerance_cm:
            detail = failure(
                brittle_id,
                int(fracture.get("frame") or 0),
                float(fracture.get("time_s") or 0.0),
                "fracture_center_matches_native_impact_point",
                round(center_error_cm, 6),
            )
            detail["fracture_center_tolerance_cm"] = tolerance_cm
            return "F4_causality_violation", detail, evidence
    else:
        center_error_cm = None

    expected_damage_state = str((selected_response or {}).get("damage_state") or "") or None
    if expected_damage_state and fracture.get("damage_state") != expected_damage_state:
        detail = failure(brittle_id, int(fracture.get("frame") or 0), float(fracture.get("time_s") or 0.0), "damage_state_matches_energy_response", fracture.get("damage_state"))
        detail["expected_damage_state"] = expected_damage_state
        return "F4_causality_violation", detail, evidence

    contact_frame = int(contact.get("frame") or 0)
    fracture_frame = int(fracture.get("frame") or 0)
    fracture_time = float(fracture.get("time_s") or 0.0)
    if fracture_frame < contact_frame:
        detail = failure(brittle_id, fracture_frame, fracture_time, "fracture_frame_before_contact", fracture_frame)
        detail["contact_frame"] = contact_frame
        return "F4_causality_violation", detail, evidence
    if "root_broken" not in fracture:
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "root_broken_present", False), evidence
    if fracture.get("root_broken") is not True:
        return "F4_causality_violation", failure(brittle_id, fracture_frame, fracture_time, "root_broken", fracture.get("root_broken")), evidence
    if fracture.get("native_break_event") is not True:
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "native_break_event_present", False), evidence

    event_strain = positive_float(fracture.get("external_strain"))
    if event_strain is None:
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "external_strain_present", False), evidence
    if not isclose(event_strain, configured_strain, rel_tol=1e-6, abs_tol=1e-6):
        detail = failure(brittle_id, fracture_frame, fracture_time, "external_strain_matches_config", event_strain)
        detail["configured_external_strain"] = configured_strain
        return "F4_causality_violation", detail, evidence
    runtime_thresholds = fracture.get("damage_thresholds_runtime") or []
    runtime_damage_threshold = positive_float(runtime_thresholds[0] if isinstance(runtime_thresholds, list) and runtime_thresholds else None)
    if runtime_damage_threshold is None or not fracture.get("damage_threshold_source"):
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "runtime_damage_threshold_present", False), evidence
    if not isclose(runtime_damage_threshold, damage_threshold, rel_tol=1e-6, abs_tol=1e-6):
        detail = failure(brittle_id, fracture_frame, fracture_time, "runtime_damage_threshold_matches_config", runtime_damage_threshold)
        detail["configured_damage_threshold"] = damage_threshold
        return "F4_causality_violation", detail, evidence
    if event_strain < runtime_damage_threshold:
        detail = failure(brittle_id, fracture_frame, fracture_time, "external_strain", event_strain)
        detail["damage_threshold"] = runtime_damage_threshold
        return "F4_causality_violation", detail, evidence

    if "fragment_count" not in fracture:
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "fragment_count_present", False), evidence
    try:
        fragment_count = int(fracture["fragment_count"])
    except (TypeError, ValueError):
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "fragment_count_present", False), evidence
    manifest_count, lineage_complete = fragment_manifest_summary(trajectory, brittle_id, fracture_frame)
    if not lineage_complete:
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "fragment_lineage_complete", False), evidence
    if manifest_count == 0:
        return "F7_runtime_artifact_incomplete", failure(brittle_id, fracture_frame, fracture_time, "fragment_manifest_present", False), evidence
    if fragment_count != manifest_count:
        detail = failure(brittle_id, fracture_frame, fracture_time, "fragment_count_matches_manifest", fragment_count)
        detail["fragment_manifest_count"] = manifest_count
        return "F7_runtime_artifact_incomplete", detail, evidence
    min_fragments = int((case_spec.get("expected_physics") or {}).get("expected_min_fragment_count") or 2)
    if fragment_count < min_fragments:
        detail = failure(brittle_id, fracture_frame, fracture_time, "fragment_count", fragment_count)
        detail["expected_min_fragment_count"] = min_fragments
        return "F4_causality_violation", detail, evidence

    evidence.append({
        "impactor_object_id": impactor_id,
        "fractured_object_id": brittle_id,
        "contact_frame": contact_frame,
        "fracture_frame": fracture_frame,
        "external_strain": event_strain,
        "impact_energy_j": impact_energy_j,
        "minimum_impact_energy_j": minimum_impact_energy_j,
        "damage_state": expected_damage_state,
        "expected_fracture": expected_fracture,
        "damage_threshold": runtime_damage_threshold,
        "damage_threshold_source": fracture.get("damage_threshold_source"),
        "root_broken": True,
        "native_break_event": True,
        "fragment_count": fragment_count,
        "fracture_center_source": fracture.get("fracture_center_source"),
        "fracture_center_error_cm": round(center_error_cm, 6) if center_error_cm is not None else None,
    })
    return None, None, evidence


def first_contact_event(
    trajectory: list[dict[str, Any]],
    a: str,
    b: str,
    *,
    native_only: bool = False,
) -> dict[str, Any] | None:
    for frame in trajectory:
        frame_id = int(frame.get("frame") or 0)
        time_s = float(frame.get("time_s") or 0.0)
        for contact in frame.get("contacts") or []:
            if not isinstance(contact, dict):
                continue
            objects = [str(item) for item in contact.get("objects") or contact.get("pair") or []]
            if {a, b}.issubset(set(objects)):
                if native_only and contact.get("native_collision") is not True:
                    continue
                result = dict(contact)
                result.setdefault("frame", frame_id)
                result.setdefault("time_s", time_s)
                return result
    return None


def first_fracture_event(trajectory: list[dict[str, Any]], object_id: str) -> dict[str, Any] | None:
    for frame in trajectory:
        frame_id = int(frame.get("frame") or 0)
        time_s = float(frame.get("time_s") or 0.0)
        for event in frame.get("fracture_events") or []:
            if not isinstance(event, dict):
                continue
            if str(event.get("event_type") or "fracture") != "fracture":
                continue
            if str(event.get("object_id") or event.get("source_object_id") or object_id) != object_id:
                continue
            result = dict(event)
            result.setdefault("frame", frame_id)
            result.setdefault("time_s", time_s)
            return result
    return None


def fragment_manifest_summary(trajectory: list[dict[str, Any]], object_id: str, start_frame: int) -> tuple[int, bool]:
    ids: set[str] = set()
    for frame in trajectory:
        if int(frame.get("frame") or 0) < start_frame:
            continue
        for fragment in frame.get("fragments") or []:
            if not isinstance(fragment, dict):
                continue
            source_object_id = fragment.get("source_object_id")
            fragment_id = fragment.get("fragment_id")
            if not source_object_id:
                return 0, False
            if str(source_object_id) != object_id:
                continue
            if not fragment_id:
                return 0, False
            ids.add(str(fragment_id))
    return len(ids), True


def first_role(case_spec: dict[str, Any], roles: set[str]) -> str | None:
    for obj in case_objects(case_spec):
        if str(obj.get("role") or (obj.get("params") or {}).get("role") or "") in roles:
            return str(obj.get("id"))
    return None


def object_threshold(case_spec: dict[str, Any], object_id: str) -> float | None:
    for obj in case_objects(case_spec):
        if str(obj.get("id")) == object_id:
            return positive_float(obj.get("fracture_threshold_j") or (obj.get("params") or {}).get("fracture_threshold_j"))
    return None


def object_fracture_response(case_spec: dict[str, Any], object_id: str) -> dict[str, Any]:
    for obj in case_objects(case_spec):
        if str(obj.get("id")) != object_id:
            continue
        response = obj.get("fracture_response") or (obj.get("params") or {}).get("fracture_response")
        return dict(response) if isinstance(response, dict) else {}
    return {}


def case_objects(case_spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        obj
        for key in ("objects", "dynamic_objects", "static_objects")
        for obj in (case_spec.get(key) or [])
        if isinstance(obj, dict)
    ]


def finite_point3(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        point = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(isfinite(item) for item in point):
        return None
    return point


def positive_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0.0 else None


def failure(object_id: str, frame: int, time: float, metric: str, value: Any) -> dict[str, Any]:
    return {"object_id": object_id, "frame": frame, "time": time, "metric": metric, "value": value}
