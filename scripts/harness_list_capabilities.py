from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.core.capability import CapabilityStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List physics-aware harness capabilities.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--include-deprecated", action="store_true", help="Include compatibility aliases and deprecated capabilities.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capabilities = [
        capability.to_summary()
        for capability in CapabilityStore().list()
        if args.include_deprecated or capability.capability_type != "compatibility_alias"
    ]
    if args.json:
        print(json.dumps({"schema_version": "harness_capability_list_v1", "capabilities": capabilities}, indent=2, ensure_ascii=False))
    else:
        for capability in capabilities:
            print(f"{capability['id']}")
            print(f"  capability_type: {capability.get('capability_type') or '-'}")
            print(f"  stage_ids: {', '.join(capability.get('stage_ids') or []) or '-'}")
            if capability.get("deprecated_by"):
                print(f"  deprecated_by: {capability['deprecated_by']}")
            print(f"  required_signals: {', '.join(capability['required_signals']) or '-'}")
            print(f"  smoke_cases: {', '.join(capability['smoke_cases']) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
