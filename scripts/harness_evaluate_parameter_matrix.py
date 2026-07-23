#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.core.artifact_schema import write_json
from harness.verification.parameter_matrix import evaluate_parameter_matrix


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a one-parameter matrix of completed UE harness runs.")
    parser.add_argument("--parameter", required=True)
    parser.add_argument("--expected", required=True, choices=("decreasing", "increasing"))
    parser.add_argument("--run", action="append", required=True, type=parse_run, metavar="VALUE=ABS_PATH")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def parse_run(raw: str) -> tuple[float, Path]:
    try:
        value_text, path_text = raw.split("=", 1)
        value = float(value_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("--run must be VALUE=ABS_PATH") from exc
    if not math.isfinite(value) or not path_text:
        raise argparse.ArgumentTypeError("--run value must be finite and path must not be empty")
    return value, Path(path_text)


def main() -> int:
    args = parse_args()
    report = evaluate_parameter_matrix(args.parameter, args.expected, args.run)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        write_json(args.output, report)
    sys.stdout.write(rendered)
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
