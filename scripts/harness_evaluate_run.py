from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.verification.run_quality import evaluate_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply hard artifact gates and compute a comparable technical run score.")
    parser.add_argument("run_dir", help="Harness run directory")
    parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe executable path")
    parser.add_argument("--no-write", action="store_true", help="Print without writing quality_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = evaluate_run(args.run_dir, ffprobe=args.ffprobe, write=not args.no_write)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report["hard_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
