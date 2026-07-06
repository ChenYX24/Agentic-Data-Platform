from __future__ import annotations

from typing import Any

from harness.planning.capability_planner import CapabilityPlanner


def prompt_to_case(prompt: str, *, case_id: str = "generated_case") -> dict[str, Any]:
    """Create a minimal editable case spec from a prompt.

    This is intentionally conservative. Agents should edit the generated spec
    before running a real backend.
    """
    plan = CapabilityPlanner().plan(prompt)
    capability_id = str(plan["primary_capability_id"])
    return {
        "schema_version": "harness_case_spec_v1",
        "case_id": case_id,
        "capability_id": capability_id,
        "prompt": prompt,
        "expected_physics": {"source": "prompt_to_case_stub", "needs_agent_review": True},
        "objects": [],
        "active_objects": [],
        "passive_objects": [],
        "required_assets": [],
        "required_signals": ["trajectory", "contact_events"],
        "verifier_expectation": {"status": "agent_review_required"},
        "should_pass": False,
        "notes": "Generated scaffold. Fill objects/assets/physics before running.",
    }
