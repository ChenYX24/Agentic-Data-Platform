from __future__ import annotations

from typing import Any


def compile_scene_spec(case_spec: dict[str, Any], asset_resolution: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile a minimal harness scene spec from case spec and asset selections."""
    return {
        "schema_version": "harness_scene_spec_v1",
        "case_id": case_spec["case_id"],
        "capability_id": case_spec["capability_id"],
        "objects": case_spec.get("objects", []),
        "active_objects": case_spec.get("active_objects", []),
        "passive_objects": case_spec.get("passive_objects", []),
        "collision_graph": case_spec.get("expected_physics", {}).get("collision_graph", []),
        "camera": case_spec.get("expected_physics", {}).get("camera", {"mode": "fixed"}),
        "required_signals": case_spec.get("required_signals", []),
        "assets": asset_resolution or {},
    }
