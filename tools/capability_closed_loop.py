from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.capability_planner import CapabilityPlanner
from tools.capability_verifier import CapabilityVerifier


ROOT = Path(__file__).resolve().parents[1]


CASE_PROMPTS = [
    {
        "case_id": "case_a_billiards_causality",
        "prompt": "Create a billiards / pool scene where one cue ball hits a compact rack of passive target balls. Targets must stay still until contact.",
    },
    {
        "case_id": "case_b_falling_blocks",
        "prompt": "Create falling blocks under gravity. Rigid bodies fall and collide with the ground and each other; the motion must not be a visual-only animation.",
    },
    {
        "case_id": "case_c_domino_chain",
        "prompt": "Create a domino chain reaction. The first domino is actively triggered and the later dominoes tip only through sequential contact propagation.",
    },
]


def run_closed_loop_demo(root: str | Path = ROOT, *, timestamp: str | None = None) -> dict[str, Any]:
    root = Path(root)
    timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / "runs" / "physics_capability_closed_loop" / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    planner = CapabilityPlanner(root / "config" / "harness_capability_profile.json")
    verifier = CapabilityVerifier()
    results = []
    for case in CASE_PROMPTS:
        case_id = case["case_id"]
        case_dir = run_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        plan = planner.plan(case["prompt"])
        execution = simulate_execution_trace(case_id, plan)
        report = verifier.verify(plan, execution)
        write_json(case_dir / "capability_plan.json", plan)
        write_json(case_dir / "execution_trace.json", execution)
        write_json(case_dir / "verifier_report.json", report)
        results.append(
            {
                "case_id": case_id,
                "prompt": case["prompt"],
                "primary_capability_id": plan["primary_capability_id"],
                "case_family": plan["case_family"],
                "capability_ready": report["capability_ready"],
                "reference_video_ready": report["reference_video_ready"],
                "artifact_tier": report["artifact_tier"],
                "primary_failure_type": report["primary_failure_type"],
                "diagnosis": report["diagnosis"],
                "artifacts": {
                    "capability_plan": rel(run_dir, case_dir / "capability_plan.json"),
                    "execution_trace": rel(run_dir, case_dir / "execution_trace.json"),
                    "verifier_report": rel(run_dir, case_dir / "verifier_report.json"),
                },
            }
        )
    summary = {
        "schema_version": "capability_closed_loop_summary_v1",
        "run_id": timestamp,
        "mode": "simulated_trace",
        "ue_render_executed": False,
        "note": "This run validates capability-to-execution rules with deterministic simulated traces. It does not claim native UE video rendering.",
        "case_count": len(results),
        "capability_ready_count": sum(1 for item in results if item["capability_ready"]),
        "reference_video_ready_count": sum(1 for item in results if item["reference_video_ready"]),
        "case_results_path": "case_results.json",
    }
    write_json(run_dir / "summary.json", summary)
    write_json(run_dir / "case_results.json", {"schema_version": "capability_closed_loop_case_results_v1", "cases": results})
    write_text(run_dir / "diagnosis.md", render_diagnosis(summary, results))
    return {"run_dir": str(run_dir), "summary": summary, "cases": results}


def simulate_execution_trace(case_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    capability_id = plan["primary_capability_id"]
    if capability_id in {"rigid_body_contact_causality", "billiard_causality_compiler"}:
        return billiards_trace(case_id, plan)
    if capability_id == "rigid_body_gravity_collision":
        return falling_blocks_trace(case_id, plan)
    if capability_id == "sequential_contact_propagation":
        return domino_trace(case_id, plan)
    return generic_trace(case_id, plan)


def base_execution(case_id: str, plan: dict[str, Any], *, objects: list[dict[str, Any]], trajectory: list[dict[str, Any]], contacts_required: bool) -> dict[str, Any]:
    return {
        "schema_version": "capability_execution_trace_v1",
        "case_id": case_id,
        "source_type": "SIM_PROXY",
        "capability_plan": {"primary_capability_id": plan["primary_capability_id"], "case_family": plan["case_family"]},
        "environment": {"gravity_m_s2": 9.81, "fixed_delta_time": 1.0 / 24.0},
        "objects": objects,
        "trajectory": trajectory,
        "render_evidence": {
            "source_type": "SIM_PROXY",
            "runtime_status": "completed",
            "video_available": False,
            "video_required": False,
            "trajectory_available": bool(trajectory),
            "contact_events_available": any(frame.get("contacts") for frame in trajectory) if contacts_required else True,
            "camera_trajectory_available": True,
            "mode": "deterministic_simulated_trace",
        },
    }


def billiards_trace(case_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    objects = [
        body("cue_ball", "active_striker", [-1.0, 0.0, 0.09], [1.4, 0.0, 0.0]),
        body("target_ball_1", "passive_target", [0.0, 0.0, 0.09], [0.0, 0.0, 0.0]),
        body("target_ball_2", "passive_target", [0.18, 0.09, 0.09], [0.0, 0.0, 0.0]),
    ]
    trajectory = [
        frame(0, 0.0, {"cue_ball": state([-1.0, 0, 0.09], [1.4, 0, 0]), "target_ball_1": state([0, 0, 0.09], [0, 0, 0]), "target_ball_2": state([0.18, 0.09, 0.09], [0, 0, 0])}),
        frame(1, 0.2, {"cue_ball": state([-0.72, 0, 0.09], [1.4, 0, 0]), "target_ball_1": state([0, 0, 0.09], [0, 0, 0]), "target_ball_2": state([0.18, 0.09, 0.09], [0, 0, 0])}),
        frame(2, 0.4, {"cue_ball": state([-0.42, 0, 0.09], [0.6, 0, 0]), "target_ball_1": state([0.04, 0, 0.09], [0.55, 0, 0]), "target_ball_2": state([0.18, 0.09, 0.09], [0, 0, 0])}, contacts=[{"objects": ["cue_ball", "target_ball_1"], "time_s": 0.4}]),
        frame(3, 0.6, {"cue_ball": state([-0.30, 0, 0.09], [0.35, 0, 0]), "target_ball_1": state([0.13, 0.02, 0.09], [0.4, 0.08, 0]), "target_ball_2": state([0.23, 0.10, 0.09], [0.24, 0.05, 0])}, contacts=[{"objects": ["target_ball_1", "target_ball_2"], "time_s": 0.6}]),
    ]
    return base_execution(case_id, plan, objects=objects, trajectory=trajectory, contacts_required=True)


def falling_blocks_trace(case_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    objects = [
        body("falling_block_1", "falling_body", [0.0, 0.0, 1.2], [0.0, 0.0, 0.0], gravity_enabled=True),
        body("ground", "support", [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], dynamic=False, gravity_enabled=False),
    ]
    trajectory = [
        frame(0, 0.0, {"falling_block_1": state([0, 0, 1.2], [0, 0, 0]), "ground": state([0, 0, 0], [0, 0, 0])}),
        frame(1, 0.2, {"falling_block_1": state([0, 0, 0.85], [0, 0, -1.9]), "ground": state([0, 0, 0], [0, 0, 0])}),
        frame(2, 0.4, {"falling_block_1": state([0, 0, 0.45], [0, 0, -2.7]), "ground": state([0, 0, 0], [0, 0, 0])}),
        frame(3, 0.6, {"falling_block_1": state([0, 0, 0.11], [0, 0, 0.0]), "ground": state([0, 0, 0], [0, 0, 0])}, contacts=[{"objects": ["falling_block_1", "ground"], "time_s": 0.6}]),
    ]
    return base_execution(case_id, plan, objects=objects, trajectory=trajectory, contacts_required=False)


def domino_trace(case_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    objects = [
        body("domino_0", "domino", [-0.2, 0, 0.2], [0, 0, 0], angular_velocity_deg_s=[0, 70, 0]),
        body("domino_1", "domino", [0.0, 0, 0.2], [0, 0, 0]),
        body("domino_2", "domino", [0.2, 0, 0.2], [0, 0, 0]),
    ]
    trajectory = [
        frame(0, 0.0, {"domino_0": state([-0.2, 0, 0.2], [0, 0, 0], rotation=[0, 0, 0]), "domino_1": state([0.0, 0, 0.2], [0, 0, 0], rotation=[0, 0, 0]), "domino_2": state([0.2, 0, 0.2], [0, 0, 0], rotation=[0, 0, 0])}),
        frame(1, 0.2, {"domino_0": state([-0.2, 0, 0.2], [0, 0, 0], rotation=[0, 18, 0]), "domino_1": state([0.0, 0, 0.2], [0, 0, 0], rotation=[0, 0, 0]), "domino_2": state([0.2, 0, 0.2], [0, 0, 0], rotation=[0, 0, 0])}),
        frame(2, 0.4, {"domino_0": state([-0.2, 0, 0.2], [0, 0, 0], rotation=[0, 55, 0]), "domino_1": state([0.0, 0, 0.2], [0, 0, 0], rotation=[0, 20, 0]), "domino_2": state([0.2, 0, 0.2], [0, 0, 0], rotation=[0, 0, 0])}, contacts=[{"objects": ["domino_0", "domino_1"], "time_s": 0.4}]),
        frame(3, 0.6, {"domino_0": state([-0.2, 0, 0.2], [0, 0, 0], rotation=[0, 75, 0]), "domino_1": state([0.0, 0, 0.2], [0, 0, 0], rotation=[0, 58, 0]), "domino_2": state([0.2, 0, 0.2], [0, 0, 0], rotation=[0, 23, 0])}, contacts=[{"objects": ["domino_1", "domino_2"], "time_s": 0.6}]),
    ]
    return base_execution(case_id, plan, objects=objects, trajectory=trajectory, contacts_required=True)


def generic_trace(case_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    objects = [body("object_0", "dynamic_subject", [0, 0, 0.5], [0, 0, 0])]
    trajectory = [frame(0, 0.0, {"object_0": state([0, 0, 0.5], [0, 0, 0])}), frame(1, 0.1, {"object_0": state([0, 0, 0.5], [0, 0, 0])})]
    return base_execution(case_id, plan, objects=objects, trajectory=trajectory, contacts_required=False)


def body(
    object_id: str,
    role: str,
    position_m: list[float],
    velocity_m_s: list[float],
    *,
    dynamic: bool = True,
    gravity_enabled: bool = True,
    collision_enabled: bool = True,
    angular_velocity_deg_s: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "role": role,
        "dynamic": dynamic,
        "initial_state": {
            "position_m": position_m,
            "linear_velocity_m_s": velocity_m_s,
            "angular_velocity_deg_s": angular_velocity_deg_s or [0.0, 0.0, 0.0],
        },
        "physics": {
            "gravity_enabled": gravity_enabled,
            "collision_enabled": collision_enabled,
            "mass_kg": 1.0,
        },
    }


def state(position_m: list[float], velocity_m_s: list[float], *, rotation: list[float] | None = None) -> dict[str, Any]:
    return {"position_m": position_m, "velocity_m_s": velocity_m_s, "rotation_deg": rotation or [0.0, 0.0, 0.0]}


def frame(frame_id: int, time_s: float, objects: dict[str, Any], *, contacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"frame": frame_id, "time_s": time_s, "objects": objects, "contacts": contacts or []}


def render_diagnosis(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Physics Capability Closed Loop Diagnosis",
        "",
        "本次运行使用 deterministic simulated trace，不调用 UE，也不声称生成 reference video。",
        f"- capability_ready: {summary['capability_ready_count']}/{summary['case_count']}",
        f"- reference_video_ready: {summary['reference_video_ready_count']}/{summary['case_count']}",
        "",
        "## Case Results",
        "",
    ]
    for item in results:
        lines.extend(
            [
                f"### {item['case_id']}",
                "",
                f"- capability: `{item['primary_capability_id']}`",
                f"- family: `{item['case_family']}`",
                f"- capability_ready: `{item['capability_ready']}`",
                f"- artifact_tier: `{item['artifact_tier']}`",
                f"- primary_failure_type: `{item['primary_failure_type']}`",
                f"- repair: {item['diagnosis']['repair_suggestion']}",
                "",
            ]
        )
    return "\n".join(lines)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
