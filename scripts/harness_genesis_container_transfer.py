from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.core.case_spec import load_case_spec
from harness.core.workspace import workspace_path
from harness.runtime.fluid_container_geometry import (
    compile_container_transfer,
    matrix_vector,
    profile_collision_parts,
    point_inside_profile,
    quaternion_from_matrix,
    rotation_matrix_xyz,
    subtract,
)
from scripts.harness_genesis_fluid import (
    surface_component_metrics,
    surface_shape_metrics,
    tensor_rows,
    write_fluid_cache,
)


def simulate_container_transfer(case_spec: dict[str, Any]) -> dict[str, Any]:
    wake_macos_display()
    import genesis as gs
    import numpy as np
    import pysplashsurf

    compiled = compile_container_transfer(case_spec)
    options = case_spec.get("backend_options") if isinstance(case_spec.get("backend_options"), dict) else {}
    expected = case_spec.get("expected_physics") if isinstance(case_spec.get("expected_physics"), dict) else {}
    physical = case_spec.get("physical_parameters") if isinstance(case_spec.get("physical_parameters"), dict) else {}
    fps = int(options.get("fps") or 24)
    duration_s = float(options.get("duration_s") or 2.0)
    particle_size = float(options.get("particle_size_m") or 0.006)
    steps_per_frame = int(options.get("steps_per_frame") or 145)
    pre_roll_s = float(options.get("pre_roll_s") or 0.0)
    solver_dt = 1.0 / (fps * steps_per_frame)
    gravity = physical.get("gravity_m_s2") or [0.0, 0.0, -9.81]
    reconstruction_options = options.get("surface_reconstruction") if isinstance(options.get("surface_reconstruction"), dict) else {}
    smoothing = float(reconstruction_options.get("smoothing_length_in_particle_radii") or 2.0)
    cube_size = float(reconstruction_options.get("cube_size_in_particle_radii") or 0.75)
    iso_threshold = float(reconstruction_options.get("iso_surface_threshold") or 0.65)
    lower = compiled["workspace_bounds_m"]["min_m"]
    upper = compiled["workspace_bounds_m"]["max_m"]

    gs.init(backend=gs.cpu, logging_level="warning")
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=solver_dt, gravity=tuple(gravity)),
        sph_options=gs.options.SPHOptions(
            dt=solver_dt,
            particle_size=particle_size,
            pressure_solver="WCSPH",
            lower_bound=tuple(lower),
            upper_bound=tuple(upper),
        ),
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
        show_viewer=False,
    )
    container_material = gs.materials.Rigid(
        needs_coup=True,
        coup_friction=0.08,
        coup_softness=0.002,
        gravity_compensation=1.0,
    )
    floor_z = 0.0
    scene.add_entity(
        morph=gs.morphs.Plane(pos=(0.0, 0.0, floor_z), normal=(0.0, 0.0, 1.0)),
        material=container_material,
    )
    source_entity = add_moving_container_collision(scene, gs, container_material, compiled["source"])
    add_container_collision(scene, gs, container_material, compiled["receiver"], fixed=True)
    fluid_spec = compiled["fluid"]
    liquid = scene.add_entity(
        morph=gs.morphs.Cylinder(
            radius=float(fluid_spec["radius_m"]),
            height=float(fluid_spec["height_m"]),
            pos=tuple(fluid_spec["world_position_m"]),
            quat=tuple(fluid_spec["world_quaternion_wxyz"]),
        ),
        material=gs.materials.SPH.Liquid(sampler="regular"),
    )
    scene.build()
    for _ in range(max(0, int(round(pre_roll_s / solver_dt)))):
        set_container_pose(source_entity, compiled["source"], 0.0)
        scene.step()
    set_container_pose(source_entity, compiled["source"], 0.0)
    preflight_positions = tensor_rows(liquid.get_particles_pos())
    preflight_transfer = classify_particles(
        preflight_positions,
        compiled["source"],
        compiled["receiver"],
        particle_size,
    )
    minimum_initial_source = float(expected.get("minimum_initial_source_fraction") or 0.0)
    if float(preflight_transfer["source_fraction"]) < minimum_initial_source:
        centroid = [sum(row[axis] for row in preflight_positions) / len(preflight_positions) for axis in range(3)]
        bounds = {
            "min_m": [min(row[axis] for row in preflight_positions) for axis in range(3)],
            "max_m": [max(row[axis] for row in preflight_positions) for axis in range(3)],
        }
        raise RuntimeError(
            "container pre-roll leaked before capture: "
            f"source_fraction={preflight_transfer['source_fraction']:.6f}, required={minimum_initial_source:.6f}, "
            f"particle_centroid_m={centroid}, particle_bounds_m={bounds}"
        )

    frame_count = max(1, int(round(duration_s * fps)))
    frames: list[dict[str, Any]] = []
    for frame_index in range(frame_count + 1):
        positions = tensor_rows(liquid.get_particles_pos())
        velocities = tensor_rows(liquid.get_particles_vel())
        source_position, solver_rotation, ue_rotation = container_pose_at_time(compiled["source"], frame_index / fps)
        source_at_frame = container_at_pose(compiled["source"], source_position, solver_rotation, ue_rotation)
        transfer_state = classify_particles(
            positions,
            source_at_frame,
            compiled["receiver"],
            particle_size,
        )
        reconstruction_positions = np.asarray(positions, dtype=np.float32)
        reconstruction = pysplashsurf.reconstruct_surface(
            reconstruction_positions,
            particle_radius=particle_size / 2.0,
            smoothing_length=smoothing,
            cube_size=cube_size,
            iso_surface_threshold=iso_threshold,
            aabb_min=np.asarray([lower[0], lower[1], floor_z], dtype=np.float32),
            aabb_max=np.asarray(upper, dtype=np.float32),
        )
        mesh = reconstruction.mesh
        topology_issue = pysplashsurf.check_mesh_consistency(
            mesh,
            reconstruction.grid,
            check_closed=True,
            check_manifold=True,
        )
        surface_vertices = np.asarray(mesh.vertices).copy()
        surface_vertices[:, 2] = np.maximum(surface_vertices[:, 2], floor_z)
        if not len(surface_vertices) or not len(mesh.triangles):
            raise RuntimeError(f"surface reconstruction is empty at frame {frame_index}")
        frames.append(
            {
                "frame": frame_index,
                "time_s": round(frame_index / fps, 8),
                "positions_m": positions,
                "velocities_m_s": velocities,
                "rigid_objects": {
                    str(compiled["source"]["id"]): {
                        "position_m": source_position,
                        "solver_rotation_xyz_deg": solver_rotation,
                        "ue_rotation_pyr_deg": ue_rotation,
                        "kinematic": True,
                    }
                },
                "transfer_state": transfer_state,
                "surface_arrays": {
                    "vertices": surface_vertices,
                    "triangles": mesh.triangles,
                    "topology_consistent": topology_issue is None,
                    "topology_issue": topology_issue,
                    "bounds_m": {
                        "min_m": [float(value) for value in surface_vertices.min(axis=0)],
                        "max_m": [float(value) for value in surface_vertices.max(axis=0)],
                    },
                    "rigid_intersection_vertex_count": 0,
                    **surface_component_metrics(mesh.triangles, len(surface_vertices)),
                    **surface_shape_metrics(surface_vertices, mesh.triangles, np),
                },
            }
        )
        if frame_index < frame_count:
            for substep in range(steps_per_frame):
                current_time = (frame_index + substep / steps_per_frame) / fps
                next_time = (frame_index + (substep + 1) / steps_per_frame) / fps
                set_container_pose(source_entity, compiled["source"], current_time, next_time_s=next_time)
                scene.step()

    particle_count = len(frames[0]["positions_m"])
    initial_volume = math.pi * float(fluid_spec["radius_m"]) ** 2 * float(fluid_spec["height_m"])
    return {
        "schema_version": "harness_particle_cache_v1",
        "backend": "genesis_sph",
        "solver": {
            "genesis_version": str(gs.__version__),
            "backend": "cpu",
            "pressure_solver": "WCSPH",
            "solver_dt_s": solver_dt,
            "gravity_m_s2": list(gravity),
        },
        "timebase": {
            "fps": fps,
            "output_dt_s": round(1.0 / fps, 10),
            "steps_per_output": steps_per_frame,
            "sampling_phase": "state after previous solver steps; frame 0 is initial state",
            "pre_roll_s": pre_roll_s,
        },
        "particles": {
            "count": particle_count,
            "stable_ids": list(range(particle_count)),
            "radius_m": particle_size / 2.0,
            "rest_density_kg_m3": 1000.0,
        },
        "environment": {
            "type": "asset_bound_container_transfer",
            "center_xy_m": [-0.06, 0.0],
            "wall_half_extent_m": 0.36,
            "floor_z_m": floor_z,
            "workspace_bounds_m": compiled["workspace_bounds_m"],
            "penetration_tolerance_m": particle_size,
            "collision_backend": "genesis_rigid_sph_legacy_coupler",
            "collision_representation": "asset_fitted_axisymmetric_profile_panels",
            "source_container": without_parts(compiled["source"]),
            "receiver_container": without_parts(compiled["receiver"]),
            "initial_condition": {
                "type": "bounded_volume",
                "shape": "cylinder",
                "frame": "source_container_local",
                "velocity_field": {"type": "still"},
            },
            "initial_liquid_position_m": fluid_spec["world_position_m"],
            "initial_liquid_volume_m3": initial_volume,
            "minimum_initial_source_fraction": float(expected.get("minimum_initial_source_fraction") or 0.0),
            "minimum_final_receiver_fraction": float(expected.get("minimum_final_receiver_fraction") or 0.0),
            "minimum_source_fraction_decrease": float(expected.get("minimum_source_fraction_decrease") or 0.0),
            "maximum_final_spill_fraction": float(expected.get("maximum_final_spill_fraction") or 1.0),
            "minimum_source_evacuation_duration_s": float(expected.get("minimum_source_evacuation_duration_s") or 0.0),
            "maximum_source_fraction_drop_per_frame": float(expected.get("maximum_source_fraction_drop_per_frame") or 0.0),
            "surface_container_intersection_metric": "not_applied_for_boundary_contacting_fluid",
            "minimum_splash_rise_m": 0.0,
            "minimum_float_sink_separation_m": 0.0,
            "minimum_initial_flow_speed_m_s": 0.0,
            "minimum_horizontal_displacement_m": 0.0,
            "minimum_jet_rise_m": 0.0,
            "minimum_final_surface_component_fraction": 0.0,
            "maximum_final_surface_area_to_volume_ratio_1_m": 0.0,
            "maximum_final_surface_volume_relative_error": 0.0,
            "rigid_objects": [],
        },
        "coupling": {
            "processor": "pysplashsurf",
            "processor_version": "0.14.1.0",
            "smoothing_length_in_particle_radii": smoothing,
            "cube_size_in_particle_radii": cube_size,
            "iso_surface_threshold": iso_threshold,
            "surface_boundary_projection": "floor_only; no x/y container clipping",
            "representation": "per-frame OBJ surface mesh",
            "ue_next_step": "replay surface and identical asset-bound container transforms",
        },
        "frames": frames,
    }


def add_container_collision(
    scene: Any,
    gs: Any,
    material: Any,
    container: dict[str, Any],
    *,
    fixed: bool,
) -> list[Any]:
    entities = []
    for part in container["collision"]["parts"]:
        if part["kind"] == "box":
            morph = gs.morphs.Box(
                size=tuple(part["size_m"]),
                pos=tuple(part["position_m"]),
                quat=tuple(part["quaternion_wxyz"]),
                fixed=fixed,
                visualization=False,
            )
        else:
            morph = gs.morphs.Cylinder(
                radius=float(part["radius_m"]),
                height=float(part["height_m"]),
                pos=tuple(part["position_m"]),
                quat=tuple(part["quaternion_wxyz"]),
                fixed=fixed,
                visualization=False,
            )
        entities.append(scene.add_entity(morph=morph, material=material))
    return entities


def add_moving_container_collision(scene: Any, gs: Any, material: Any, container: dict[str, Any]) -> Any:
    collision = container["collision"]
    parts = profile_collision_parts(
        [0.0, 0.0, 0.0],
        rotation_matrix_xyz([0.0, 0.0, 0.0]),
        collision["inner_profile"],
        float(collision["wall_thickness_m"]),
        int(collision["panel_count"]),
    )
    geoms = []
    for part in parts:
        pos = " ".join(str(value) for value in part["position_m"])
        quat = " ".join(str(value) for value in part["quaternion_wxyz"])
        if part["kind"] == "box":
            size = " ".join(str(float(value) / 2.0) for value in part["size_m"])
            geoms.append(f'<geom type="box" pos="{pos}" quat="{quat}" size="{size}"/>')
        else:
            size = f'{part["radius_m"]} {float(part["height_m"]) / 2.0}'
            geoms.append(f'<geom type="cylinder" pos="{pos}" quat="{quat}" size="{size}"/>')
    body_pos = " ".join(str(value) for value in container["transform"]["position_m"])
    body_quat = " ".join(str(value) for value in quaternion_from_matrix(rotation_matrix_xyz(container["transform"]["euler_xyz_deg"])))
    xml = (
        '<mujoco model="container"><worldbody>'
        f'<body name="container" pos="{body_pos}" quat="{body_quat}">'
        '<freejoint/><inertial pos="0 0 0" mass="1" diaginertia="0.01 0.01 0.01"/>'
        + "".join(geoms)
        + "</body></worldbody></mujoco>"
    )
    return scene.add_entity(
        morph=gs.morphs.MJCF(file=xml, visualization=False, requires_jac_and_IK=False),
        material=material,
    )


def set_container_pose(
    entity: Any,
    container: dict[str, Any],
    time_s: float,
    *,
    next_time_s: float | None = None,
) -> None:
    position, solver_rotation, _ue_rotation = container_pose_at_time(container, time_s)
    linear_velocity = [0.0, 0.0, 0.0]
    angular_velocity = [0.0, 0.0, 0.0]
    if next_time_s is not None:
        dt = float(next_time_s) - float(time_s)
        if dt <= 0.0:
            raise ValueError("container pose next_time_s must be greater than time_s")
        next_position, next_rotation, _next_ue_rotation = container_pose_at_time(container, next_time_s)
        linear_velocity = [(after - before) / dt for before, after in zip(position, next_position, strict=True)]
        angular_velocity = [math.radians(after - before) / dt for before, after in zip(solver_rotation, next_rotation, strict=True)]
    entity.set_pos(
        tuple(position),
        zero_velocity=True,
        relative=False,
        skip_forward=True,
    )
    entity.set_quat(
        tuple(quaternion_from_matrix(rotation_matrix_xyz(solver_rotation))),
        zero_velocity=True,
        relative=False,
        skip_forward=True,
    )
    entity.set_dofs_velocity((*linear_velocity, *angular_velocity), skip_forward=False)


def container_pose_at_time(container: dict[str, Any], time_s: float) -> tuple[list[float], list[float], list[float]]:
    solver_rotation, ue_rotation = container_rotations_at_time(container, time_s)
    motion = container.get("kinematic_motion")
    if not isinstance(motion, dict):
        return list(container["transform"]["position_m"]), solver_rotation, ue_rotation
    position = subtract(
        motion["pivot_world_m"],
        matrix_vector(rotation_matrix_xyz(solver_rotation), motion["pivot_local_m"]),
    )
    return position, solver_rotation, ue_rotation


def container_rotations_at_time(container: dict[str, Any], time_s: float) -> tuple[list[float], list[float]]:
    transform = container["transform"]
    motion = container.get("kinematic_motion")
    solver_start = list(transform["euler_xyz_deg"])
    ue_start = list(transform["ue_rotation_pyr_deg"])
    if not isinstance(motion, dict):
        return solver_start, ue_start
    duration = float(motion["duration_s"])
    fraction = max(0.0, min(1.0, (float(time_s) - float(motion["start_time_s"])) / duration))
    fraction = fraction * fraction * (3.0 - 2.0 * fraction)
    return (
        interpolate_rotation(solver_start, motion["solver_end_rotation_xyz_deg"], fraction),
        interpolate_rotation(ue_start, motion["ue_end_rotation_pyr_deg"], fraction),
    )


def interpolate_rotation(start: list[float], end: list[float], fraction: float) -> list[float]:
    return [float(start[index]) + (float(end[index]) - float(start[index])) * fraction for index in range(3)]


def container_at_pose(
    container: dict[str, Any],
    position: list[float],
    solver_rotation: list[float],
    ue_rotation: list[float],
) -> dict[str, Any]:
    return {
        **container,
        "transform": {
            **container["transform"],
            "position_m": list(position),
            "euler_xyz_deg": list(solver_rotation),
            "ue_rotation_pyr_deg": list(ue_rotation),
        },
    }


def classify_particles(
    positions: list[list[float]],
    source: dict[str, Any],
    receiver: dict[str, Any],
    particle_size: float,
) -> dict[str, Any]:
    source_count = sum(point_inside_profile(row, source) for row in positions)
    receiver_count = sum(point_inside_profile(row, receiver) for row in positions)
    total = max(1, len(positions))
    outside = max(0, len(positions) - source_count - receiver_count)
    return {
        "source_particle_count": source_count,
        "receiver_particle_count": receiver_count,
        "outside_both_particle_count": outside,
        "source_fraction": source_count / total,
        "receiver_fraction": receiver_count / total,
        "outside_both_fraction": outside / total,
    }


def without_parts(container: dict[str, Any]) -> dict[str, Any]:
    collision = dict(container["collision"])
    collision.pop("parts", None)
    return {**container, "collision": collision}


def wake_macos_display() -> None:
    """Genesis' offscreen rasterizer still needs a Cocoa screen on macOS."""
    caffeinate = shutil.which("caffeinate")
    if sys.platform == "darwin" and caffeinate:
        subprocess.run([caffeinate, "-u", "-t", "2"], check=False, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an asset-bound Genesis container transfer and export canonical particle/surface truth.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--skip-publish", action="store_true")
    args = parser.parse_args()
    case = load_case_spec(args.case)
    output_dir = workspace_path(args.output_dir, default_relative="runs/fluid/container_transfer")
    compiled = compile_container_transfer(case.data)
    (output_dir / "container_transfer_compilation.json").parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "container_transfer_compilation.json").write_text(
        json.dumps(compiled, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    report = write_fluid_cache(simulate_container_transfer(case.data), output_dir)
    print(json.dumps({"status": report["status"], "output_dir": str(output_dir), **report["checks"]}, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
