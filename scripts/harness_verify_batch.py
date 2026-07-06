from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.core.artifact_schema import write_json
from harness.runtime.render_pass_contract import verify_render_observability
from harness.verification.physics_verifier import PhysicsVerifier
from harness.verification.render_sync_checker import check_render_sync


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify every harness run directory inside a batch output directory.")
    parser.add_argument("batch_dir", nargs="?", help="Batch directory under runs/harness_cases/...")
    parser.add_argument("--runs", dest="batch_dir_flag", help="Alias for batch_dir.")
    parser.add_argument("--require-multiview", action="store_true")
    parser.add_argument("--require-depth", action="store_true")
    parser.add_argument("--min-view-count", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_arg = args.batch_dir_flag or args.batch_dir
    if not batch_arg:
        raise SystemExit("--runs or batch_dir is required")
    batch_dir = Path(batch_arg)
    if not batch_dir.is_absolute():
        batch_dir = ROOT / batch_dir
    verifier = PhysicsVerifier()
    rows: list[dict[str, Any]] = []

    for run_dir in sorted(path for path in batch_dir.iterdir() if path.is_dir()):
        case_spec = run_dir / "case_spec.json"
        if not case_spec.exists():
            rows.append(
                {
                    "run_dir": str(run_dir),
                    "status": "fail",
                    "failure_type": "artifact_missing",
                    "reason": "missing case_spec.json",
                    "render_sync": {},
                }
            )
            continue
        report = verifier.verify_run_dir(run_dir, write=True)
        render_observability = verify_render_observability(run_dir, require_multiview=args.require_multiview, require_depth=args.require_depth, min_view_count=args.min_view_count)
        render_sync = check_render_sync(run_dir, require_depth=args.require_depth, require_segmentation=False, write=True)
        if render_observability["failures"]:
            report = dict(report)
            report["status"] = "fail"
            report["failure_type"] = render_observability["failures"][0]["code"]
        rows.append(
            {
                "run_dir": str(run_dir),
                "case_id": report["case_id"],
                "capability_id": report["capability_id"],
                "status": report["status"],
                "failure_type": report["failure_type"],
                "artifact_completeness": report.get("artifact_completeness", {}),
                "render_observability": render_observability,
                "render_sync": render_sync,
            }
        )

    failure_counts = Counter(str(row["failure_type"]) for row in rows if row.get("failure_type"))
    artifact_missing = sum(1 for row in rows if row.get("failure_type") == "artifact_missing")
    trajectory_empty = sum(1 for row in rows if not (row.get("artifact_completeness") or {}).get("trajectory", False))
    contact_missing = sum(1 for row in rows if not (row.get("artifact_completeness") or {}).get("contact_events_file", False))
    render_missing = sum(1 for row in rows if not (row.get("artifact_completeness") or {}).get("render_manifest", False))
    render_observability_fail = sum(1 for row in rows if (row.get("render_observability") or {}).get("failures"))
    summary = {
        "schema_version": "harness_batch_verifier_summary_v1",
        "artifact_schema_version": "2.3",
        "batch_dir": str(batch_dir),
        "case_count": len(rows),
        "pass_count": sum(1 for row in rows if row["status"] == "pass"),
        "fail_count": sum(1 for row in rows if row["status"] == "fail"),
        "failure_code_distribution": dict(sorted(failure_counts.items())),
        "artifact_completeness": {
            "artifact_missing": artifact_missing,
            "trajectory_empty": trajectory_empty,
            "contact_missing": contact_missing,
            "render_missing": render_missing,
            "render_observability_fail": render_observability_fail,
        },
        "cases": rows,
    }
    render_report = build_batch_render_report(rows, batch_dir=batch_dir)
    write_json(batch_dir / "batch_verifier_summary.json", summary)
    write_json(batch_dir / "batch_render_report.json", render_report)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if artifact_missing == 0 and render_observability_fail == 0 else 1


def build_batch_render_report(rows: list[dict[str, Any]], *, batch_dir: Path) -> dict[str, Any]:
    total = len(rows)
    depth_fail_count = sum(1 for row in rows if "F_DEPTH_MISSING" in ((row.get("render_sync") or {}).get("failure_codes") or []))
    sync_fail_count = sum(1 for row in rows if "F_RENDER_SYNC_FAIL" in ((row.get("render_sync") or {}).get("failure_codes") or []))
    camera_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"case_count": 0, "pass_count": 0, "failure_codes": Counter(), "avg_depth_variance": 0.0, "avg_render_time": 0.0})
    depth_variance_acc: dict[str, list[float]] = defaultdict(list)
    render_time_acc: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for camera_id, stats in ((row.get("render_sync") or {}).get("per_camera_statistics") or {}).items():
            camera_stats[camera_id]["case_count"] += 1
            if stats.get("status") == "pass":
                camera_stats[camera_id]["pass_count"] += 1
            for code in stats.get("failure_codes") or []:
                camera_stats[camera_id]["failure_codes"][str(code)] += 1
            depth_variance_acc[camera_id].append(float(stats.get("depth_variance") or 0.0))
            render_time_acc[camera_id].append(float(stats.get("render_time_sec") or 0.0))
    per_camera = {}
    for camera_id, stats in sorted(camera_stats.items()):
        depth_values = [value for value in depth_variance_acc[camera_id] if value > 0]
        render_values = [value for value in render_time_acc[camera_id] if value > 0]
        per_camera[camera_id] = {
            "case_count": stats["case_count"],
            "pass_count": stats["pass_count"],
            "failure_codes": dict(sorted(stats["failure_codes"].items())),
            "avg_depth_variance": round(sum(depth_values) / len(depth_values), 6) if depth_values else 0.0,
            "avg_render_time": round(sum(render_values) / len(render_values), 6) if render_values else 0.0,
        }
    return {
        "schema_version": "batch_render_report.v2.3",
        "artifact_schema_version": "2.3",
        "batch_dir": str(batch_dir),
        "case_count": total,
        "success_rate": round(sum(1 for row in rows if (row.get("render_sync") or {}).get("status") == "pass") / total, 6) if total else 0.0,
        "depth_fail_rate": round(depth_fail_count / total, 6) if total else 0.0,
        "sync_fail_rate": round(sync_fail_count / total, 6) if total else 0.0,
        "avg_render_time": round(sum(float((row.get("render_sync") or {}).get("avg_render_time") or 0.0) for row in rows) / total, 6) if total else 0.0,
        "per_camera_statistics": per_camera,
    }


if __name__ == "__main__":
    raise SystemExit(main())
