from __future__ import annotations

from typing import Any

from harness.assets.asset_intent import intent_from_object
from harness.assets.asset_registry import AssetRegistry


def resolve_asset_intents(case_spec: dict[str, Any], *, top_k: int = 5, registry: AssetRegistry | None = None) -> dict[str, Any]:
    registry = registry or AssetRegistry()
    intents = [intent_from_object(obj) for obj in case_spec.get("objects", []) if isinstance(obj, dict)]
    rows = []
    for intent in intents:
        candidates = registry.search(intent.query, top_k=top_k)
        selected = candidates[0] if candidates else None
        rows.append(
            {
                "intent": intent.to_dict(),
                "candidates": candidates,
                "selected_asset": selected,
                "selection_reason": "top_registry_candidate" if selected else "no_registry_candidate",
                "runtime_binding_requirements": intent.required_properties,
                "fallback_reason": None if selected else "no registry candidate; use analytic/proxy asset",
            }
        )
    return {
        "schema_version": "harness_asset_resolution_v1",
        "capability_id": "asset_intent_resolution",
        "stage_id": "asset_resolution",
        "case_id": case_spec.get("case_id"),
        "top_k": top_k,
        "physics_critical_count": sum(1 for intent in intents if intent.physics_critical),
        "visual_only_count": sum(1 for intent in intents if not intent.physics_critical),
        "invocation_contract": {
            "next_capability_id": "asset_runtime_binding_invocation",
            "requires_selected_asset_or_fallback": True,
            "physics_critical_required_properties": ["collider", "mass", "rigid_body", "collision_profile"],
        },
        "assets": rows,
    }
