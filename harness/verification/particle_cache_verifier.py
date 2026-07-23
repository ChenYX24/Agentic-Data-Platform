from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def verify_particle_cache(cache: dict[str, Any], *, root: str | Path | None = None) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    frames = cache.get("frames") if isinstance(cache.get("frames"), list) else []
    particles = cache.get("particles") if isinstance(cache.get("particles"), dict) else {}
    expected_count = int(particles.get("count") or 0)
    previous_time = -math.inf
    environment = cache.get("environment") if isinstance(cache.get("environment"), dict) else {}
    for frame in frames:
        frame_id = int(frame.get("frame") or 0)
        time_s = float(frame.get("time_s") or 0.0)
        positions = frame.get("positions_m") if isinstance(frame.get("positions_m"), list) else []
        velocities = frame.get("velocities_m_s") if isinstance(frame.get("velocities_m_s"), list) else []
        if time_s <= previous_time:
            failures.append(failure("non_monotonic_time", frame_id, time_s))
        previous_time = time_s
        if len(positions) != expected_count or len(velocities) != expected_count:
            failures.append(failure("particle_count_changed", frame_id, {"positions": len(positions), "velocities": len(velocities), "expected": expected_count}))
        if not finite_vec3_rows(positions) or not finite_vec3_rows(velocities):
            failures.append(failure("non_finite_particle_state", frame_id, None))
        if finite_vec3_rows(positions) and outside_basin(positions, environment):
            failures.append(failure("container_penetration", frame_id, particle_bounds(positions)))
        surface = frame.get("surface") if isinstance(frame.get("surface"), dict) else {}
        if int(surface.get("vertex_count") or 0) <= 0 or int(surface.get("triangle_count") or 0) <= 0:
            failures.append(failure("surface_mesh_empty", frame_id, surface))
        if surface.get("topology_consistent") is False:
            failures.append(failure("surface_topology_invalid", frame_id, surface.get("topology_issue")))
        bounds = surface.get("bounds_m") if isinstance(surface.get("bounds_m"), dict) else None
        if bounds is not None and surface_bounds_outside_basin(bounds, environment):
            failures.append(failure("surface_container_penetration", frame_id, bounds))
        surface_intersection_metric_applied = environment.get("surface_container_intersection_metric") != "not_applied_for_boundary_contacting_fluid"
        if surface_intersection_metric_applied and int(surface.get("rigid_intersection_vertex_count") or 0) > 0:
            failures.append(
                failure(
                    "surface_rigid_intersection",
                    frame_id,
                    int(surface["rigid_intersection_vertex_count"]),
                )
            )
        if root and surface.get("path"):
            path = Path(root) / str(surface["path"])
            if not path.is_file() or path.stat().st_size == 0:
                failures.append(failure("surface_mesh_missing", frame_id, str(path)))
    if cache.get("schema_version") != "harness_particle_cache_v1":
        failures.append(failure("particle_cache_schema", 0, cache.get("schema_version")))
    if expected_count <= 0 or not frames:
        failures.append(failure("particle_cache_empty", 0, {"particle_count": expected_count, "frame_count": len(frames)}))
    initial_type = str((environment.get("initial_condition") or {}).get("type") or "bounded_volume")
    initial_surface_outlier = None
    if frames and initial_type == "container_fill":
        initial_surface = float(environment.get("initial_liquid_surface_z_m") or 0.0)
        initial_surface_outlier = max(
            (float(row[2]) for row in frames[0].get("positions_m") or []),
            default=initial_surface,
        ) - initial_surface
        maximum_outlier = float(environment.get("maximum_initial_surface_outlier_m") or 0.08)
        if initial_surface_outlier > maximum_outlier:
            failures.append(failure("initial_surface_not_settled", 0, initial_surface_outlier))
    if frames and initial_type == "bounded_volume" and negative_gravity(cache) and center_z(frames[-1]) >= center_z(frames[0]):
        failures.append(failure("gravity_direction_not_observed", int(frames[-1].get("frame") or 0), {"initial_center_z": center_z(frames[0]), "final_center_z": center_z(frames[-1])}))
    rigid_checks = verify_rigid_fluid_response(frames, environment, failures)
    flow_checks = verify_initial_flow_response(frames, environment, failures)
    surface_coherence = verify_final_surface_coherence(frames, environment, failures)
    transfer_checks = verify_container_transfer(frames, environment, failures)
    return {
        "schema_version": "harness_particle_cache_report_v1",
        "status": "pass" if not failures else "fail",
        "failure_codes": sorted({item["code"] for item in failures}),
        "failures": failures,
        "checks": {
            "frame_count": len(frames),
            "particle_count": expected_count,
            "stable_particle_count": not any(item["code"] == "particle_count_changed" for item in failures),
            "surface_frame_count": sum(1 for frame in frames if int((frame.get("surface") or {}).get("triangle_count") or 0) > 0),
            "surface_topology_consistent": not any(item["code"] == "surface_topology_invalid" for item in failures),
            "container_bounds_respected": not any(item["code"] == "container_penetration" for item in failures),
            "surface_container_bounds_respected": not any(item["code"] == "surface_container_penetration" for item in failures),
            "surface_rigid_intersections_absent": (
                not any(item["code"] == "surface_rigid_intersection" for item in failures)
                if environment.get("surface_container_intersection_metric") != "not_applied_for_boundary_contacting_fluid"
                else None
            ),
            "initial_surface_outlier_m": initial_surface_outlier,
            **rigid_checks,
            **flow_checks,
            **surface_coherence,
            **transfer_checks,
        },
    }


def verify_container_transfer(
    frames: list[dict[str, Any]], environment: dict[str, Any], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    if environment.get("type") != "asset_bound_container_transfer" or not frames:
        return {}
    initial = frames[0].get("transfer_state") if isinstance(frames[0].get("transfer_state"), dict) else {}
    final = frames[-1].get("transfer_state") if isinstance(frames[-1].get("transfer_state"), dict) else {}
    required_keys = {"source_fraction", "receiver_fraction", "outside_both_fraction"}
    if not required_keys.issubset(initial) or not required_keys.issubset(final):
        failures.append(failure("container_transfer_state_missing", int(frames[-1].get("frame") or 0), None))
        return {"container_transfer_checked": True}
    initial_source = float(initial["source_fraction"])
    final_source = float(final["source_fraction"])
    final_receiver = float(final["receiver_fraction"])
    final_spill = float(final["outside_both_fraction"])
    source_decrease = initial_source - final_source
    minimum_initial = float(environment.get("minimum_initial_source_fraction") or 0.0)
    minimum_receiver = float(environment.get("minimum_final_receiver_fraction") or 0.0)
    minimum_decrease = float(environment.get("minimum_source_fraction_decrease") or 0.0)
    maximum_spill = float(environment.get("maximum_final_spill_fraction") or 1.0)
    minimum_evacuation_duration = float(environment.get("minimum_source_evacuation_duration_s") or 0.0)
    maximum_drop_per_frame = float(environment.get("maximum_source_fraction_drop_per_frame") or 0.0)
    if initial_source < minimum_initial:
        failures.append(failure("initial_fluid_not_inside_source_container", 0, initial_source))
    if final_receiver < minimum_receiver:
        failures.append(failure("container_transfer_receiver_fraction_too_low", int(frames[-1].get("frame") or 0), final_receiver))
    if source_decrease < minimum_decrease:
        failures.append(failure("container_transfer_source_did_not_empty", int(frames[-1].get("frame") or 0), source_decrease))
    if final_spill > maximum_spill:
        failures.append(failure("container_transfer_spill_too_high", int(frames[-1].get("frame") or 0), final_spill))
    source_series = [float((frame.get("transfer_state") or {}).get("source_fraction") or 0.0) for frame in frames]
    first_discharge = next((index for index, value in enumerate(source_series) if value < initial_source - 0.01), None)
    empty = next((index for index, value in enumerate(source_series) if value <= 0.01), None)
    evacuation_duration = None
    if first_discharge is not None and empty is not None and empty >= first_discharge:
        evacuation_duration = float(frames[empty].get("time_s") or 0.0) - float(frames[first_discharge].get("time_s") or 0.0)
        if minimum_evacuation_duration > 0.0 and evacuation_duration < minimum_evacuation_duration:
            failures.append(failure("container_transfer_source_evacuation_too_abrupt", int(frames[empty].get("frame") or 0), evacuation_duration))
    maximum_drop = max((before - after for before, after in zip(source_series, source_series[1:], strict=False)), default=0.0)
    if maximum_drop_per_frame > 0.0 and maximum_drop > maximum_drop_per_frame:
        failures.append(failure("container_transfer_single_frame_discharge_too_large", 0, maximum_drop))
    transfer_frame = next(
        (
            int(frame.get("frame") or 0)
            for frame in frames[1:]
            if float(((frame.get("transfer_state") or {}).get("receiver_fraction") or 0.0)) >= 0.05
        ),
        None,
    )
    if transfer_frame is None:
        failures.append(failure("container_transfer_event_not_observed", int(frames[-1].get("frame") or 0), None))
    return {
        "container_transfer_checked": True,
        "initial_source_fraction": initial_source,
        "final_source_fraction": final_source,
        "source_fraction_decrease": source_decrease,
        "final_receiver_fraction": final_receiver,
        "final_spill_fraction": final_spill,
        "transfer_event_frame": transfer_frame,
        "source_evacuation_duration_s": evacuation_duration,
        "maximum_source_fraction_drop_per_frame": maximum_drop,
    }


def verify_final_surface_coherence(
    frames: list[dict[str, Any]], environment: dict[str, Any], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    minimum = float(environment.get("minimum_final_surface_component_fraction") or 0.0)
    maximum_ratio = float(environment.get("maximum_final_surface_area_to_volume_ratio_1_m") or 0.0)
    maximum_volume_error = float(environment.get("maximum_final_surface_volume_relative_error") or 0.0)
    if (minimum <= 0.0 and maximum_ratio <= 0.0 and maximum_volume_error <= 0.0) or not frames:
        return {}
    surface = frames[-1].get("surface") if isinstance(frames[-1].get("surface"), dict) else {}
    value = surface.get("largest_component_triangle_fraction")
    if minimum > 0.0 and (not isinstance(value, (int, float)) or not math.isfinite(float(value))):
        failures.append(failure("surface_component_evidence_missing", int(frames[-1].get("frame") or 0), value))
        return {"final_surface_coherence_checked": True, "final_largest_component_fraction": None}
    fraction = float(value) if isinstance(value, (int, float)) else None
    if minimum > 0.0 and fraction is not None and fraction < minimum:
        failures.append(failure("final_surface_too_fragmented", int(frames[-1].get("frame") or 0), fraction))
    ratio = surface.get("surface_area_to_volume_ratio_1_m")
    if maximum_ratio > 0.0 and (not isinstance(ratio, (int, float)) or not math.isfinite(float(ratio))):
        failures.append(failure("surface_shape_evidence_missing", int(frames[-1].get("frame") or 0), ratio))
    elif maximum_ratio > 0.0 and float(ratio) > maximum_ratio:
        failures.append(failure("final_surface_too_stringy", int(frames[-1].get("frame") or 0), float(ratio)))
    initial_volume = float(environment.get("initial_liquid_volume_m3") or 0.0)
    final_volume = surface.get("enclosed_volume_m3")
    volume_error = None
    if maximum_volume_error > 0.0:
        if initial_volume <= 0.0 or not isinstance(final_volume, (int, float)) or not math.isfinite(float(final_volume)):
            failures.append(failure("surface_volume_evidence_missing", int(frames[-1].get("frame") or 0), final_volume))
        else:
            volume_error = abs(float(final_volume) - initial_volume) / initial_volume
            if volume_error > maximum_volume_error:
                failures.append(failure("final_surface_volume_drift", int(frames[-1].get("frame") or 0), volume_error))
    return {
        "final_surface_coherence_checked": True,
        "final_largest_component_fraction": fraction,
        "minimum_final_surface_component_fraction": minimum,
        "final_surface_area_to_volume_ratio_1_m": float(ratio) if isinstance(ratio, (int, float)) else None,
        "maximum_final_surface_area_to_volume_ratio_1_m": maximum_ratio,
        "final_surface_volume_relative_error": volume_error,
        "maximum_final_surface_volume_relative_error": maximum_volume_error,
    }


def verify_initial_flow_response(
    frames: list[dict[str, Any]], environment: dict[str, Any], failures: list[dict[str, Any]]
) -> dict[str, Any]:
    if not frames:
        return {}
    initial = environment.get("initial_condition") if isinstance(environment.get("initial_condition"), dict) else {}
    field = initial.get("velocity_field") if isinstance(initial.get("velocity_field"), dict) else {"type": "still"}
    field_type = str(field.get("type") or "still")
    if field_type == "still":
        return {}
    positions = frames[0].get("positions_m") if isinstance(frames[0].get("positions_m"), list) else []
    velocities = frames[0].get("velocities_m_s") if isinstance(frames[0].get("velocities_m_s"), list) else []
    if not positions or len(positions) != len(velocities):
        failures.append(failure("initial_flow_state_missing", 0, field_type))
        return {"initial_flow_checked": True, "initial_flow_type": field_type}
    mean_speed = sum(math.sqrt(sum(float(value) ** 2 for value in row)) for row in velocities) / len(velocities)
    minimum_speed = float(environment.get("minimum_initial_flow_speed_m_s") or 0.0)
    if mean_speed < minimum_speed:
        failures.append(failure("initial_flow_speed_too_low", 0, mean_speed))

    direction_measure = None
    if field_type == "uniform":
        target = [float(value) for value in field.get("velocity_m_s") or [0.0, 0.0, 0.0]]
        target_speed = math.sqrt(sum(value * value for value in target))
        mean_velocity = [sum(float(row[axis]) for row in velocities) / len(velocities) for axis in range(3)]
        direction_measure = sum(mean_velocity[axis] * target[axis] for axis in range(3)) / max(target_speed, 1e-8)
        if target_speed > 0.0 and direction_measure < target_speed * 0.9:
            failures.append(failure("initial_flow_direction_mismatch", 0, direction_measure))
    elif field_type == "swirl_z":
        center = [float(value) for value in field.get("center_m") or [0.0, 0.0, 0.0]]
        circulation = sum(
            (float(position[0]) - center[0]) * float(velocity[1])
            - (float(position[1]) - center[1]) * float(velocity[0])
            for position, velocity in zip(positions, velocities, strict=True)
        ) / len(positions)
        direction_measure = circulation
        omega = float(field.get("angular_speed_rad_s") or 0.0)
        if circulation == 0.0 or circulation * omega <= 0.0:
            failures.append(failure("initial_swirl_direction_mismatch", 0, circulation))
    else:
        failures.append(failure("initial_flow_type_unsupported", 0, field_type))

    horizontal_displacement = math.dist(center_xy_of_frame(frames[0]), center_xy_of_frame(frames[-1]))
    minimum_horizontal = float(environment.get("minimum_horizontal_displacement_m") or 0.0)
    if horizontal_displacement < minimum_horizontal:
        failures.append(failure("horizontal_flow_displacement_too_low", int(frames[-1].get("frame") or 0), horizontal_displacement))
    initial_max_z = max(float(row[2]) for row in positions)
    jet_rise = max(float(row[2]) for frame in frames for row in frame.get("positions_m") or []) - initial_max_z
    minimum_jet_rise = float(environment.get("minimum_jet_rise_m") or 0.0)
    if jet_rise < minimum_jet_rise:
        failures.append(failure("jet_rise_too_low", 0, jet_rise))
    return {
        "initial_flow_checked": True,
        "initial_flow_type": field_type,
        "initial_mean_speed_m_s": mean_speed,
        "initial_flow_direction_measure": direction_measure,
        "horizontal_displacement_m": horizontal_displacement,
        "jet_rise_m": jet_rise,
    }


def verify_rigid_fluid_response(frames: list[dict[str, Any]], environment: dict[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    specs = environment.get("rigid_objects") if isinstance(environment.get("rigid_objects"), list) else []
    if not specs or not frames:
        return {}
    final_states = frames[-1].get("rigid_objects") if isinstance(frames[-1].get("rigid_objects"), dict) else {}
    floor = float(environment.get("floor_z_m") or 0.0)
    tolerance = float(environment.get("penetration_tolerance_m") or 0.0)
    float_z = sink_z = None
    for spec in specs:
        object_id = str(spec.get("id") or "")
        state = final_states.get(object_id) if isinstance(final_states.get(object_id), dict) else {}
        position = state.get("position_m") if isinstance(state.get("position_m"), list) else []
        if len(position) != 3:
            failures.append(failure("rigid_fluid_state_missing", int(frames[-1].get("frame") or 0), object_id))
            continue
        z = float(position[2])
        radius = float(spec.get("radius_m") or 0.0)
        expected = str(spec.get("expected_response") or "")
        if expected == "float":
            float_z = z
            if z <= floor + radius + tolerance:
                failures.append(failure("buoyant_body_did_not_float", int(frames[-1].get("frame") or 0), {"id": object_id, "z_m": z}))
        elif expected == "sink":
            sink_z = z
            if z > floor + radius + tolerance:
                failures.append(failure("dense_body_did_not_sink", int(frames[-1].get("frame") or 0), {"id": object_id, "z_m": z}))
    required_separation = float(environment.get("minimum_float_sink_separation_m") or 0.0)
    separation = float_z - sink_z if float_z is not None and sink_z is not None else None
    if separation is not None and separation < required_separation:
        failures.append(failure("float_sink_separation_too_small", int(frames[-1].get("frame") or 0), separation))
    initial_surface = float(environment.get("initial_liquid_surface_z_m") or 0.0)
    splash_start = rigid_entry_frame(frames, specs, initial_surface)
    splash_frames = frames[splash_start:] if splash_start is not None else []
    splash_rise = max(
        (float(row[2]) for frame in splash_frames for row in frame.get("positions_m") or []),
        default=initial_surface,
    ) - initial_surface
    required_splash = float(environment.get("minimum_splash_rise_m") or 0.0)
    if splash_rise < required_splash:
        failures.append(failure("splash_not_observed", 0, splash_rise))
    return {
        "rigid_fluid_response_checked": True,
        "float_sink_separation_m": separation,
        "splash_rise_m": splash_rise,
        "splash_measurement_start_frame": splash_start,
    }


def rigid_entry_frame(frames: list[dict[str, Any]], specs: list[dict[str, Any]], surface_z: float) -> int | None:
    radii = {str(spec.get("id") or ""): float(spec.get("radius_m") or 0.0) for spec in specs}
    for index, frame in enumerate(frames):
        states = frame.get("rigid_objects") if isinstance(frame.get("rigid_objects"), dict) else {}
        for object_id, radius in radii.items():
            state = states.get(object_id) if isinstance(states.get(object_id), dict) else {}
            position = state.get("position_m") if isinstance(state.get("position_m"), list) else []
            if len(position) == 3 and float(position[2]) - radius <= surface_z:
                return index
    return None


def finite_vec3_rows(rows: list[Any]) -> bool:
    return all(isinstance(row, list) and len(row) == 3 and all(math.isfinite(float(value)) for value in row) for row in rows)


def center_z(frame: dict[str, Any]) -> float:
    positions = frame.get("positions_m") or []
    return sum(float(row[2]) for row in positions) / max(1, len(positions))


def center_xy_of_frame(frame: dict[str, Any]) -> list[float]:
    positions = frame.get("positions_m") or []
    return [
        sum(float(row[axis]) for row in positions) / max(1, len(positions))
        for axis in range(2)
    ]


def negative_gravity(cache: dict[str, Any]) -> bool:
    gravity = ((cache.get("solver") or {}).get("gravity_m_s2") or [0.0, 0.0, 0.0])
    return isinstance(gravity, list) and len(gravity) >= 3 and float(gravity[2]) < 0.0


def outside_basin(rows: list[Any], environment: dict[str, Any]) -> bool:
    if environment.get("type") == "asset_bound_container_transfer":
        bounds = environment.get("workspace_bounds_m") if isinstance(environment.get("workspace_bounds_m"), dict) else {}
        minimum = bounds.get("min_m") if isinstance(bounds.get("min_m"), list) else []
        maximum = bounds.get("max_m") if isinstance(bounds.get("max_m"), list) else []
        if len(minimum) != 3 or len(maximum) != 3:
            return True
        tolerance = float(environment.get("penetration_tolerance_m") or 0.0)
        return any(
            any(float(row[axis]) < float(minimum[axis]) - tolerance or float(row[axis]) > float(maximum[axis]) + tolerance for axis in range(3))
            for row in rows
        )
    if environment.get("type") != "five_plane_basin":
        return False
    floor = float(environment.get("floor_z_m") or 0.0)
    extent = float(environment.get("wall_half_extent_m") or 0.0)
    tolerance = float(environment.get("penetration_tolerance_m") or 0.0)
    center = environment.get("center_xy_m") or [0.0, 0.0]
    center_x, center_y = float(center[0]), float(center[1])
    return any(
        float(row[2]) < floor - tolerance
        or abs(float(row[0]) - center_x) > extent + tolerance
        or abs(float(row[1]) - center_y) > extent + tolerance
        for row in rows
    )


def particle_bounds(rows: list[Any]) -> dict[str, list[float]]:
    return {
        "min_m": [min(float(row[axis]) for row in rows) for axis in range(3)],
        "max_m": [max(float(row[axis]) for row in rows) for axis in range(3)],
    }


def surface_bounds_outside_basin(bounds: dict[str, Any], environment: dict[str, Any]) -> bool:
    if environment.get("type") == "asset_bound_container_transfer":
        workspace = environment.get("workspace_bounds_m") if isinstance(environment.get("workspace_bounds_m"), dict) else {}
        allowed_minimum = workspace.get("min_m") if isinstance(workspace.get("min_m"), list) else []
        allowed_maximum = workspace.get("max_m") if isinstance(workspace.get("max_m"), list) else []
        minimum = bounds.get("min_m") if isinstance(bounds.get("min_m"), list) else []
        maximum = bounds.get("max_m") if isinstance(bounds.get("max_m"), list) else []
        if any(len(value) != 3 for value in (allowed_minimum, allowed_maximum, minimum, maximum)):
            return True
        tolerance = 1e-6
        return any(
            float(minimum[axis]) < float(allowed_minimum[axis]) - tolerance
            or float(maximum[axis]) > float(allowed_maximum[axis]) + tolerance
            for axis in range(3)
        )
    if environment.get("type") != "five_plane_basin":
        return False
    minimum = bounds.get("min_m") if isinstance(bounds.get("min_m"), list) else []
    maximum = bounds.get("max_m") if isinstance(bounds.get("max_m"), list) else []
    if len(minimum) != 3 or len(maximum) != 3:
        return True
    floor = float(environment.get("floor_z_m") or 0.0)
    extent = float(environment.get("wall_half_extent_m") or 0.0)
    tolerance = 1e-6
    center = environment.get("center_xy_m") or [0.0, 0.0]
    center_x, center_y = float(center[0]), float(center[1])
    return (
        float(minimum[0]) < center_x - extent - tolerance
        or float(maximum[0]) > center_x + extent + tolerance
        or float(minimum[1]) < center_y - extent - tolerance
        or float(maximum[1]) > center_y + extent + tolerance
        or float(minimum[2]) < floor - tolerance
    )


def failure(code: str, frame: int, value: Any) -> dict[str, Any]:
    return {"code": code, "frame": frame, "value": value}
