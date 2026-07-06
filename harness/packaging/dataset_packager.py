from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.core.artifact_schema import write_json
from harness.packaging.manifest import run_manifest


def package_runs(run_dirs: list[str | Path], output: str | Path) -> dict[str, Any]:
    entries = [run_manifest(path) for path in run_dirs]
    package = {
        "schema_version": "harness_dataset_package_v1",
        "sample_count": len(entries),
        "entries": entries,
    }
    write_json(output, package)
    return package
