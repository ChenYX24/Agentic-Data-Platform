from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import FallbackBackend
from harness.runtime.ue_backend import UEBackend, UEBackendUnavailable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one harness case spec with a selected backend.")
    parser.add_argument("case_spec", nargs="?", help="Path to cases/.../*.json")
    parser.add_argument("--case", dest="case_spec_flag", help="Path to cases/.../*.json")
    parser.add_argument("--backend", choices=["fallback", "ue"], default="fallback")
    parser.add_argument("--output-root", default="runs/harness_cases")
    parser.add_argument("--out", dest="output_root_alias", help="Alias for --output-root")
    parser.add_argument("--views", default="front_static,side_static,top_down,tracking_subject,event_closeup")
    parser.add_argument("--render-passes", default="rgb,depth,segmentation")
    parser.add_argument("--camera-strategy", default="bounds_auto_v1")
    parser.add_argument("--mode", choices=["rgb", "data", "both"], default="both", help="UE render pass mode; fallback ignores this.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case_path = args.case_spec_flag or args.case_spec
    if not case_path:
        raise SystemExit("--case or case_spec is required")
    output_root = args.output_root_alias or args.output_root
    requested_views = parse_csv(args.views)
    render_passes = parse_csv(args.render_passes)
    case = load_case_spec(case_path)
    if args.backend == "ue":
        import os

        os.environ["SIM_STUDIO_UE_RENDER_MODE"] = args.mode
    backend = FallbackBackend() if args.backend == "fallback" else UEBackend()
    try:
        run_dir = backend.run_case(case, ROOT / output_root, requested_views=requested_views, render_passes=render_passes, camera_strategy=args.camera_strategy)
    except UEBackendUnavailable as exc:
        print(
            json.dumps(
                {
                    "schema_version": "harness_run_case_result_v1",
                    "run_dir": str(exc.run_dir),
                    "case_id": case.case_id,
                    "backend": args.backend,
                    "status": "failed_unavailable",
                    "failure_type": exc.failure_type,
                    "failure_category": exc.report.get("failure_category"),
                    "real_ue_invoked": bool(exc.report.get("whether_real_ue_invoked")),
                    "reason": str(exc),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps({"schema_version": "harness_run_case_result_v1", "run_dir": str(run_dir), "case_id": case.case_id, "backend": args.backend, "status": "completed"}, indent=2, ensure_ascii=False))
    return 0


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
