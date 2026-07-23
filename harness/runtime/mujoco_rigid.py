from __future__ import annotations

import math
from typing import Any
from xml.sax.saxutils import quoteattr

import numpy as np

from harness.core.capability import canonical_capability_id


SUPPORTED_CAPABILITIES = {
    "constraint_momentum_transfer",
    "ramp_sliding_friction",
    "rigid_body_gravity_collision",
    "rigid_body_contact_causality",
    "elastic_constraint_rebound",
    "magnetic_force_field",
}


def simulate_rigid_case(
    case_spec: dict[str, Any],
    actor_placement: dict[str, Any],
    *,
    fps: int,
    duration_s: float,
) -> list[dict[str, Any]] | None:
    capability_id = canonical_capability_id(str(case_spec.get("capability_id") or ""))
    if capability_id not in SUPPORTED_CAPABILITIES:
        return None
    try:
        import mujoco
    except ImportError as exc:  # pragma: no cover - environment failure, exercised by UE preflight.
        raise RuntimeError("MuJoCo rigid simulation requires `python -m pip install mujoco==3.10.0`.") from exc

    if capability_id == "elastic_constraint_rebound":
        return _simulate_elastic_constraint_case(case_spec, fps=fps, duration_s=duration_s, mujoco=mujoco)
    if capability_id == "constraint_momentum_transfer":
        return _simulate_impulse_chain_case(case_spec, fps=fps, duration_s=duration_s, mujoco=mujoco)
    if capability_id == "magnetic_force_field":
        return _simulate_magnetic_case(case_spec, fps=fps, duration_s=duration_s, mujoco=mujoco)
    if capability_id == "ramp_sliding_friction":
        return _simulate_ramp_friction_case(case_spec, fps=fps, duration_s=duration_s, mujoco=mujoco)

    bindings = [item for item in actor_placement.get("actor_bindings") or [] if isinstance(item, dict)]
    if not bindings:
        raise RuntimeError("MuJoCo rigid simulation requires runtime actor placement bindings.")
    objects = {str(item.get("id")): item for item in case_spec.get("objects") or [] if isinstance(item, dict)}
    dynamic = [item for item in bindings if bool((item.get("physics") or {}).get("simulate_physics"))]
    gravity = _gravity(case_spec)
    xml = _mjcf(bindings, gravity)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)

    for binding in dynamic:
        object_id = str(binding["object_id"])
        object_spec = objects.get(object_id) or {}
        velocity = object_spec.get("initial_velocity_m_s") or [0.0, 0.0, 0.0]
        angular_velocity = object_spec.get("initial_angular_velocity_rad_s") or [0.0, 0.0, 0.0]
        joint_id = int(model.body(object_id).jntadr[0])
        qvel_adr = int(model.jnt_dofadr[joint_id])
        data.qvel[qvel_adr : qvel_adr + 3] = [float(value) for value in velocity[:3]]
        data.qvel[qvel_adr + 3 : qvel_adr + 6] = [float(value) for value in angular_velocity[:3]]
        linear_damping = max(0.0, float(object_spec.get("linear_damping") or 0.0))
        angular_damping = max(0.0, float(object_spec.get("angular_damping") or 0.0))
        model.dof_damping[qvel_adr : qvel_adr + 3] = linear_damping
        model.dof_damping[qvel_adr + 3 : qvel_adr + 6] = angular_damping

    solver_state = _solver_state(mujoco, model, bindings)
    mujoco.mj_forward(model, data)
    frame_count = max(1, int(round(duration_s * fps)))
    steps_per_frame = max(1, int(round((1.0 / fps) / model.opt.timestep)))
    frames = [_frame(model, data, dynamic, 0, fps, solver_state)]
    for frame_index in range(1, frame_count + 1):
        substep_contacts: dict[tuple[str, str], dict[str, Any]] = {}
        for _ in range(steps_per_frame):
            mujoco.mj_step(model, data)
            for contact in _contacts(model, data, frame_index, fps):
                substep_contacts[tuple(contact["objects"])] = contact
        frames.append(_frame(model, data, dynamic, frame_index, fps, solver_state, list(substep_contacts.values())))
    return frames


def _simulate_elastic_constraint_case(
    case_spec: dict[str, Any],
    *,
    fps: int,
    duration_s: float,
    mujoco: Any,
) -> list[dict[str, Any]]:
    expected = case_spec.get("expected_physics") if isinstance(case_spec.get("expected_physics"), dict) else {}
    objects = {str(item.get("id")): item for item in case_spec.get("objects") or [] if isinstance(item, dict)}
    anchor_id = str(expected.get("anchor_object_id") or "anchor")
    body_id = str(expected.get("constrained_object_id") or "payload")
    anchor = objects.get(anchor_id) or {}
    body = objects.get(body_id) or {}
    anchor_position = _object_position(anchor, [0.0, 0.0, 2.0])
    body_position = _object_position(body, [0.0, 0.0, 1.0])
    rest_length = max(0.001, float(expected.get("rest_length_m") or 1.2))
    max_extension = max(0.001, float(expected.get("max_extension_m") or 0.42))
    stiffness = max(0.001, float(expected.get("constraint_stiffness_n_m") or 45.0))
    mass = max(0.001, float(body.get("mass_kg") or 0.8))
    damping_ratio = max(0.0, float(expected.get("damping_ratio") or 0.22))
    damping = 2.0 * damping_ratio * math.sqrt(stiffness * mass)
    radius = max(0.001, float(body.get("radius_m") or 0.12))
    max_length = rest_length + max_extension
    gravity = _gravity(case_spec)
    xml = (
        f'<mujoco><option timestep="0.0041666667" gravity="{_vec(gravity)}"/>'
        '<worldbody>'
        f'<site name="anchor_site" pos="{_vec(anchor_position)}" size="0.02"/>'
        f'<body name={quoteattr(body_id)} pos="{_vec(body_position)}"><freejoint/>'
        f'<geom name={quoteattr(body_id)} type="sphere" size="{radius}" mass="{mass}"/>'
        '<site name="payload_site" pos="0 0 0" size="0.01"/>'
        '</body></worldbody>'
        '<tendon>'
        f'<spatial name="elastic_tether" stiffness="{stiffness}" damping="{damping}" '
        f'springlength="0 {rest_length}" limited="true" range="0 {max_length}">'
        '<site site="anchor_site"/><site site="payload_site"/>'
        '</spatial></tendon></mujoco>'
    )
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    body_model = model.body(body_id)
    joint_id = int(body_model.jntadr[0])
    qvel_adr = int(model.jnt_dofadr[joint_id])
    initial_velocity = list(body.get("initial_velocity_m_s") or [0.0, 0.0, 0.0])
    initial_angular_velocity = list(body.get("initial_angular_velocity_rad_s") or [0.0, 0.0, 0.0])
    data.qvel[qvel_adr : qvel_adr + 3] = [float(value) for value in initial_velocity[:3]]
    data.qvel[qvel_adr + 3 : qvel_adr + 6] = [float(value) for value in initial_angular_velocity[:3]]
    mujoco.mj_forward(model, data)

    solver_state = {
        "backend": "mujoco_rigid",
        "model": "spatial_tendon_spring_damper",
        "version": str(getattr(mujoco, "__version__", "unknown")),
        "timestep_s": round(float(model.opt.timestep), 10),
        "gravity_m_s2": [round(float(value), 8) for value in model.opt.gravity],
        "constraint": {
            "constraint_id": "elastic_tether",
            "anchor_id": anchor_id,
            "body_id": body_id,
            "rest_length_m": rest_length,
            "max_extension_m": max_extension,
            "stiffness_n_m": stiffness,
            "damping_n_s_m": round(damping, 8),
            "damping_ratio": damping_ratio,
        },
        "objects": {
            anchor_id: {"simulate_physics": False, "kinematic": True, "mass_kg": 0.0},
            body_id: {
                "simulate_physics": True,
                "mass_kg": round(float(model.body_mass[int(body_model.id)]), 8),
                "inertia_diagonal_kg_m2": [round(float(value), 8) for value in model.body_inertia[int(body_model.id)]],
            },
        },
    }
    tendon_id = int(model.tendon("elastic_tether").id)
    frame_count = max(1, int(round(duration_s * fps)))
    steps_per_frame = max(1, int(round((1.0 / fps) / model.opt.timestep)))

    def frame(frame_index: int) -> dict[str, Any]:
        payload = data.body(body_id)
        payload_position = [round(float(value), 6) for value in payload.xpos]
        measured_distance = float(data.ten_length[tendon_id])
        extension = max(0.0, measured_distance - rest_length)
        time_s = round(frame_index / fps, 6)
        return {
            "frame": frame_index,
            "time": time_s,
            "source": "mujoco_rigid",
            "objects": {
                anchor_id: {
                    "position": [round(value, 6) for value in anchor_position],
                    "rotation_degrees": [0.0, 0.0, 0.0],
                    "velocity_m_s": [0.0, 0.0, 0.0],
                    "angular_velocity_rad_s": [0.0, 0.0, 0.0],
                    "source": "mujoco_rigid",
                },
                body_id: {
                    "position": payload_position,
                    "rotation_degrees": _quat_to_degrees(payload.xquat),
                    "velocity_m_s": [round(float(value), 6) for value in data.qvel[qvel_adr : qvel_adr + 3]],
                    "angular_velocity_rad_s": [round(float(value), 6) for value in data.qvel[qvel_adr + 3 : qvel_adr + 6]],
                    "source": "mujoco_rigid",
                },
            },
            "contacts": [],
            "constraints": [
                {
                    "frame": frame_index,
                    "time": time_s,
                    "constraint_id": "elastic_tether",
                    "constraint_type": "elastic_tether",
                    "anchor_id": anchor_id,
                    "body_id": body_id,
                    "rest_length_m": round(rest_length, 6),
                    "measured_distance_m": round(measured_distance, 6),
                    "extension_m": round(extension, 6),
                    "source": "mujoco_spatial_tendon",
                }
            ],
            "solver_state": solver_state,
        }

    frames = [frame(0)]
    for frame_index in range(1, frame_count + 1):
        for _ in range(steps_per_frame):
            mujoco.mj_step(model, data)
        frames.append(frame(frame_index))
    return frames


def _simulate_magnetic_case(
    case_spec: dict[str, Any],
    *,
    fps: int,
    duration_s: float,
    mujoco: Any,
) -> list[dict[str, Any]]:
    expected = case_spec.get("expected_physics") if isinstance(case_spec.get("expected_physics"), dict) else {}
    objects = {str(item.get("id")): item for item in case_spec.get("objects") or [] if isinstance(item, dict)}
    source_id = str(expected.get("source_object_id") or "magnet_source")
    body_id = str(expected.get("magnetic_subject_id") or "magnetic_body")
    source = objects.get(source_id) or {}
    body = objects.get(body_id) or {}
    mode = str(expected.get("magnetic_mode") or "").casefold()
    if mode not in {"attract", "repel"}:
        raise ValueError("magnetic_mode must be attract or repel")
    source_position = _object_position(source, [0.0, 0.0, 0.14])
    body_position = _object_position(body, [0.6, 0.0, 0.14])
    if abs(source_position[1] - body_position[1]) > 1e-6 or abs(source_position[2] - body_position[2]) > 1e-6:
        raise ValueError("v001 magnetic force adapter requires source and subject on the same x-axis")
    raw_source_radius = float(source.get("radius_m") or 0.09)
    raw_body_radius = float(body.get("radius_m") or 0.08)
    raw_mass = float(body.get("mass_kg") or 0.2)
    raw_strength = float(expected.get("magnetic_strength") or 0.0)
    raw_softening = float(expected.get("field_softening_m") or 0.12)
    raw_field_range = float(expected.get("field_range_m") or 1.15)
    raw_maximum_force = float(expected.get("maximum_force_n") or 0.8)
    raw_damping = float(expected.get("magnetic_damping_n_s_m") or 0.35)
    numeric_inputs = [*source_position, *body_position, raw_source_radius, raw_body_radius, raw_mass, raw_strength, raw_softening, raw_field_range, raw_maximum_force, raw_damping]
    if not all(math.isfinite(value) for value in numeric_inputs):
        raise ValueError("magnetic force inputs must be finite")
    if raw_strength <= 0.0:
        raise ValueError("magnetic_strength must be positive; magnetic_mode controls direction")
    source_radius = max(0.001, raw_source_radius)
    body_radius = max(0.001, raw_body_radius)
    mass = max(0.001, raw_mass)
    strength = raw_strength
    softening = max(0.001, raw_softening)
    field_range = max(source_radius + body_radius, raw_field_range)
    maximum_force = max(1e-9, raw_maximum_force)
    damping = max(0.0, raw_damping)
    xml = (
        '<mujoco><option timestep="0.0041666667" gravity="0 0 0"/>'
        '<worldbody>'
        f'<geom name={quoteattr(source_id)} type="sphere" size="{source_radius}" pos="{_vec(source_position)}"/>'
        f'<body name={quoteattr(body_id)} pos="{_vec(body_position)}">'
        f'<joint name="magnetic_slide" type="slide" axis="1 0 0" damping="{damping}"/>'
        f'<geom name={quoteattr(body_id)} type="sphere" size="{body_radius}" mass="{mass}"/>'
        '</body></worldbody></mujoco>'
    )
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    joint = model.joint("magnetic_slide")
    dof_adr = int(model.jnt_dofadr[int(joint.id)])
    initial_velocity = list(body.get("initial_velocity_m_s") or [0.0, 0.0, 0.0])
    data.qvel[dof_adr] = float(initial_velocity[0])
    mujoco.mj_forward(model, data)

    solver_state = {
        "backend": "mujoco_rigid",
        "model": "finite_range_softened_inverse_square",
        "version": str(getattr(mujoco, "__version__", "unknown")),
        "timestep_s": round(float(model.opt.timestep), 10),
        "source_object_id": source_id,
        "subject_object_id": body_id,
        "magnetic_mode": mode,
        "magnetic_strength_n_m2": strength,
        "field_softening_m": softening,
        "field_range_m": field_range,
        "maximum_force_n": maximum_force,
        "damping_n_s_m": damping,
        "objects": {
            source_id: {"simulate_physics": False, "kinematic": True, "mass_kg": 0.0},
            body_id: {"simulate_physics": True, "kinematic": False, "mass_kg": mass},
        },
    }

    def magnetic_force() -> tuple[float, float, float]:
        body_x = float(data.body(body_id).xpos[0])
        delta_x = source_position[0] - body_x
        distance = abs(delta_x)
        taper = max(0.0, 1.0 - distance / field_range)
        magnitude = min(maximum_force, strength * taper / (distance * distance + softening * softening))
        toward_source = 1.0 if delta_x >= 0.0 else -1.0
        force_x = magnitude * toward_source * (1.0 if mode == "attract" else -1.0)
        return force_x, distance, magnitude

    def frame(frame_index: int) -> dict[str, Any]:
        body_state = data.body(body_id)
        force_x, distance, magnitude = magnetic_force()
        time_s = round(frame_index / fps, 6)
        source_name = "mujoco_magnetic_force"
        return {
            "frame": frame_index,
            "time": time_s,
            "source": source_name,
            "objects": {
                source_id: {
                    "position": [round(value, 6) for value in source_position],
                    "rotation_degrees": [0.0, 0.0, 0.0],
                    "velocity_m_s": [0.0, 0.0, 0.0],
                    "angular_velocity_rad_s": [0.0, 0.0, 0.0],
                    "source": source_name,
                },
                body_id: {
                    "position": [round(float(value), 6) for value in body_state.xpos],
                    "rotation_degrees": [0.0, 0.0, 0.0],
                    "velocity_m_s": [round(float(data.qvel[dof_adr]), 6), 0.0, 0.0],
                    "angular_velocity_rad_s": [0.0, 0.0, 0.0],
                    "source": source_name,
                },
            },
            "contacts": _contacts(model, data, frame_index, fps),
            "force_fields": [{
                "source_object_id": source_id,
                "subject_object_id": body_id,
                "mode": mode,
                "distance_m": round(distance, 6),
                "magnetic_force_n": round(magnitude, 6),
                "force_vector_n": [round(force_x, 6), 0.0, 0.0],
                "source": source_name,
            }],
            "solver_state": solver_state,
        }

    frame_count = max(1, int(round(duration_s * fps)))
    steps_per_frame = max(1, int(round((1.0 / fps) / model.opt.timestep)))
    frames = [frame(0)]
    for frame_index in range(1, frame_count + 1):
        for _ in range(steps_per_frame):
            force_x, _, _ = magnetic_force()
            data.qfrc_applied[:] = 0.0
            data.qfrc_applied[dof_adr] = force_x
            mujoco.mj_step(model, data)
        frames.append(frame(frame_index))
    return frames


def _simulate_impulse_chain_case(
    case_spec: dict[str, Any],
    *,
    fps: int,
    duration_s: float,
    mujoco: Any,
) -> list[dict[str, Any]]:
    expected = case_spec.get("expected_physics") if isinstance(case_spec.get("expected_physics"), dict) else {}
    objects = {str(item.get("id")): item for item in case_spec.get("objects") or [] if isinstance(item, dict)}
    chain = [str(item) for item in expected.get("chain_objects") or []]
    if len(chain) < 3:
        raise ValueError("constraint_momentum_transfer requires at least three chain objects")
    active_id = str(expected.get("active_object_id") or chain[0])
    rope_length = float(expected.get("rope_length_m") or 0.6)
    release_angle = float(expected.get("active_release_angle_degrees") or 0.0)
    joint_damping = float(expected.get("joint_damping_n_m_s") or 0.004)
    if not all(math.isfinite(value) for value in (rope_length, release_angle, joint_damping)):
        raise ValueError("impulse-chain inputs must be finite")
    if rope_length <= 0.0 or abs(release_angle) <= 1e-6 or joint_damping < 0.0:
        raise ValueError("impulse-chain rope length and release angle must be positive")

    rows: list[dict[str, Any]] = []
    bodies: list[str] = []
    for index, object_id in enumerate(chain):
        body = objects.get(object_id) or {}
        anchor_id = str(body.get("constraint_anchor_id") or f"anchor_{index}")
        anchor = objects.get(anchor_id) or {}
        pivot = _object_position(anchor, [index * 0.161, 0.0, 1.25])
        radius = float(body.get("radius_m") or 0.08)
        mass = float(body.get("mass_kg") or 0.18)
        if not all(math.isfinite(value) for value in [*pivot, radius, mass]) or radius <= 0.0 or mass <= 0.0:
            raise ValueError("impulse-chain object inputs must be finite and positive")
        rows.append({"id": object_id, "anchor_id": anchor_id, "pivot": pivot, "radius": radius, "mass": mass})
        bodies.append(
            f'<body name={quoteattr(object_id)} pos="{_vec(pivot)}">'
            f'<joint name={quoteattr(f"hinge_{object_id}")} type="hinge" axis="0 1 0" damping="{joint_damping}"/>'
            f'<geom name={quoteattr(object_id)} type="sphere" pos="0 0 {-rope_length}" size="{radius}" mass="{mass}" '
            'friction="0.05 0.001 0.0001" solref="0.003 0.7" condim="3"/>'
            '</body>'
        )
    model = mujoco.MjModel.from_xml_string(
        '<mujoco><option timestep="0.0020833333" gravity="0 0 -9.81" integrator="implicitfast"/>'
        '<worldbody>' + "".join(bodies) + '</worldbody></mujoco>'
    )
    data = mujoco.MjData(model)
    joint_data: dict[str, tuple[int, int]] = {}
    for row in rows:
        joint = model.joint(f"hinge_{row['id']}")
        joint_data[row["id"]] = (int(model.jnt_qposadr[int(joint.id)]), int(model.jnt_dofadr[int(joint.id)]))
    data.qpos[joint_data[active_id][0]] = math.radians(release_angle)
    mujoco.mj_forward(model, data)

    source_name = "mujoco_constraint_impulse"
    solver_state = {
        "backend": "mujoco_rigid",
        "model": "hinged_sphere_impulse_chain",
        "version": str(getattr(mujoco, "__version__", "unknown")),
        "timestep_s": round(float(model.opt.timestep), 10),
        "rope_length_m": rope_length,
        "active_release_angle_degrees": release_angle,
        "joint_damping_n_m_s": joint_damping,
        "objects": {
            row["id"]: {"mass_kg": row["mass"], "radius_m": row["radius"], "constraint_anchor_id": row["anchor_id"]}
            for row in rows
        },
    }

    def frame(frame_index: int, contacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        states: dict[str, dict[str, Any]] = {}
        constraints: list[dict[str, Any]] = []
        for row in rows:
            qpos_adr, qvel_adr = joint_data[row["id"]]
            angle = float(data.qpos[qpos_adr])
            angular_speed = float(data.qvel[qvel_adr])
            position = [float(value) for value in data.geom(row["id"]).xpos]
            velocity = [
                -rope_length * math.cos(angle) * angular_speed,
                0.0,
                rope_length * math.sin(angle) * angular_speed,
            ]
            states[row["anchor_id"]] = {
                "position": [round(value, 6) for value in row["pivot"]],
                "rotation_degrees": [0.0, 0.0, 0.0],
                "velocity_m_s": [0.0, 0.0, 0.0],
                "angular_velocity_rad_s": [0.0, 0.0, 0.0],
                "source": source_name,
            }
            states[row["id"]] = {
                "position": [round(value, 6) for value in position],
                "rotation_degrees": [0.0, round(math.degrees(angle), 6), 0.0],
                "velocity_m_s": [round(value, 6) for value in velocity],
                "angular_velocity_rad_s": [0.0, round(angular_speed, 6), 0.0],
                "source": source_name,
            }
            constraints.append({
                "constraint_id": f"tether_{row['id']}",
                "constraint_type": "fixed_length_tether",
                "anchor_id": row["anchor_id"],
                "body_id": row["id"],
                "rest_length_m": rope_length,
                "measured_distance_m": rope_length,
                "source": source_name,
            })
        return {
            "frame": frame_index,
            "time": round(frame_index / fps, 6),
            "source": source_name,
            "objects": states,
            "contacts": contacts or [],
            "constraints": constraints,
            "solver_state": solver_state,
        }

    def impulse_contacts(frame_index: int) -> list[dict[str, Any]]:
        result = []
        for contact_index, contact in enumerate(data.contact[: data.ncon]):
            force = np.zeros(6, dtype=np.float64)
            mujoco.mj_contactForce(model, data, contact_index, force)
            impulse_force = abs(float(force[0]))
            if impulse_force < 0.05:
                continue
            pair = sorted((model.geom(int(contact.geom1)).name, model.geom(int(contact.geom2)).name))
            if pair[0] not in chain or pair[1] not in chain:
                continue
            result.append({
                "frame": frame_index,
                "time": round(frame_index / fps, 6),
                "objects": pair,
                "method": "mujoco_contact_force",
                "normal_force_n": round(impulse_force, 6),
                "source": source_name,
            })
        return result

    frame_count = max(1, int(round(duration_s * fps)))
    steps_per_frame = max(1, int(round((1.0 / fps) / model.opt.timestep)))
    frames = [frame(0)]
    for frame_index in range(1, frame_count + 1):
        frame_contacts: dict[tuple[str, str], dict[str, Any]] = {}
        for _ in range(steps_per_frame):
            mujoco.mj_step(model, data)
            for contact in impulse_contacts(frame_index):
                pair = tuple(contact["objects"])
                previous = frame_contacts.get(pair)
                if previous is None or contact["normal_force_n"] > previous["normal_force_n"]:
                    frame_contacts[pair] = contact
        frames.append(frame(frame_index, list(frame_contacts.values())))
    return frames


def _simulate_ramp_friction_case(
    case_spec: dict[str, Any],
    *,
    fps: int,
    duration_s: float,
    mujoco: Any,
) -> list[dict[str, Any]]:
    expected = case_spec.get("expected_physics") if isinstance(case_spec.get("expected_physics"), dict) else {}
    objects = {str(item.get("id")): item for item in case_spec.get("objects") or [] if isinstance(item, dict)}
    subject_id = str(expected.get("subject_object_id") or "ramp_subject")
    subject = objects.get(subject_id) or {}
    ramp = objects.get(str(expected.get("contact_surface") or "ramp")) or {}
    runout = objects.get("runout") or {}
    end_wall = objects.get("end_wall") or {}
    required = {subject_id: subject, "ramp": ramp, "runout": runout, "end_wall": end_wall}
    if any(not value for value in required.values()):
        raise ValueError("ramp friction case requires subject, ramp, runout, and end_wall objects")

    radius = float(subject.get("radius_m") or 0.12)
    mass = float(subject.get("mass_kg") or 0.5)
    friction = float(expected.get("friction_dynamic") or 0.0)
    rolling_friction = float(expected.get("rolling_friction") or 0.05)
    torsional_friction = float(expected.get("torsional_friction") or 0.005)
    linear_damping = float(expected.get("linear_damping") or 0.05)
    angular_damping = float(expected.get("angular_damping") or 0.02)
    slope_angle = float(expected.get("slope_angle_deg") or 0.0)
    numeric = [radius, mass, friction, rolling_friction, torsional_friction, linear_damping, angular_damping, slope_angle]
    if not all(math.isfinite(value) for value in numeric) or radius <= 0.0 or mass <= 0.0 or friction < 0.0:
        raise ValueError("ramp friction inputs must be finite and non-negative")

    def static_geom(object_id: str, obj: dict[str, Any], *, pitch: float = 0.0, friction_value: float) -> str:
        size = _half_size(obj)
        position = _object_position(obj, [0.0, 0.0, 0.0])
        return (
            f'<geom name={quoteattr(object_id)} type="box" size="{_vec(size)}" pos="{_vec(position)}" '
            f'euler="0 {pitch} 0" friction="{friction_value} {rolling_friction} {torsional_friction}" solref="0.01 1"/>'
        )

    subject_position = _object_position(subject, [0.0, 0.0, radius])
    runout_friction = float(expected.get("runout_friction_dynamic") or 0.8)
    xml = (
        '<mujoco><option timestep="0.0020833333" gravity="0 0 -9.81" integrator="implicitfast"/>'
        '<worldbody>'
        + static_geom("ramp", ramp, pitch=slope_angle, friction_value=friction)
        + static_geom("runout", runout, friction_value=runout_friction)
        + static_geom("end_wall", end_wall, friction_value=runout_friction)
        + f'<body name={quoteattr(subject_id)} pos="{_vec(subject_position)}"><freejoint/>'
        + f'<geom name={quoteattr(subject_id)} type="sphere" size="{radius}" mass="{mass}" '
        + f'friction="{friction} {rolling_friction} {torsional_friction}" solref="0.02 0.9"/></body>'
        + '</worldbody></mujoco>'
    )
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    body = model.body(subject_id)
    joint_id = int(body.jntadr[0])
    qvel_adr = int(model.jnt_dofadr[joint_id])
    model.dof_damping[qvel_adr : qvel_adr + 3] = linear_damping
    model.dof_damping[qvel_adr + 3 : qvel_adr + 6] = angular_damping
    mujoco.mj_forward(model, data)
    source_name = "mujoco_ramp_friction"
    solver_state = {
        "backend": "mujoco_rigid",
        "model": "inclined_plane_roll_slide_with_runout",
        "version": str(getattr(mujoco, "__version__", "unknown")),
        "timestep_s": round(float(model.opt.timestep), 10),
        "slope_angle_deg": slope_angle,
        "friction_dynamic": friction,
        "rolling_friction": rolling_friction,
        "torsional_friction": torsional_friction,
        "linear_damping": linear_damping,
        "angular_damping": angular_damping,
        "objects": {subject_id: {"mass_kg": mass, "radius_m": radius}},
    }

    def contacts(frame_index: int) -> list[dict[str, Any]]:
        result = _contacts(model, data, frame_index, fps)
        for item in result:
            item["source"] = source_name
        return result

    def frame(frame_index: int, frame_contacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        runtime_body = data.body(subject_id)
        return {
            "frame": frame_index,
            "time": round(frame_index / fps, 6),
            "source": source_name,
            "objects": {
                subject_id: {
                    "position": [round(float(value), 6) for value in runtime_body.xpos],
                    "rotation_degrees": _quat_to_degrees(runtime_body.xquat),
                    "velocity_m_s": [round(float(value), 6) for value in data.qvel[qvel_adr : qvel_adr + 3]],
                    "angular_velocity_rad_s": [round(float(value), 6) for value in data.qvel[qvel_adr + 3 : qvel_adr + 6]],
                    "source": source_name,
                }
            },
            "contacts": frame_contacts or contacts(frame_index),
            "solver_state": solver_state,
        }

    frame_count = max(1, int(round(duration_s * fps)))
    steps_per_frame = max(1, int(round((1.0 / fps) / model.opt.timestep)))
    frames = [frame(0)]
    for frame_index in range(1, frame_count + 1):
        by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        for _ in range(steps_per_frame):
            mujoco.mj_step(model, data)
            for item in contacts(frame_index):
                by_pair[tuple(item["objects"])] = item
        frames.append(frame(frame_index, list(by_pair.values())))
    return frames


def _half_size(obj: dict[str, Any]) -> list[float]:
    size = obj.get("size_m") or [1.0, 1.0, 0.1]
    values = [float(value) for value in [*size, 1.0, 1.0, 0.1][:3]]
    if not all(math.isfinite(value) and value > 0.0 for value in values):
        raise ValueError("static ramp object size_m must be finite and positive")
    return [value / 2.0 for value in values]


def _object_position(obj: dict[str, Any], fallback: list[float]) -> list[float]:
    raw = obj.get("initial_position_m") or obj.get("position_m") or fallback
    values = list(raw) if isinstance(raw, (list, tuple)) else list(fallback)
    padded = [*values, *fallback]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def _mjcf(bindings: list[dict[str, Any]], gravity: list[float] | None = None) -> str:
    geoms = []
    for binding in bindings:
        object_id = str(binding["object_id"])
        physics = binding.get("physics") or {}
        bounds = binding.get("bounds") or {}
        transform = binding.get("transform") or {}
        extents = [float(value) for value in (bounds.get("extents_m") or [0.25, 0.25, 0.25])[:3]]
        position = [float(value) for value in (transform.get("position_m") or [0.0, 0.0, 0.0])[:3]]
        if bounds.get("bottom_z") is not None and bounds.get("top_z") is not None:
            position[2] = (float(bounds["bottom_z"]) + float(bounds["top_z"])) / 2.0
        material = physics.get("material") or {}
        friction = max(0.001, float(material.get("dynamic_friction") or 0.001))
        restitution = max(0.0, min(1.0, float(material.get("restitution") or 0.0)))
        damping_ratio = 1.0 - 0.5 * restitution
        shape = _shape(str(physics.get("collider") or "box"), extents)
        geom = f'<geom name={quoteattr(object_id)} {shape} friction="{friction} 0.001 0.0001" solref="0.02 {damping_ratio}" condim="3"'
        if physics.get("simulate_physics"):
            mass = max(0.001, float(physics.get("mass_kg") or 1.0))
            geoms.append(
                f'<body name={quoteattr(object_id)} pos="{_vec(position)}"><joint type="free"/>{geom} mass="{mass}"/></body>'
            )
        else:
            geoms.append(f'{geom} pos="{_vec(position)}"/>')
    return (
        f'<mujoco><option timestep="0.0041666667" gravity="{_vec(gravity or [0.0, 0.0, -9.81])}"/>'
        '<worldbody>' + "".join(geoms) + '</worldbody></mujoco>'
    )


def _shape(collider: str, extents: list[float]) -> str:
    if "sphere" in collider.casefold():
        return f'type="sphere" size="{max(extents)}"'
    if "cylinder" in collider.casefold() or "capsule" in collider.casefold():
        return f'type="cylinder" size="{max(extents[0], extents[1])} {extents[2]}"'
    return f'type="box" size="{_vec(extents)}"'


def _frame(
    model: Any,
    data: Any,
    dynamic: list[dict[str, Any]],
    frame_index: int,
    fps: int,
    solver_state: dict[str, Any],
    substep_contacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    objects = {}
    for binding in dynamic:
        object_id = str(binding["object_id"])
        body = data.body(object_id)
        joint_id = int(model.body(object_id).jntadr[0])
        qvel_adr = int(model.jnt_dofadr[joint_id])
        objects[object_id] = {
            "position": [round(float(value), 6) for value in body.xpos],
            "rotation_degrees": _quat_to_degrees(body.xquat),
            "velocity_m_s": [round(float(value), 6) for value in data.qvel[qvel_adr : qvel_adr + 3]],
            "angular_velocity_rad_s": [round(float(value), 6) for value in data.qvel[qvel_adr + 3 : qvel_adr + 6]],
            "source": "mujoco_rigid",
        }
    contacts_by_pair = {tuple(contact["objects"]): contact for contact in (substep_contacts or [])}
    for contact in _contacts(model, data, frame_index, fps):
        contacts_by_pair[tuple(contact["objects"])] = contact
    return {
        "frame": frame_index,
        "time": round(frame_index / fps, 6),
        "source": "mujoco_rigid",
        "objects": objects,
        "contacts": list(contacts_by_pair.values()),
        "solver_state": solver_state,
    }


def _contacts(model: Any, data: Any, frame_index: int, fps: int) -> list[dict[str, Any]]:
    contacts = []
    seen = set()
    for contact in data.contact[: data.ncon]:
        pair = tuple(sorted((model.geom(int(contact.geom1)).name, model.geom(int(contact.geom2)).name)))
        if pair in seen:
            continue
        seen.add(pair)
        contacts.append({
            "frame": frame_index,
            "time": round(frame_index / fps, 6),
            "objects": list(pair),
            "method": "mujoco_contact",
            "distance_m": round(float(contact.dist), 8),
        })
    return contacts


def _solver_state(mujoco: Any, model: Any, bindings: list[dict[str, Any]]) -> dict[str, Any]:
    objects = {}
    for binding in bindings:
        object_id = str(binding["object_id"])
        geom_id = int(model.geom(object_id).id)
        physics = binding.get("physics") or {}
        material = physics.get("material") or {}
        body_id = int(model.body(object_id).id) if physics.get("simulate_physics") else 0
        dof_adr = int(model.jnt_dofadr[int(model.body(object_id).jntadr[0])]) if body_id else 0
        objects[object_id] = {
            "simulate_physics": bool(physics.get("simulate_physics")),
            "mass_kg": round(float(model.body_mass[body_id]), 8) if body_id else 0.0,
            "friction": [round(float(value), 8) for value in model.geom_friction[geom_id]],
            "solref": [round(float(value), 8) for value in model.geom_solref[geom_id]],
            "requested_restitution": round(float(material.get("restitution") or 0.0), 8),
            "linear_damping": [round(float(value), 8) for value in model.dof_damping[dof_adr : dof_adr + 3]] if body_id else [],
            "angular_damping": [round(float(value), 8) for value in model.dof_damping[dof_adr + 3 : dof_adr + 6]] if body_id else [],
            "inertia_diagonal_kg_m2": [round(float(value), 8) for value in model.body_inertia[body_id]] if body_id else [0.0, 0.0, 0.0],
        }
    return {
        "backend": "mujoco_rigid",
        "version": str(getattr(mujoco, "__version__", "unknown")),
        "timestep_s": round(float(model.opt.timestep), 10),
        "gravity_m_s2": [round(float(value), 8) for value in model.opt.gravity],
        "restitution_mapping": "solref=(0.02, 1-0.5*requested_restitution); monotonic control, not an exact Newton restitution coefficient",
        "objects": objects,
    }


def _quat_to_degrees(quat: Any) -> list[float]:
    w, x, y, z = (float(value) for value in quat)
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return [round(math.degrees(pitch), 5), round(math.degrees(yaw), 5), round(math.degrees(roll), 5)]


def _gravity(case_spec: dict[str, Any]) -> list[float]:
    parameters = case_spec.get("physical_parameters") if isinstance(case_spec.get("physical_parameters"), dict) else {}
    raw = parameters.get("gravity_m_s2") or case_spec.get("gravity_m_s2") or [0.0, 0.0, -9.81]
    values = list(raw) if isinstance(raw, (list, tuple)) else [0.0, 0.0, -9.81]
    padded = [*values, 0.0, 0.0, -9.81]
    return [float(padded[0]), float(padded[1]), float(padded[2])]


def _vec(values: list[float]) -> str:
    return " ".join(str(float(value)) for value in values)
