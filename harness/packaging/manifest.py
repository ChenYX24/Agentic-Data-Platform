from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.core.artifact_schema import read_json


def run_manifest(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest_path = run_dir / "artifact_manifest.json"
    if manifest_path.exists():
        return read_json(manifest_path)
    return {"schema_version": "harness_artifact_manifest_v1", "run_id": run_dir.name, "artifacts": {}}
