from __future__ import annotations

import re
from typing import Any

from harness.planning.capability_planner import CapabilityPlanner


def prompt_to_case(prompt: str, *, case_id: str = "generated_case") -> dict[str, Any]:
    """Compile a prompt into a valid, conservative CaseSpec draft."""
    normalized = " ".join(prompt.split())
    if not normalized:
        raise ValueError("prompt must not be empty")
    plan = CapabilityPlanner().plan(normalized)
    capability_id = str(plan["primary_capability_id"])
    template = case_template(capability_id)
    speed = first_number(normalized, r"(-?\d+(?:\.\d+)?)\s*(?:m/s|米每秒)")
    if speed is not None and template["active_objects"]:
        active_id = template["active_objects"][0]
        for obj in template["objects"]:
            if obj["id"] == active_id:
                obj["initial_velocity_m_s"] = [speed, 0.0, 0.0]
                break
        template["physical_parameters"]["requested_speed_m_s"] = speed
    return {
        "schema_version": "harness_case_spec_v1",
        "case_id": case_id,
        "capability_id": capability_id,
        "prompt": normalized,
        "expanded_prompt": (
            f"{normalized} Produce synchronized trajectory, contact/event evidence, static-camera RGB, "
            "OpenEXR depth, and instance segmentation; reject physically inconsistent output."
        ),
        "task_type": template["task_type"],
        "scene": template["scene"],
        "physical_parameters": template["physical_parameters"],
        "expected_physics": {
            **template["expected_physics"],
            "source": "deterministic_prompt_compiler_v1",
            "needs_agent_review": True,
        },
        "objects": template["objects"],
        "active_objects": template["active_objects"],
        "passive_objects": template["passive_objects"],
        "required_assets": template["required_assets"],
        "required_signals": ["trajectory", "contact_events", "camera_trajectory", "rgb", "depth", "segmentation"],
        "asset_requirements": {"acquisition_modes": ["preimported", "harness_generate", "harness_find_at_runtime"]},
        "allowed_proxy_policy": "analytic_proxy_for_local_draft_only",
        "verifier_expectation": {"status": "pass"},
        "should_pass": True,
        "notes": "Executable draft with conservative defaults; review dimensions, materials, and parameter ranges before reference publication.",
        "planning_trace": plan,
    }


def case_template(capability_id: str) -> dict[str, Any]:
    if capability_id == "rigid_body_contact_causality":
        return {
            "task_type": "billiards_collision",
            "scene": {"layout": "flat_table_single_target", "duration_s": 3.0, "coordinate_system": "z_up"},
            "physical_parameters": {"restitution": 0.86, "table_dynamic_friction": 0.035},
            "expected_physics": {"collision_graph": [["cue_ball", "target_ball_1"]], "passive_stationary_until_contact": True},
            "objects": [
                ball("cue_ball", "active_striker", [-1.2, 0.0, 0.09], [1.2, 0.0, 0.0]),
                ball("target_ball_1", "passive_target", [0.0, 0.0, 0.09], [0.0, 0.0, 0.0]),
                support("table", [3.0, 1.6, 0.1]),
            ],
            "active_objects": ["cue_ball"],
            "passive_objects": ["target_ball_1"],
            "required_assets": ["billiard ball", "low-friction table collider"],
        }
    if capability_id == "sequential_contact_propagation":
        dominoes = [
            {
                "id": f"domino_{index + 1:02d}",
                "role": "active_chain_driver" if index == 0 else "passive_target",
                "shape": "box",
                "size_m": [0.06, 0.18, 0.42],
                "mass_kg": 0.08,
                "initial_position_m": [index * 0.16, 0.0, 0.21],
                "initial_velocity_m_s": [0.35, 0.0, 0.0] if index == 0 else [0.0, 0.0, 0.0],
                "asset_query": "domino block",
            }
            for index in range(5)
        ]
        return {
            "task_type": "domino_chain",
            "scene": {"layout": "linear_domino_chain", "duration_s": 3.0, "coordinate_system": "z_up"},
            "physical_parameters": {"restitution": 0.25, "dynamic_friction": 0.45},
            "expected_physics": {"ordered_contact_propagation": True},
            "objects": [*dominoes, support("floor", [2.0, 1.0, 0.1])],
            "active_objects": ["domino_01"],
            "passive_objects": [item["id"] for item in dominoes[1:]],
            "required_assets": ["domino block", "floor collider"],
        }
    if capability_id == "fluid_particle_dynamics":
        return {
            "task_type": "fluid_drop_in_basin",
            "scene": {"layout": "fluid_source_over_basin", "duration_s": 1.0, "coordinate_system": "z_up"},
            "physical_parameters": {"density_kg_m3": 1000.0, "particle_size_m": 0.025},
            "expected_physics": {"particle_count_conserved": True, "surface_reconstruction_required": True},
            "objects": [
                {"id": "fluid_source", "role": "fluid_volume", "shape": "box", "size_m": [0.3, 0.3, 0.3], "initial_position_m": [0.0, 0.0, 0.7], "asset_query": "water material"},
                {"id": "basin", "role": "support", "shape": "box", "size_m": [1.0, 1.0, 0.1], "initial_position_m": [0.0, 0.0, 0.0], "asset_query": "basin container"},
            ],
            "active_objects": ["fluid_source"],
            "passive_objects": ["basin"],
            "required_assets": ["water material", "basin collider", "surface reconstruction cache"],
        }
    return {
        "task_type": "gravity_drop",
        "scene": {"layout": "body_over_floor", "duration_s": 3.0, "coordinate_system": "z_up"},
        "physical_parameters": {"gravity_m_s2": [0.0, 0.0, -9.81], "restitution": 0.25},
        "expected_physics": {"downward_acceleration_before_contact": True, "support_contact_required": True},
        "objects": [
            {"id": "falling_body", "role": "falling_body", "shape": "box", "size_m": [0.3, 0.3, 0.3], "mass_kg": 1.0, "initial_position_m": [0.0, 0.0, 1.5], "initial_velocity_m_s": [0.0, 0.0, 0.0], "asset_query": "rigid crate"},
            support("floor", [3.0, 3.0, 0.1]),
        ],
        "active_objects": ["falling_body"],
        "passive_objects": ["floor"],
        "required_assets": ["rigid body collider", "floor collider"],
    }


def ball(object_id: str, role: str, position: list[float], velocity: list[float]) -> dict[str, Any]:
    return {
        "id": object_id,
        "role": role,
        "shape": "sphere",
        "radius_m": 0.09,
        "collider": "sphere",
        "mass_kg": 0.17,
        "initial_position_m": position,
        "initial_velocity_m_s": velocity,
        "asset_query": "/Game/Props/Decorative/SM_8Ball.SM_8Ball",
    }


def support(object_id: str, size: list[float]) -> dict[str, Any]:
    return {
        "id": object_id,
        "role": "support",
        "shape": "box",
        "size_m": size,
        "collider": "box",
        "initial_position_m": [0.0, 0.0, 0.0],
        "asset_query": "analytic low friction support",
    }


def first_number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None
