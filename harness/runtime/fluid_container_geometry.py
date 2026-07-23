from __future__ import annotations

import math
from typing import Any


def compile_container_transfer(case_spec: dict[str, Any]) -> dict[str, Any]:
    """Compile one asset-bound source/receiver pair into solver collision parts."""
    objects = [item for item in case_spec.get("objects") or [] if isinstance(item, dict)]
    source = exactly_one(objects, "source_container")
    receiver = exactly_one(objects, "receiver_container")
    fluid = exactly_one_of(objects, {"fluid", "fluid_volume"})
    source_compiled = compile_container(source)
    receiver_compiled = compile_container(receiver)
    initial = fluid.get("initial_condition") if isinstance(fluid.get("initial_condition"), dict) else {}
    if initial.get("frame") != "source_container_local":
        raise ValueError("container transfer fluid must use source_container_local initial frame")
    if str(initial.get("shape") or "") != "cylinder":
        raise ValueError("container transfer vertical slice requires a cylindrical initial liquid volume")
    local_position = vec3(initial.get("local_position_m"), "fluid local_position_m")
    source_rotation = rotation_matrix_xyz(source_compiled["transform"]["euler_xyz_deg"])
    world_position = add(
        source_compiled["transform"]["position_m"],
        matrix_vector(source_rotation, local_position),
    )
    pour_alignment = compile_pour_alignment(
        source_compiled,
        receiver_compiled,
    )
    workspace = case_spec.get("workspace_bounds_m")
    if not isinstance(workspace, dict):
        raise ValueError("container transfer requires workspace_bounds_m")
    minimum = vec3(workspace.get("min_m"), "workspace_bounds_m.min_m")
    maximum = vec3(workspace.get("max_m"), "workspace_bounds_m.max_m")
    if any(minimum[index] >= maximum[index] for index in range(3)):
        raise ValueError("workspace bounds must have min < max on every axis")
    return {
        "schema_version": "harness_container_transfer_compilation_v1",
        "solver_mode": "container_transfer",
        "source": source_compiled,
        "receiver": receiver_compiled,
        "fluid": {
            "id": str(fluid.get("id") or "fluid"),
            "shape": "cylinder",
            "radius_m": positive(initial.get("radius_m"), "fluid radius_m"),
            "height_m": positive(initial.get("height_m"), "fluid height_m"),
            "world_position_m": world_position,
            "world_quaternion_wxyz": quaternion_from_matrix(source_rotation),
            "initial_velocity_m_s": [0.0, 0.0, 0.0],
        },
        "pour_alignment": pour_alignment,
        "workspace_bounds_m": {"min_m": minimum, "max_m": maximum},
    }


def compile_pour_alignment(
    source: dict[str, Any],
    receiver: dict[str, Any],
) -> dict[str, Any]:
    """Reject a zero-velocity kinematic pour whose pivot drop line misses the receiver."""
    motion = source.get("kinematic_motion")
    if not isinstance(motion, dict):
        raise ValueError("container transfer source requires kinematic tilt motion")
    estimated_drop = motion["expected_stream_landing_xy_m"]
    receiver_center = receiver["transform"]["position_m"]
    xy_distance = math.hypot(
        estimated_drop[0] - receiver_center[0],
        estimated_drop[1] - receiver_center[1],
    )
    capture_radius = float(receiver["collision"]["inner_rim_radius_m"])
    if xy_distance > capture_radius:
        raise ValueError(
            "container transfer gravity-only drop line misses receiver: "
            f"xy_distance_m={xy_distance:.6f}, capture_radius_m={capture_radius:.6f}"
        )
    return {
        "method": "solver_probe_stream_landing_v3",
        "estimated_drop_xy_m": estimated_drop[:2],
        "receiver_center_xy_m": receiver_center[:2],
        "xy_distance_m": xy_distance,
        "capture_radius_m": capture_radius,
        "pass": True,
    }


def compile_container(container: dict[str, Any]) -> dict[str, Any]:
    asset = container.get("asset") if isinstance(container.get("asset"), dict) else {}
    collision = container.get("collision") if isinstance(container.get("collision"), dict) else {}
    ue_path = str(asset.get("ue_path") or "")
    asset_hash = str(asset.get("sha256") or "")
    if not ue_path.startswith("/Game/") or "." not in ue_path:
        raise ValueError("container asset must declare a full /Game UE object path")
    if len(asset_hash) != 64 or any(character not in "0123456789abcdef" for character in asset_hash.lower()):
        raise ValueError("container asset sha256 must be a 64-character hex digest")
    if asset.get("proxy") is not False:
        raise ValueError("container transfer requires non-proxy UE assets")
    if collision.get("type") != "axisymmetric_profile":
        raise ValueError("container collision must use axisymmetric_profile")
    if collision.get("asset_geometry_match") is not True:
        raise ValueError("container collision must be explicitly fitted to the render asset")
    panel_count = int(collision.get("panel_count") or 0)
    if panel_count < 12:
        raise ValueError("container profile requires at least 12 wall panels")
    profile = compile_inner_profile(collision.get("inner_profile"))
    bottom_z = profile[0]["z_m"]
    bottom_radius = profile[0]["radius_m"]
    rim_z = profile[-1]["z_m"]
    rim_radius = profile[-1]["radius_m"]
    thickness = positive(collision.get("wall_thickness_m"), "wall_thickness_m")
    if rim_z <= bottom_z:
        raise ValueError("container rim must be above its inner bottom")
    transform = {
        "position_m": vec3(container.get("initial_position_m"), "container initial_position_m"),
        "euler_xyz_deg": vec3(container.get("solver_rotation_xyz_deg"), "container solver_rotation_xyz_deg"),
        "ue_rotation_pyr_deg": vec3(container.get("ue_rotation_pyr_deg"), "container ue_rotation_pyr_deg"),
    }
    rotation = rotation_matrix_xyz(transform["euler_xyz_deg"])
    parts = profile_collision_parts(
        transform["position_m"],
        rotation,
        profile,
        thickness,
        panel_count,
    )
    motion = container.get("kinematic_motion") if isinstance(container.get("kinematic_motion"), dict) else None
    compiled_motion = None
    if motion is not None:
        if motion.get("type") != "tilt":
            raise ValueError("container kinematic motion must be tilt")
        compiled_motion = {
            "type": "tilt",
            "start_time_s": finite(motion.get("start_time_s"), "container tilt start_time_s"),
            "duration_s": positive(motion.get("duration_s"), "container tilt duration_s"),
            "pivot_local_m": vec3(motion.get("pivot_local_m"), "container tilt pivot_local_m"),
            "expected_stream_landing_xy_m": vec2(
                motion.get("expected_stream_landing_xy_m"),
                "container tilt expected_stream_landing_xy_m",
            ),
            "solver_start_rotation_xyz_deg": list(transform["euler_xyz_deg"]),
            "solver_end_rotation_xyz_deg": vec3(motion.get("solver_end_rotation_xyz_deg"), "container tilt solver end rotation"),
            "ue_start_rotation_pyr_deg": list(transform["ue_rotation_pyr_deg"]),
            "ue_end_rotation_pyr_deg": vec3(motion.get("ue_end_rotation_pyr_deg"), "container tilt UE end rotation"),
        }
        compiled_motion["pivot_world_m"] = add(
            transform["position_m"],
            matrix_vector(rotation, compiled_motion["pivot_local_m"]),
        )
    return {
        "id": str(container.get("id") or ""),
        "role": str(container.get("role") or ""),
        "asset": {
            "ue_path": ue_path,
            "material_path": str(asset.get("material_path") or ""),
            "sha256": asset_hash.lower(),
            "proxy": False,
            "catalog_source": str(asset.get("catalog_source") or ""),
            "bbox_m": vec3(asset.get("bbox_m"), "container asset bbox_m"),
        },
        "transform": transform,
        "kinematic_motion": compiled_motion,
        "collision": {
            "type": "axisymmetric_profile",
            "asset_geometry_match": True,
            "fit_method": str(collision.get("fit_method") or ""),
            "inner_bottom_radius_m": bottom_radius,
            "inner_rim_radius_m": rim_radius,
            "inner_bottom_z_m": bottom_z,
            "inner_rim_z_m": rim_z,
            "inner_profile": profile,
            "wall_thickness_m": thickness,
            "panel_count": panel_count,
            "parts": parts,
        },
    }


def compile_inner_profile(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("container collision requires at least two inner_profile points")
    profile: list[dict[str, float]] = []
    for point in value:
        if not isinstance(point, dict):
            raise ValueError("container inner_profile points must be objects")
        z_m = finite(point.get("z_m"), "inner_profile z_m")
        radius_m = positive(point.get("radius_m"), "inner_profile radius_m")
        if profile and z_m <= profile[-1]["z_m"]:
            raise ValueError("container inner_profile z_m values must be strictly increasing")
        profile.append({"z_m": z_m, "radius_m": radius_m})
    return profile


def profile_collision_parts(
    base_position: list[float],
    rotation: list[list[float]],
    profile: list[dict[str, float]],
    thickness: float,
    panel_count: int,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for lower, upper in zip(profile, profile[1:]):
        segment = frustum_collision_parts(
            base_position,
            rotation,
            lower["radius_m"],
            upper["radius_m"],
            lower["z_m"],
            upper["z_m"],
            thickness,
            panel_count,
        )
        parts.extend(segment[:panel_count])
    bottom = profile[0]
    bottom_position = add(
        base_position,
        matrix_vector(rotation, [0.0, 0.0, bottom["z_m"] - thickness / 2.0]),
    )
    parts.append(
        {
            "kind": "cylinder",
            "position_m": bottom_position,
            "quaternion_wxyz": quaternion_from_matrix(rotation),
            "radius_m": bottom["radius_m"] + thickness * 1.5,
            "height_m": thickness,
        }
    )
    return parts


def frustum_collision_parts(
    base_position: list[float],
    rotation: list[list[float]],
    bottom_radius: float,
    rim_radius: float,
    bottom_z: float,
    rim_z: float,
    thickness: float,
    panel_count: int,
) -> list[dict[str, Any]]:
    height = rim_z - bottom_z
    radial_delta = rim_radius - bottom_radius
    slant = math.hypot(height, radial_delta)
    middle_radius = (bottom_radius + rim_radius) / 2.0
    parts: list[dict[str, Any]] = []
    for index in range(panel_count):
        angle = 2.0 * math.pi * index / panel_count
        tangent = [-math.sin(angle), math.cos(angle), 0.0]
        local_z = [radial_delta * math.cos(angle) / slant, radial_delta * math.sin(angle) / slant, height / slant]
        local_y = normalize(cross(local_z, tangent))
        local_rotation = columns(tangent, local_y, local_z)
        world_rotation = matrix_multiply(rotation, local_rotation)
        local_center = [middle_radius * math.cos(angle), middle_radius * math.sin(angle), (bottom_z + rim_z) / 2.0]
        world_center = add(base_position, matrix_vector(rotation, local_center))
        parts.append(
            {
                "kind": "box",
                "position_m": world_center,
                "quaternion_wxyz": quaternion_from_matrix(world_rotation),
                "size_m": [2.0 * math.pi * max(bottom_radius, rim_radius) / panel_count * 1.25, thickness, slant * 1.03],
            }
        )
    bottom_position = add(base_position, matrix_vector(rotation, [0.0, 0.0, bottom_z - thickness / 2.0]))
    parts.append(
        {
            "kind": "cylinder",
            "position_m": bottom_position,
            "quaternion_wxyz": quaternion_from_matrix(rotation),
            "radius_m": bottom_radius + thickness * 1.5,
            "height_m": thickness,
        }
    )
    return parts


def point_inside_profile(point: list[float], container: dict[str, Any], *, radial_margin_m: float = 0.0) -> bool:
    transform = container["transform"]
    rotation = rotation_matrix_xyz(transform["euler_xyz_deg"])
    local = matrix_vector(transpose(rotation), subtract(point, transform["position_m"]))
    collision = container["collision"]
    profile = collision["inner_profile"]
    bottom_z = float(profile[0]["z_m"])
    rim_z = float(profile[-1]["z_m"])
    if local[2] < bottom_z or local[2] > rim_z:
        return False
    lower, upper = next(
        (lower, upper)
        for lower, upper in zip(profile, profile[1:])
        if float(lower["z_m"]) <= local[2] <= float(upper["z_m"])
    )
    fraction = (local[2] - float(lower["z_m"])) / (float(upper["z_m"]) - float(lower["z_m"]))
    radius = float(lower["radius_m"]) + fraction * (float(upper["radius_m"]) - float(lower["radius_m"]))
    return math.hypot(local[0], local[1]) <= max(0.0, radius - radial_margin_m)


def exactly_one(objects: list[dict[str, Any]], role: str) -> dict[str, Any]:
    matches = [item for item in objects if str(item.get("role") or "") == role]
    if len(matches) != 1:
        raise ValueError(f"container transfer requires exactly one {role}")
    return matches[0]


def exactly_one_of(objects: list[dict[str, Any]], roles: set[str]) -> dict[str, Any]:
    matches = [item for item in objects if str(item.get("role") or "") in roles]
    if len(matches) != 1:
        raise ValueError("container transfer requires exactly one fluid")
    return matches[0]


def rotation_matrix_xyz(euler_deg: list[float]) -> list[list[float]]:
    x, y, z = [math.radians(float(value)) for value in euler_deg]
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy, cy * sx, cy * cx],
    ]


def quaternion_from_matrix(matrix: list[list[float]]) -> list[float]:
    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        values = [0.25 * scale, (matrix[2][1] - matrix[1][2]) / scale, (matrix[0][2] - matrix[2][0]) / scale, (matrix[1][0] - matrix[0][1]) / scale]
    elif matrix[0][0] > matrix[1][1] and matrix[0][0] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2.0
        values = [(matrix[2][1] - matrix[1][2]) / scale, 0.25 * scale, (matrix[0][1] + matrix[1][0]) / scale, (matrix[0][2] + matrix[2][0]) / scale]
    elif matrix[1][1] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2.0
        values = [(matrix[0][2] - matrix[2][0]) / scale, (matrix[0][1] + matrix[1][0]) / scale, 0.25 * scale, (matrix[1][2] + matrix[2][1]) / scale]
    else:
        scale = math.sqrt(1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2.0
        values = [(matrix[1][0] - matrix[0][1]) / scale, (matrix[0][2] + matrix[2][0]) / scale, (matrix[1][2] + matrix[2][1]) / scale, 0.25 * scale]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def matrix_multiply(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [[sum(left[row][axis] * right[axis][column] for axis in range(3)) for column in range(3)] for row in range(3)]


def matrix_vector(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(matrix[row][axis] * vector[axis] for axis in range(3)) for row in range(3)]


def transpose(matrix: list[list[float]]) -> list[list[float]]:
    return [[matrix[column][row] for column in range(3)] for row in range(3)]


def columns(first: list[float], second: list[float], third: list[float]) -> list[list[float]]:
    return [[first[row], second[row], third[row]] for row in range(3)]


def cross(left: list[float], right: list[float]) -> list[float]:
    return [left[1] * right[2] - left[2] * right[1], left[2] * right[0] - left[0] * right[2], left[0] * right[1] - left[1] * right[0]]


def normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vector))
    return [value / length for value in vector]


def add(left: list[float], right: list[float]) -> list[float]:
    return [float(left[index]) + float(right[index]) for index in range(3)]


def subtract(left: list[float], right: list[float]) -> list[float]:
    return [float(left[index]) - float(right[index]) for index in range(3)]


def vec3(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must be a finite 3-vector")
    return [finite(item, name) for item in value]


def vec2(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be a finite 2-vector")
    return [finite(item, name) for item in value]


def positive(value: Any, name: str) -> float:
    number = finite(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be positive")
    return number


def finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number
