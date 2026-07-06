from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.packaging.dataset_packager import package_runs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package harness run manifests into a dataset manifest.")
    parser.add_argument("run_dirs", nargs="+", help="Run directories to include.")
    parser.add_argument("--output", default="outputs/harness_dataset_manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package = package_runs([Path(path) for path in args.run_dirs], ROOT / args.output)
    print(json.dumps(package, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
