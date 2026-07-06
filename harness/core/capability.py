from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_SCHEMA_VERSION = "harness_capability_v1"


@dataclass(frozen=True)
class Capability:
    id: str
    description: str
    physical_assumptions: list[str]
    required_signals: list[str]
    required_assets: list[str]
    verifier_rules: list[str]
    failure_taxonomy: list[str]
    repair_suggestions: list[str]
    smoke_cases: list[str]
    regression_cases: list[str]
    capability_type: str
    stage_ids: list[str]
    deprecated_by: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Capability":
        validate_capability_dict(data)
        return cls(
            id=str(data["id"]),
            description=str(data["description"]),
            physical_assumptions=[str(item) for item in data.get("physical_assumptions", [])],
            required_signals=[str(item) for item in data.get("required_signals", [])],
            required_assets=[str(item) for item in data.get("required_assets", [])],
            verifier_rules=[str(item) for item in data.get("verifier_rules", [])],
            failure_taxonomy=[str(item) for item in data.get("failure_taxonomy", [])],
            repair_suggestions=[str(item) for item in data.get("repair_suggestions", [])],
            smoke_cases=[str(item) for item in data.get("smoke_cases", [])],
            regression_cases=[str(item) for item in data.get("regression_cases", [])],
            capability_type=str(data.get("capability_type") or infer_capability_type(str(data["id"]))),
            stage_ids=[str(item) for item in data.get("stage_ids", [])],
            deprecated_by=str(data["deprecated_by"]) if data.get("deprecated_by") else None,
        )

    def to_summary(self) -> dict[str, Any]:
        summary = {
            "id": self.id,
            "capability_type": self.capability_type,
            "stage_ids": self.stage_ids,
            "description": self.description,
            "required_signals": self.required_signals,
            "required_assets": self.required_assets,
            "smoke_cases": self.smoke_cases,
            "regression_cases": self.regression_cases,
        }
        if self.deprecated_by:
            summary["deprecated_by"] = self.deprecated_by
        return summary


class CapabilityStore:
    def __init__(self, root: str | Path = ROOT / "capabilities") -> None:
        self.root = Path(root)

    def list(self) -> list[Capability]:
        return [Capability.from_dict(read_json(path)) for path in sorted(self.root.glob("*.json"))]

    def get(self, capability_id: str) -> Capability:
        path = self.root / f"{capability_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"capability not found: {capability_id}")
        return Capability.from_dict(read_json(path))


def validate_capability_dict(data: dict[str, Any]) -> None:
    if data.get("schema_version") != CAPABILITY_SCHEMA_VERSION:
        raise ValueError("capability schema_version must be harness_capability_v1")
    required = [
        "id",
        "description",
        "physical_assumptions",
        "required_signals",
        "required_assets",
        "verifier_rules",
        "failure_taxonomy",
        "repair_suggestions",
        "smoke_cases",
        "regression_cases",
    ]
    for key in required:
        if key not in data:
            raise ValueError(f"capability missing field: {key}")
    for key in required[2:]:
        if not isinstance(data.get(key), list):
            raise ValueError(f"capability field must be list: {key}")
    if "stage_ids" in data and not isinstance(data["stage_ids"], list):
        raise ValueError("capability field must be list: stage_ids")


def infer_capability_type(capability_id: str) -> str:
    if capability_id in {"asset_intent_resolution", "asset_runtime_binding_invocation"}:
        return "asset_operation"
    if capability_id in {"capability_runtime_artifact_bridge", "canonical_signal_capture"}:
        return "runtime_bridge"
    if capability_id in {"pipeline_stage_orchestration", "scene_spec_compilation", "static_scene_placement", "prompt_case_capability_planning"}:
        return "pipeline_stage"
    if capability_id in {"physics_property_constraint_validation", "explicit_physics_control_surface"}:
        return "physics_constraint"
    if capability_id in {"physics_verifier_truth_gate"}:
        return "verification"
    if capability_id in {"dataset_artifact_packaging"}:
        return "dataset_packaging"
    if capability_id in {"billiard_causality_compiler"}:
        return "compatibility_alias"
    return "physics_constraint"


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data
