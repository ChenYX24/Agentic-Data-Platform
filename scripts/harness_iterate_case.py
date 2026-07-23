from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.core.artifact_schema import write_json
from harness.core.artifact_manager import (
    COMPLETE_DELIVERY_MIN_SOURCE_RUNS,
    ArtifactManager,
    DeliveryError,
    delivery_group_contract,
    publish_complete_case_delivery,
    safe_filename,
)
from harness.core.workspace import case_output_root, workspace_path
from harness.verification.candidate_selector import choose_best_candidate
from harness.verification.run_quality import evaluate_run


RUN_INDEX_SCHEMA_VERSION = "harness_case_run_index_v1"
COMPARISON_INPUT_FILES = (
    "case_spec.json",
    "camera_plan.json",
    "runtime_actor_placement.json",
    "inputs/render_config.json",
    "inputs/scene.json",
)
COMPARISON_RUNTIME_INPUT_FILES = (
    "logs/studio_runtime_scene_rgb.json",
    "logs/studio_runtime_scene_data.json",
)
COMPARISON_COMBINED_RUNTIME_INPUT_FILE = "logs/studio_runtime_scene_combined.json"
COMPARISON_RUNTIME_INPUT_KEYS = (
    "asset_policy",
    "background_map",
    "camera",
    "dynamic_objects",
    "map_lighting_controls",
    "physics",
    "physics_controls",
    "render",
    "requested_views",
    "simulation",
    "static_objects",
)
COMPARISON_FINGERPRINT_POLICY = "exact_runtime_input_fingerprint_v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render, hard-gate, retry, and select the best harness candidate.")
    parser.add_argument("case_spec")
    parser.add_argument(
        "--backend",
        choices=("ue",),
        default="ue",
        help="Formal complete-case iteration currently supports only the UE backend; use run-case for probes.",
    )
    parser.add_argument("--max-attempts", type=int, default=None, help="Attempt limit; defaults to one attempt per lighting preset.")
    parser.add_argument("--lighting-presets", default="data_neutral,map_lights_balanced_fill,cinematic_subject_key_fill")
    parser.add_argument("--views", default="front_static,side_static,top_down,tracking_subject,event_closeup")
    parser.add_argument("--render-passes", default="rgb,depth,segmentation")
    parser.add_argument("--mode", choices=("rgb", "data", "both"), default="both")
    parser.add_argument(
        "--condition",
        help="Explicit causal-condition label; required when runs under one case route use different inputs.",
    )
    outputs = parser.add_mutually_exclusive_group()
    outputs.add_argument("--output-root")
    outputs.add_argument("--case-route", help="Canonical physics/scenario/vNNN_description route under workspace/cases.")
    parser.add_argument("--video-root", default="review/inbox", help="Publish only the selected hard-gate winner here.")
    parser.add_argument("--stop-on-first-pass", action="store_true", help="Opt out of best-of-N and stop after the first hard-gate pass.")
    parser.add_argument("--keep-going", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_complete_delivery_request(args.views, args.render_passes, backend=args.backend, mode=args.mode)
    condition = args.condition.strip() if isinstance(args.condition, str) and args.condition.strip() else None
    if not args.case_route:
        raise SystemExit(
            "formal complete-case iteration requires --case-route physics/scenario/vNNN_description; "
            "use harness_run_case.py for one-off probes"
        )
    case_path = Path(args.case_spec)
    if not case_path.is_absolute():
        case_path = ROOT / case_path
    presets = [item.strip() for item in args.lighting_presets.split(",") if item.strip()] or ["data_neutral"]
    max_attempts = args.max_attempts if args.max_attempts is not None else len(presets)
    if max_attempts < 1:
        raise SystemExit("--max-attempts must be at least 1")
    session_id = new_session_id()
    group = case_output_root(args.case_route)
    session_root = group / "runs" / session_id
    review = workspace_path(args.video_root, default_relative="review/inbox")
    diagnostic_review = workspace_path("review/probes", default_relative="review/probes")
    candidates: list[dict] = []
    for attempt in range(1, max_attempts + 1):
        preset = presets[(attempt - 1) % len(presets)]
        attempt_root = session_root / f"attempt_{attempt:02d}"
        staging_review = attempt_root / "_unvalidated_review"
        env = os.environ.copy()
        env["SIM_STUDIO_UE_LIGHTING_PRESET"] = preset
        command = [
            sys.executable,
            str(ROOT / "scripts" / "harness_run_case.py"),
            str(case_path),
            "--backend",
            args.backend,
            "--output-root",
            str(attempt_root),
            "--video-root",
            str(staging_review),
            "--views",
            args.views,
            "--render-passes",
            args.render_passes,
            "--mode",
            args.mode,
        ]
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
        summary = parse_json_output(completed.stdout)
        run_dir = Path(str(summary.get("run_dir") or attempt_root / f"{case_path.stem}_{args.backend}"))
        try:
            quality = evaluate_run(run_dir, write=True) if run_dir.is_dir() and (run_dir / "views").is_dir() else None
        finally:
            shutil.rmtree(staging_review, ignore_errors=True)
        row = {
            "attempt": attempt,
            "lighting_preset": preset,
            "returncode": completed.returncode,
            "run_dir": str(run_dir),
            "runner_status": summary.get("status"),
            "runner_failure_type": summary.get("failure_type"),
            "case_id": summary.get("case_id") or case_path.stem,
            "condition": condition,
            "quality": quality,
            "stderr_tail": completed.stderr[-2000:],
        }
        candidates.append(row)
        if quality and quality.get("hard_gate_passed") and args.stop_on_first_pass and not args.keep_going:
            break
    best = choose_best_candidate(candidates)
    report = {
        "schema_version": "harness_iteration_report_v2",
        "session_id": session_id,
        "session_root": str(session_root),
        "case_spec": str(case_path),
        "condition": condition,
        "selection_policy": "hard gates first; then highest technical score; if all fail, fewest hard-gate failures",
        "attempted": len(candidates),
        "best_attempt": best.get("attempt") if best else None,
        "best_run_dir": best.get("run_dir") if best else None,
        "hard_gate_passed": bool(best and (best.get("quality") or {}).get("hard_gate_passed")),
        "review_role": None,
        "publication_tier": None,
        "comparison_run_count": 0,
        "comparison_run_required": COMPLETE_DELIVERY_MIN_SOURCE_RUNS,
        "review_bundle": None,
        "published_videos": [],
        "candidates": candidates,
    }
    session_root.mkdir(parents=True, exist_ok=True)
    report_path = session_root / "iteration_report.json"
    write_json(report_path, report)

    run_index: dict[str, Any] | None = None
    run_index_path = group / "run_index.json"
    if args.case_route:
        with locked_run_index(run_index_path, case_route=str(args.case_route)) as run_index:
            prospective = current_comparison_runs([best], session_id=session_id) if best else []
            existing = indexed_comparison_runs(run_index, allow_empty=True)
            if prospective:
                try:
                    delivery_group_contract(existing + prospective)
                except DeliveryError as exc:
                    report["registration_error"] = f"{type(exc).__name__}: {exc}"
                    write_json(report_path, report)
                    raise RuntimeError(
                        f"selected run is incompatible with case route {args.case_route}; "
                        "fix --condition/acquisition inputs or use a new version route"
                    ) from exc
            register_session(
                run_index,
                session_id=session_id,
                report_path=report_path,
                group=group,
                case_spec=case_path,
                candidates=candidates,
                selected_run_dir=best.get("run_dir") if best else None,
            )

    published_videos: list[Path] = []
    review_bundle: Path | None = None
    review_role = None
    publication_tier = None
    comparison_run_count = 0
    try:
        if best and best.get("run_dir"):
            best_quality = best.get("quality") or {}
            review_role = "review_candidate" if best_quality.get("hard_gate_passed") else "diagnostic_probe"
            publication_tier = quality_publication_tier(best_quality)
            publication_root = review if review_role == "review_candidate" else diagnostic_review
            if review_role == "review_candidate":
                comparison_runs = (
                    indexed_comparison_runs(run_index)
                    if run_index is not None
                    else current_comparison_runs(
                        candidates,
                        session_id=session_id,
                    )
                )
            else:
                comparison_runs = []
            comparison_run_count = len(comparison_runs)
            if review_role == "review_candidate" and comparison_run_count < COMPLETE_DELIVERY_MIN_SOURCE_RUNS:
                review_role = "comparison_pending"
            else:
                review_bundle, published_videos = publish_candidate_bundle(
                    publication_root=publication_root,
                    run_dir=Path(str(best["run_dir"])),
                    group=group,
                    case_route=args.case_route,
                    case_id=str(best.get("case_id") or case_path.stem),
                    backend=args.backend,
                    timestamp=session_id,
                    attempt=int(best.get("attempt") or 0),
                    review_role=review_role,
                    publication_tier=publication_tier,
                    quality=best_quality,
                    comparison_runs=comparison_runs,
                )
    except Exception as exc:
        report["publication_error"] = f"{type(exc).__name__}: {exc}"
        if run_index is not None:
            with locked_run_index(run_index_path, case_route=str(args.case_route)) as current_index:
                set_index_session_status(current_index, session_id, "publication_failed")
        write_json(report_path, report)
        raise

    report.update(
        {
            "review_role": review_role,
            "publication_tier": publication_tier,
            "comparison_run_count": comparison_run_count,
            "comparison_run_required": COMPLETE_DELIVERY_MIN_SOURCE_RUNS,
            "review_bundle": str(review_bundle) if review_bundle else None,
            "published_videos": [str(path) for path in published_videos],
        }
    )
    write_json(report_path, report)
    if run_index is not None:
        with locked_run_index(run_index_path, case_route=str(args.case_route)) as current_index:
            set_index_session_status(
                current_index,
                session_id,
                "published" if review_bundle else (
                    "awaiting_comparison_quorum" if review_role == "comparison_pending" else "completed_without_bundle"
                ),
            )
        write_json(
            group / "latest_iteration.json",
            {
                "schema_version": "harness_latest_iteration_pointer_v1",
                "session_id": session_id,
                "report": report_path.relative_to(group).as_posix(),
                "review_bundle": report["review_bundle"],
                "hard_gate_passed": report["hard_gate_passed"],
                "condition": condition,
            },
        )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["hard_gate_passed"] else 2


def new_session_id() -> str:
    """Return a human-sortable, process-safe identity for one formal iteration."""
    return safe_filename(
        f"{time.strftime('%Y%m%dT%H%M%S')}_{time.time_ns() % 1_000_000_000:09d}_{os.getpid()}_{secrets.token_hex(4)}"
    )


def load_run_index(path: Path, *, case_route: str) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema_version": RUN_INDEX_SCHEMA_VERSION,
            "case_route": case_route,
            "sessions": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid case run index: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != RUN_INDEX_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported case run index: {path}")
    if payload.get("case_route") != case_route or not isinstance(payload.get("sessions"), list):
        raise RuntimeError(f"case run index does not match route {case_route}: {path}")
    return payload


@contextmanager
def locked_run_index(path: Path, *, case_route: str) -> Iterator[dict[str, Any]]:
    """Serialize one complete run-index read/modify/write transaction per case version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f"run-index lock must be a regular file: {lock_path}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            index = load_run_index(path, case_route=case_route)
            yield index
            write_json(path, index)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def register_session(
    index: dict[str, Any],
    *,
    session_id: str,
    report_path: Path,
    group: Path,
    case_spec: Path,
    candidates: list[dict[str, Any]],
    selected_run_dir: str | Path | None = None,
) -> None:
    sessions = index.setdefault("sessions", [])
    if any(isinstance(row, dict) and row.get("session_id") == session_id for row in sessions):
        raise RuntimeError(f"duplicate iteration session id: {session_id}")
    passing_runs = []
    selected = (
        Path(str(selected_run_dir)).expanduser().resolve(strict=False)
        if selected_run_dir is not None
        else None
    )
    for row in candidates:
        if not (row.get("quality") or {}).get("hard_gate_passed") or not row.get("run_dir"):
            continue
        run_dir = Path(str(row["run_dir"])).expanduser().resolve(strict=False)
        if selected is not None and run_dir != selected:
            continue
        passing_runs.append(
            {
                "label": comparison_label(session_id, row),
                "run_dir": str(run_dir),
                "attempt": row.get("attempt"),
                "lighting_preset": row.get("lighting_preset"),
                "condition": row.get("condition"),
                "quality_report": str((run_dir / "quality_report.json").resolve(strict=False)),
                "comparison_policy": COMPARISON_FINGERPRINT_POLICY,
                "comparison_fingerprint": comparison_input_fingerprint(run_dir, required=False),
            }
        )
    sessions.append(
        {
            "session_id": session_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": "rendered",
            "case_spec": str(case_spec.resolve(strict=False)),
            "condition": passing_runs[0].get("condition") if passing_runs else None,
            "report": report_path.relative_to(group).as_posix(),
            "passing_runs": passing_runs,
        }
    )
    index["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")


def set_index_session_status(index: dict[str, Any], session_id: str, status: str) -> None:
    for row in index.get("sessions") or []:
        if isinstance(row, dict) and row.get("session_id") == session_id:
            row["status"] = status
            index["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            return
    raise RuntimeError(f"iteration session is absent from run index: {session_id}")


def comparison_label(session_id: str, row: dict[str, Any]) -> str:
    condition = str(row.get("condition") or "").strip()
    return safe_filename(
        "__".join(
            part
            for part in (
                condition,
                session_id,
                f"attempt_{int(row.get('attempt') or 0):02d}",
                str(row.get("lighting_preset") or "default"),
            )
            if part
        )
    )


def current_comparison_runs(
    candidates: list[dict[str, Any]],
    *,
    session_id: str,
    comparison_fingerprint: str | None = None,
) -> list[dict[str, Any]]:
    comparison: list[dict[str, Any]] = []
    for row in candidates:
        if not (row.get("quality") or {}).get("hard_gate_passed") or not row.get("run_dir"):
            continue
        fingerprint = comparison_input_fingerprint(Path(str(row["run_dir"])), required=False)
        if comparison_fingerprint and fingerprint != comparison_fingerprint:
            continue
        comparison.append(
            {
                "label": comparison_label(session_id, row),
                "run_dir": row["run_dir"],
                "session_id": session_id,
                "attempt": row.get("attempt"),
                "lighting_preset": row.get("lighting_preset"),
                "condition": row.get("condition"),
                "comparison_policy": COMPARISON_FINGERPRINT_POLICY,
                "comparison_fingerprint": fingerprint,
            }
        )
    return comparison


def comparison_input_fingerprint(run_dir: Path, *, required: bool = True) -> str:
    """Fingerprint exact declared inputs plus pass-specific runtime render controls."""
    digest = hashlib.sha256()
    runtime_files = (
        (COMPARISON_COMBINED_RUNTIME_INPUT_FILE,)
        if (run_dir / COMPARISON_COMBINED_RUNTIME_INPUT_FILE).is_file()
        else COMPARISON_RUNTIME_INPUT_FILES
    )
    sources = tuple((relative, None) for relative in COMPARISON_INPUT_FILES) + tuple(
        (relative, COMPARISON_RUNTIME_INPUT_KEYS) for relative in runtime_files
    )
    for relative, projected_keys in sources:
        path = run_dir / relative
        if not path.is_file():
            if required:
                raise RuntimeError(f"comparison input is missing: {path}")
            return ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if required:
                raise RuntimeError(f"comparison input is invalid: {path}") from exc
            return ""
        if projected_keys is not None:
            if not isinstance(payload, dict):
                if required:
                    raise RuntimeError(f"comparison runtime input is not an object: {path}")
                return ""
            payload = {key: payload[key] for key in projected_keys if key in payload}
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def indexed_comparison_runs(
    index: dict[str, Any],
    *,
    comparison_fingerprint: str | None = None,
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    """Return registered hard passes, revalidating each exact input fingerprint."""
    comparison: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for session in index.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        if session.get("status") in {"publication_failed", "comparison_incompatible"}:
            continue
        session_id = str(session.get("session_id") or "")
        for row in session.get("passing_runs") or []:
            if not isinstance(row, dict):
                continue
            run_dir = Path(str(row.get("run_dir") or "")).expanduser().resolve(strict=False)
            quality_report = Path(str(row.get("quality_report") or run_dir / "quality_report.json")).expanduser()
            if not run_dir.is_dir() or not quality_report.is_file():
                continue
            if run_dir in seen:
                raise RuntimeError(f"duplicate source run in case run index: {run_dir}")
            seen.add(run_dir)
            fingerprint = comparison_input_fingerprint(run_dir, required=False)
            if not fingerprint:
                raise RuntimeError(f"registered comparison inputs are missing or invalid: {run_dir}")
            stored_policy = str(row.get("comparison_policy") or "")
            stored_fingerprint = str(row.get("comparison_fingerprint") or "")
            if (
                stored_policy == COMPARISON_FINGERPRINT_POLICY
                and stored_fingerprint
                and stored_fingerprint != fingerprint
            ):
                raise RuntimeError(f"registered comparison input fingerprint drifted after indexing: {run_dir}")
            if comparison_fingerprint and fingerprint != comparison_fingerprint:
                continue
            comparison.append(
                {
                    "label": str(row.get("label") or comparison_label(session_id, row)),
                    "run_dir": str(run_dir),
                    "session_id": session_id,
                    "attempt": row.get("attempt"),
                    "lighting_preset": row.get("lighting_preset"),
                    "condition": row.get("condition"),
                    "comparison_policy": COMPARISON_FINGERPRINT_POLICY,
                    "comparison_fingerprint": fingerprint,
                }
            )
    if not comparison and not allow_empty:
        raise RuntimeError("no registered hard-gate passing source runs remain available for comparison")
    return comparison


def quality_publication_tier(quality: dict[str, Any]) -> str:
    readiness = ((quality.get("source_reports") or {}).get("run_readiness") or {})
    tier = readiness.get("publication_tier")
    if isinstance(tier, str) and tier in {"reference", "local_preview", "rejected"}:
        return tier
    return "unverified" if quality.get("hard_gate_passed") else "rejected"


def publish_candidate_bundle(
    *,
    publication_root: Path,
    run_dir: Path,
    group: Path,
    case_route: str | None,
    case_id: str,
    backend: str,
    timestamp: str,
    attempt: int,
    review_role: str,
    publication_tier: str,
    quality: dict,
    comparison_runs: list[dict] | None = None,
) -> tuple[Path | None, list[Path]]:
    """Publish a rename-atomic review bundle with selected-run and condition lineage."""
    name = safe_filename(f"{case_id}__{backend}__{timestamp}__attempt_{attempt:02d}")
    publication_root.mkdir(parents=True, exist_ok=True)
    if publication_root.is_symlink() or not publication_root.is_dir():
        raise RuntimeError(f"review publication root must be a real directory: {publication_root}")
    destination = publication_root / name
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"review candidate already exists: {destination}")
    staging = Path(tempfile.mkdtemp(dir=publication_root, prefix=f".{name}.staging-"))
    renamed = False
    try:
        delivery = None
        if review_role == "review_candidate":
            delivery = publish_complete_case_delivery(
                comparison_runs or [{"label": f"attempt_{attempt:02d}", "run_dir": run_dir}],
                staging,
                publication_tier=publication_tier,
            )
            staged_videos = [staging / row["file"] for row in delivery["videos"]]
        else:
            staged_videos = ArtifactManager(run_dir).publish_videos(staging, case_id=case_id, backend=backend)
        if not staged_videos:
            return None, []
        case_status_path = group / "case_status.json" if case_route else None
        manifest = {
            "schema_version": "harness_review_manifest_v3" if delivery else "harness_review_manifest_v1",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "candidate": name,
            "case_route": case_route,
            "case_status": str(case_status_path) if case_status_path else None,
            "source_run": str(run_dir.resolve(strict=False)),
            "source_quality_report": str((run_dir / "quality_report.json").resolve(strict=False)),
            "status": "review_pending" if review_role == "review_candidate" else "diagnostic_probe",
            "review_role": review_role,
            "publication_tier": publication_tier,
            "cleanup_policy": "source_run_preserved_until_explicit_cleanup",
            "hard_gate_passed": bool(quality.get("hard_gate_passed")),
            "technical_score": (quality.get("ranking") or {}).get("technical_score"),
            "source_runs": delivery["runs"] if delivery else None,
            "comparison_mode": ((delivery or {}).get("contract") or {}).get("comparison_mode"),
            "comparison_policy": ((delivery or {}).get("contract") or {}).get("comparison_policy"),
            "comparison_fingerprint": ((delivery or {}).get("contract") or {}).get("comparison_fingerprint"),
            "delivery_contract": delivery["contract"] if delivery else None,
            "layout": delivery["layout"] if delivery else None,
            "views": delivery["views"] if delivery else None,
            "run_overall": delivery.get("run_overall") if delivery else None,
            "overall": delivery["overall"] if delivery else None,
            "videos": delivery["videos"] if delivery else [
                {"file": path.name, "sha256": file_sha256(path)} for path in staged_videos
            ],
        }
        write_json(staging / f"{name}.review.json", manifest)
        if destination.exists() or destination.is_symlink():
            raise RuntimeError(f"review candidate already exists: {destination}")
        staging.rename(destination)
        renamed = True
        published = [destination / path.relative_to(staging) for path in staged_videos]
        if case_status_path is not None:
            try:
                update_case_status_for_review(
                    case_status_path,
                    case_route=str(case_route),
                    candidate=name,
                    destination=destination,
                    source_run=run_dir,
                    review_role=review_role,
                    publication_tier=publication_tier,
                    delivery=delivery,
                )
            except Exception:
                destination.rename(staging)
                renamed = False
                raise
        return destination, published
    finally:
        if not renamed:
            shutil.rmtree(staging, ignore_errors=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_case_status_for_review(
    path: Path,
    *,
    case_route: str,
    candidate: str,
    destination: Path,
    source_run: Path,
    review_role: str,
    publication_tier: str,
    delivery: dict | None = None,
) -> None:
    payload: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
    payload.update(
        {
            "schema_version": payload.get("schema_version") or "harness_case_status_v1",
            "case_route": case_route,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": "review_pending" if review_role == "review_candidate" else "diagnostic_only",
            "decision": "awaiting_user_keep_or_reject" if review_role == "review_candidate" else "hard_gate_failed",
            "publication_tier": publication_tier,
        }
    )
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    review.update(
        {
            "candidate": candidate,
            "inbox": str(destination),
            "manifest": str(destination / f"{candidate}.review.json"),
            "source_run": str(source_run.resolve(strict=False)),
            "review_role": review_role,
            "publication_tier": publication_tier,
            "source_runs": [row["source_run"] for row in (delivery or {}).get("runs", [])],
            "views": (delivery or {}).get("views"),
            "modalities": list(((delivery or {}).get("contract") or {}).get("per_view_modalities") or []),
            "comparison_mode": ((delivery or {}).get("contract") or {}).get("comparison_mode"),
            "comparison_policy": ((delivery or {}).get("contract") or {}).get("comparison_policy"),
            "conditions": sorted(
                {
                    str(row["condition"])
                    for row in (delivery or {}).get("runs", [])
                    if row.get("condition") is not None
                }
            ),
            "run_overall": (delivery or {}).get("run_overall"),
            "overall": (delivery or {}).get("overall"),
            "video_count": len((delivery or {}).get("videos") or []),
        }
    )
    payload["review"] = review
    write_json(path, payload)


def validate_complete_delivery_request(views: str, render_passes: str, *, backend: str, mode: str) -> None:
    """Fail before an expensive formal UE iteration if its delivery profile is incomplete."""
    if backend != "ue":
        raise SystemExit("formal complete-case iteration currently supports only --backend ue; use harness_run_case.py for probes")
    requested_views = {item.strip() for item in views.split(",") if item.strip()}
    requested_passes = {item.strip() for item in render_passes.split(",") if item.strip()}
    static_views = {"front_static", "side_static", "top_down"}
    moving_views = {"tracking_subject", "event_closeup"}
    if len(requested_views) < 5:
        raise SystemExit("formal UE iteration requires at least five camera views")
    missing_static = static_views.difference(requested_views)
    if missing_static:
        raise SystemExit(
            f"formal UE iteration requires front_static, side_static, and top_down; "
            f"missing {','.join(sorted(missing_static))}"
        )
    missing_moving = moving_views.difference(requested_views)
    if missing_moving:
        raise SystemExit(
            "formal UE iteration requires tracking_subject and event_closeup; "
            f"missing {','.join(sorted(missing_moving))}"
        )
    missing = {"rgb", "depth", "segmentation"}.difference(requested_passes)
    if missing:
        raise SystemExit(f"formal UE iteration is missing render passes: {','.join(sorted(missing))}")
    if mode != "both":
        raise SystemExit("formal UE iteration requires --mode both")


def parse_json_output(value: str) -> dict:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
