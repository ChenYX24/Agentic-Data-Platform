from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.assets.asset_resolver import resolve_asset_intents
from harness.core.workspace import case_output_root, workspace_path
from harness.planning.static_scene_builder import build_static_scene_layout
from harness.runtime.actor_placement import compile_runtime_actor_placement
from harness.runtime.mujoco_rigid import simulate_rigid_case
from harness.verification.physics_verifier import PhysicsVerifier


DEFAULT_CASE = ROOT / "cases" / "billiards" / "low_speed_single_contact.json"


def run_sweeps(case_spec: dict[str, Any], *, fps: int = 24, duration_s: float = 4.0, parameters: set[str] | None = None) -> dict[str, Any]:
    sweep_specs: list[tuple[str, list[float], Callable[[dict[str, Any], float], None], str, bool]] = [
        ("speed_m_s", [1.8, 2.8, 4.2], mutate_speed, "contact_time_s", False),
        ("mass_ratio", [0.5, 1.0, 2.0], mutate_mass_ratio, "target_speed_post_m_s", False),
        ("restitution_control", [0.1, 0.5, 0.9], mutate_restitution, "kinetic_energy_retention", True),
        ("friction", [0.01, 0.1, 0.4], mutate_friction, "target_final_displacement_m", False),
        ("incidence_angle_deg", [0.0, 12.0, 18.0], mutate_incidence_angle, "target_lateral_speed_post_m_s", True),
    ]
    sweeps: dict[str, Any] = {}
    representatives: dict[str, dict[str, Any]] = {}
    for parameter, values, mutate, metric, increasing in sweep_specs:
        if parameters is not None and parameter not in parameters:
            continue
        rows = []
        cases = []
        for value in values:
            case = copy.deepcopy(case_spec)
            mutate(case, value)
            case["case_id"] = f"{case_spec.get('case_id', 'rigid')}__{parameter}_{slug(value)}"
            case["sweep_metadata"] = {"parameter": parameter, "value": value, "base_case_id": case_spec.get("case_id")}
            trajectory, verifier = simulate_case(case, fps=fps, duration_s=duration_s)
            rows.append(
                {
                    "value": value,
                    "verifier_status": verifier["status"],
                    "metrics": collision_metrics(case, trajectory),
                    "solver_parameter_echo": (trajectory[0].get("solver_state") or {}) if trajectory else {},
                }
            )
            cases.append(case)
        metric_values = [float(row["metrics"][metric]) for row in rows]
        directional_pass = monotonic(metric_values, increasing=increasing)
        sweeps[parameter] = {
            "changed_parameter_only": True,
            "values": values,
            "directional_metric": metric,
            "expected_direction": "increasing" if increasing else "decreasing",
            "directional_pass": directional_pass,
            "rows": rows,
        }
        representatives[f"{parameter}__low"] = cases[0]
        representatives[f"{parameter}__high"] = cases[-1]
        if parameter == "incidence_angle_deg":
            mirrored = copy.deepcopy(case_spec)
            mutate(mirrored, -values[-1])
            mirrored["case_id"] = f"{case_spec.get('case_id', 'rigid')}__{parameter}_{slug(-values[-1])}"
            mirrored["sweep_metadata"] = {"parameter": parameter, "value": -values[-1], "base_case_id": case_spec.get("case_id")}
            representatives[f"{parameter}__negative_high"] = mirrored
    return {
        "schema_version": "harness_rigid_parameter_sweep_v1",
        "base_case_id": case_spec.get("case_id"),
        "backend": "mujoco_rigid",
        "fps": fps,
        "duration_s": duration_s,
        "status": "pass" if all(sweep["directional_pass"] and all(row["verifier_status"] == "pass" for row in sweep["rows"]) for sweep in sweeps.values()) else "fail",
        "method": "one parameter changes per sweep; simulation-only points; render low/high representatives separately",
        "sweeps": sweeps,
        "representative_cases": representatives,
    }


def simulate_case(case: dict[str, Any], *, fps: int, duration_s: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assets = resolve_asset_intents(case)
    layout = build_static_scene_layout(case, asset_resolution=assets)
    placement = compile_runtime_actor_placement(case, layout, asset_resolution=assets)
    trajectory = simulate_rigid_case(case, placement, fps=fps, duration_s=duration_s) or []
    return trajectory, PhysicsVerifier().verify(case, trajectory)


def collision_metrics(case: dict[str, Any], trajectory: list[dict[str, Any]]) -> dict[str, Any]:
    active_id = str((case.get("active_objects") or ["cue_ball"])[0])
    passive_id = str((case.get("passive_objects") or ["target_ball_1"])[0])
    contact_index = next(
        (
            index
            for index, frame in enumerate(trajectory)
            if any(set(contact.get("objects") or []) == {active_id, passive_id} for contact in frame.get("contacts") or [])
        ),
        0,
    )
    pre = trajectory[max(0, contact_index - 1)]
    post = trajectory[min(len(trajectory) - 1, contact_index)]
    final = trajectory[-1]
    masses = {str(obj.get("id")): float(obj.get("mass_kg") or 0.0) for obj in case.get("objects") or [] if isinstance(obj, dict)}
    pre_energy = kinetic_energy(pre, masses)
    target_velocity = state_velocity(post, passive_id)
    target_initial = object_by_id(case, passive_id).get("initial_position_m") or [0.0, 0.0, 0.0]
    target_final = ((final.get("objects") or {}).get(passive_id) or {}).get("position") or target_initial
    return {
        "contact_frame": int(post.get("frame") or 0),
        "contact_time_s": float(post.get("time") or 0.0),
        "striker_speed_post_m_s": round(planar_speed(state_velocity(post, active_id)), 8),
        "target_speed_post_m_s": round(planar_speed(target_velocity), 8),
        "target_lateral_speed_post_m_s": round(abs(float(target_velocity[1])), 8),
        "target_deflection_deg": round(math.degrees(math.atan2(float(target_velocity[1]), float(target_velocity[0]))), 6),
        "target_final_displacement_m": round(math.dist([float(value) for value in target_initial[:2]], [float(value) for value in target_final[:2]]), 8),
        "kinetic_energy_retention": round(kinetic_energy(post, masses) / pre_energy, 8) if pre_energy > 0 else 0.0,
    }


def mutate_mass_ratio(case: dict[str, Any], ratio: float) -> None:
    cue = object_by_id(case, primary_object_id(case, "active_objects"))
    target_mass = float(cue.get("mass_kg") or 0.17) * ratio
    for target_id in case.get("passive_objects") or []:
        object_by_id(case, str(target_id))["mass_kg"] = target_mass
    case.setdefault("physical_parameters", {})["target_ball_mass_kg"] = target_mass


def mutate_restitution(case: dict[str, Any], value: float) -> None:
    dynamic_ids = {str(item) for key in ("active_objects", "passive_objects") for item in case.get(key) or []}
    for obj in case.get("objects") or []:
        if str(obj.get("id")) in dynamic_ids:
            obj.setdefault("material", {})["restitution"] = value
    case.setdefault("physical_parameters", {})["restitution"] = value


def mutate_friction(case: dict[str, Any], value: float) -> None:
    changed_ids = {"table", *(str(item) for key in ("active_objects", "passive_objects") for item in case.get(key) or [])}
    for obj in case.get("objects") or []:
        if str(obj.get("id")) in changed_ids:
            obj.setdefault("material", {}).update({"static_friction": value, "dynamic_friction": value})
    case.setdefault("physical_parameters", {})["table_dynamic_friction"] = value


def mutate_incidence_angle(case: dict[str, Any], degrees: float) -> None:
    cue = object_by_id(case, primary_object_id(case, "active_objects"))
    target = object_by_id(case, primary_object_id(case, "passive_objects"))
    cue_position = cue["initial_position_m"]
    target_position = target["initial_position_m"]
    distance_x = float(target_position[0]) - float(cue_position[0])
    speed = planar_speed([float(value) for value in cue.get("initial_velocity_m_s") or [1.0, 0.0]])
    radians = math.radians(degrees)
    cue_position[1] = round(float(target_position[1]) - distance_x * math.tan(radians), 8)
    cue["initial_velocity_m_s"] = [round(speed * math.cos(radians), 8), round(speed * math.sin(radians), 8), 0.0]


def mutate_speed(case: dict[str, Any], speed: float) -> None:
    cue = object_by_id(case, primary_object_id(case, "active_objects"))
    velocity = [float(value) for value in cue.get("initial_velocity_m_s") or [1.0, 0.0, 0.0]]
    current = planar_speed(velocity)
    direction = [velocity[0] / current, velocity[1] / current] if current else [1.0, 0.0]
    cue["initial_velocity_m_s"] = [round(speed * direction[0], 8), round(speed * direction[1], 8), 0.0]
    case.setdefault("physical_parameters", {})["cue_speed_m_s"] = speed


def primary_object_id(case: dict[str, Any], field: str) -> str:
    values = case.get(field) or []
    if not values:
        raise ValueError(f"case has no {field}")
    return str(values[0])


def object_by_id(case: dict[str, Any], object_id: str) -> dict[str, Any]:
    return next(obj for obj in case.get("objects") or [] if isinstance(obj, dict) and str(obj.get("id")) == object_id)


def state_velocity(frame: dict[str, Any], object_id: str) -> list[float]:
    value = ((frame.get("objects") or {}).get(object_id) or {}).get("velocity_m_s") or [0.0, 0.0, 0.0]
    return [float(entry) for entry in [*value, 0.0, 0.0, 0.0][:3]]


def planar_speed(velocity: list[float]) -> float:
    return math.hypot(velocity[0], velocity[1])


def kinetic_energy(frame: dict[str, Any], masses: dict[str, float]) -> float:
    return sum(0.5 * masses.get(object_id, 0.0) * planar_speed(state_velocity(frame, object_id)) ** 2 for object_id in (frame.get("objects") or {}))


def monotonic(values: list[float], *, increasing: bool, tolerance: float = 1e-8) -> bool:
    pairs = zip(values, values[1:])
    return all(right > left + tolerance if increasing else right < left - tolerance for left, right in pairs)


def slug(value: float) -> str:
    return str(value).replace("-", "neg").replace(".", "p")


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    representatives = report.pop("representative_cases")
    representative_paths = {}
    representative_dir = output_dir / "representatives"
    representative_dir.mkdir(exist_ok=True)
    for name, case in representatives.items():
        path = representative_dir / f"{name}.json"
        path.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
        representative_paths[name] = str(path.relative_to(output_dir))
    report["representative_cases"] = representative_paths
    (output_dir / "sweep_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one-variable MuJoCo rigid parameter sweeps and write low/high representative cases.")
    parser.add_argument("--case", default=str(DEFAULT_CASE))
    outputs = parser.add_mutually_exclusive_group()
    outputs.add_argument("--output-dir")
    outputs.add_argument("--case-route", help="Canonical physics/scenario/vNNN_description route under workspace/cases.")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--duration", type=float, default=4.0)
    parser.add_argument("--parameters", default="", help="Comma-separated sweep names; default runs all.")
    args = parser.parse_args()
    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    parameters = {item.strip() for item in args.parameters.split(",") if item.strip()} or None
    report = run_sweeps(case, fps=args.fps, duration_s=args.duration, parameters=parameters)
    if parameters and set(report["sweeps"]) != parameters:
        raise SystemExit(f"unknown sweep parameter(s): {', '.join(sorted(parameters - set(report['sweeps'])))}")
    output_dir = case_output_root(args.case_route) if args.case_route else workspace_path(args.output_dir, default_relative="runs/sweeps/rigid_core")
    write_outputs(report, output_dir)
    print(json.dumps({"status": report["status"], "output": str(output_dir / "sweep_report.json")}, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
