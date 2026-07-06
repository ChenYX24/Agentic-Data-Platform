from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CASE_SPEC_SCHEMA_VERSION = "harness_case_spec_v1"


@dataclass(frozen=True)
class CaseSpec:
    data: dict[str, Any]

    @property
    def case_id(self) -> str:
        return str(self.data["case_id"])

    @property
    def capability_id(self) -> str:
        return str(self.data["capability_id"])

    @property
    def should_pass(self) -> bool:
        return bool(self.data["should_pass"])

    @property
    def objects(self) -> list[dict[str, Any]]:
        return [item for item in self.data.get("objects", []) if isinstance(item, dict)]


def load_case_spec(path: str | Path) -> CaseSpec:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"case spec must be a JSON object: {path}")
    validate_case_spec(data)
    return CaseSpec(data)


def validate_case_spec(data: dict[str, Any]) -> None:
    if data.get("schema_version") != CASE_SPEC_SCHEMA_VERSION:
        raise ValueError("case spec schema_version must be harness_case_spec_v1")
    required = [
        "case_id",
        "capability_id",
        "prompt",
        "expected_physics",
        "objects",
        "active_objects",
        "passive_objects",
        "required_assets",
        "required_signals",
        "verifier_expectation",
        "should_pass",
        "notes",
    ]
    for key in required:
        if key not in data:
            raise ValueError(f"case spec missing field: {key}")
    if not isinstance(data["objects"], list) or not data["objects"]:
        raise ValueError("case spec objects must be a non-empty list")
    for key in ("active_objects", "passive_objects", "required_assets", "required_signals"):
        if not isinstance(data[key], list):
            raise ValueError(f"case spec field must be list: {key}")
    if not isinstance(data["should_pass"], bool):
        raise ValueError("case spec should_pass must be boolean")
