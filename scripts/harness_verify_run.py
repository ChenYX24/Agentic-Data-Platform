from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.verification.physics_verifier import PhysicsVerifier
from tools.capability_runtime_adapter import verify_capability_run as verify_legacy_capability_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a harness run directory.")
    parser.add_argument("run_dir", help="Path to run directory.")
    parser.add_argument("--legacy", action="store_true", help="Use legacy capability runtime adapter for existing Studio UE/fallback runs.")
    parser.add_argument("--no-write", action="store_true", help="Do not write verifier artifacts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir)
    if args.legacy or not (run_dir / "case_spec.json").exists():
        result = verify_legacy_capability_run(run_dir, write=not args.no_write)
        report = result["verifier_report"]
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report.get("capability_ready") else 2
    report = PhysicsVerifier().verify_run_dir(run_dir, write=not args.no_write)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
