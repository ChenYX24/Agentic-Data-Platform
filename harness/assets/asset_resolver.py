from __future__ import annotations

import os
from typing import Any

from harness.assets.asset_intent import intent_from_object
from harness.assets.asset_registry import AssetRegistry


def resolve_asset_intents(case_spec: dict[str, Any], *, top_k: int = 5, registry: AssetRegistry | None = None) -> dict[str, Any]:
    registry = registry or AssetRegistry()
    allow_local_preview = os.environ.get("SIM_HARNESS_ALLOW_LOCAL_PREVIEW_ASSETS", "").casefold() in {"1", "true", "yes"}
    objects = [obj for obj in case_spec.get("objects", []) if isinstance(obj, dict)]
    intents = [intent_from_object(obj) for obj in objects]
    rows = []
    for obj, intent in zip(objects, intents):
        explicit_proxy = bool(obj.get("force_analytic_proxy") or obj.get("asset_policy") == "analytic_proxy")
        ranked = [] if explicit_proxy else registry.search(intent.query, top_k=max(top_k * 4, top_k))
        evaluated = [
            {
                **candidate,
                "quality_gate": asset_quality_gate(
                    candidate,
                    physics_critical=intent.physics_critical,
                    allow_local_preview=allow_local_preview,
                ),
            }
            for candidate in ranked
        ]
        selected = next((candidate for candidate in evaluated if str(candidate["quality_gate"]["status"]).startswith("pass")), None)
        rejected = [candidate for candidate in evaluated if candidate["quality_gate"]["status"] == "fail"][:top_k]
        rows.append(
            {
                "intent": intent.to_dict(),
                "candidates": evaluated[:top_k],
                "rejected_candidates": rejected,
                "selected_asset": selected,
                "selection_reason": (
                    "first_reference_approved_candidate"
                    if selected and selected["quality_gate"]["status"] == "pass"
                    else "first_explicit_local_preview_candidate"
                    if selected
                    else "no_quality_approved_candidate"
                ),
                "runtime_binding_requirements": intent.required_properties,
                "fallback_reason": (
                    None
                    if selected
                    else "explicit analytic proxy policy"
                    if explicit_proxy
                    else "no quality-approved registry candidate; use analytic/proxy asset"
                ),
                "fallback_mode": "harness_generate_analytic" if explicit_proxy else "automatic_proxy" if not selected else None,
            }
        )
    selected = [row["selected_asset"] for row in rows if row.get("selected_asset")]
    return {
        "schema_version": "harness_asset_resolution_v1",
        "capability_id": "asset_intent_resolution",
        "stage_id": "asset_resolution",
        "case_id": case_spec.get("case_id"),
        "top_k": top_k,
        "physics_critical_count": sum(1 for intent in intents if intent.physics_critical),
        "visual_only_count": sum(1 for intent in intents if not intent.physics_critical),
        "quality_gate": {
            "approved_count": sum(1 for asset in selected if asset["quality_gate"]["status"] == "pass"),
            "local_preview_count": sum(1 for asset in selected if asset["quality_gate"]["status"] == "pass_local_preview"),
            "fallback_count": sum(1 for row in rows if not row["selected_asset"]),
            "rejected_candidate_count": sum(len(row["rejected_candidates"]) for row in rows),
            "reference_assets_ready": bool(rows)
            and all(asset["quality_gate"]["status"] == "pass" for asset in selected)
            and len(selected) == len(rows),
            "local_preview_enabled": allow_local_preview,
        },
        "invocation_contract": {
            "next_capability_id": "asset_runtime_binding_invocation",
            "requires_selected_asset_or_fallback": True,
            "physics_critical_required_properties": ["collider", "mass", "rigid_body", "collision_profile"],
        },
        "assets": rows,
    }


def asset_quality_gate(
    asset: dict[str, Any],
    *,
    physics_critical: bool,
    allow_local_preview: bool = False,
) -> dict[str, Any]:
    execution_failures: list[str] = []
    reference_failures: list[str] = []
    source_kind = str(asset.get("source_kind") or "").strip()
    source_uri = str(asset.get("source_uri") or "").strip()
    license_name = str(asset.get("license") or "").strip()
    quality_status = str(asset.get("quality_status") or "").strip()
    sha256 = str(asset.get("sha256") or "").strip().casefold()

    if not asset.get("ue_path"):
        execution_failures.append("missing_ue_path")
    if not source_kind:
        execution_failures.append("missing_source_kind")
    if not source_uri:
        execution_failures.append("missing_source_uri")
    if not license_name or any(term in license_name.casefold() for term in ("unknown", "unverified", "pending")):
        reference_failures.append("missing_or_unverified_license")
    if quality_status not in {"approved", "approved_proxy"}:
        reference_failures.append("quality_not_approved")
    if source_kind not in {"engine_builtin", "analytic_proxy"} and not is_sha256(sha256):
        reference_failures.append("missing_or_invalid_sha256")
    if physics_critical:
        for field in ("collider", "mass_kg", "material", "collision_profile"):
            if asset.get(field) is None:
                execution_failures.append(f"missing_physics_{field}")
    local_preview = allow_local_preview and quality_status == "local_preview" and not execution_failures
    failures = [*execution_failures, *reference_failures]
    return {
        "status": "fail" if execution_failures or (reference_failures and not local_preview) else "pass_local_preview" if local_preview else "pass",
        "failure_codes": failures,
        "execution_failure_codes": execution_failures,
        "reference_blockers": reference_failures,
        "reference_approved": not failures,
        "content_identity": sha256 or source_uri or None,
        "hash_required": source_kind not in {"engine_builtin", "analytic_proxy"},
    }


def is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
