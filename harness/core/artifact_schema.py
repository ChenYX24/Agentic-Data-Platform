from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ARTIFACT_SCHEMA_VERSION = "harness_runtime_artifact_v1"
TRAJECTORY_SCHEMA_VERSION = "harness_trajectory_v1"


def runtime_summary(run_id: str, case_id: str, capability_id: str, backend: str, *, status: str = "completed") -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "run_id": run_id,
        "case_id": case_id,
        "capability_id": capability_id,
        "backend": backend,
        "status": status,
    }


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
