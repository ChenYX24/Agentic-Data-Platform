from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_timebase(*, duration_s: float, physics_hz: int, render_fps: int) -> dict[str, Any]:
    duration_s = float(duration_s)
    physics_hz = int(physics_hz)
    render_fps = int(render_fps)
    if duration_s <= 0 or physics_hz <= 0 or render_fps <= 0:
        raise ValueError("duration_s, physics_hz, and render_fps must be positive")
    if physics_hz % render_fps:
        raise ValueError("physics_hz must be an integer multiple of render_fps")
    substeps = physics_hz // render_fps
    canonical_steps = int(round(duration_s * render_fps))
    solver_steps = canonical_steps * substeps
    indices = list(range(0, solver_steps + 1, substeps))
    return {
        "schema_version": "harness_timebase_v1",
        "physics_hz": physics_hz,
        "physics_dt_s": 1.0 / physics_hz,
        "render_fps": render_fps,
        "render_dt_s": 1.0 / render_fps,
        "substeps_per_render": substeps,
        "sample_phase": "initial_then_post_step",
        "endpoint_policy": "inclusive",
        "solver_frame_count": solver_steps + 1,
        "canonical_frame_count": canonical_steps + 1,
        "source_solver_indices": indices,
    }


def sample_solver_trajectory(
    solver_frames: list[dict[str, Any]],
    timebase: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    indices = [int(value) for value in timebase.get("source_solver_indices") or []]
    if not indices or indices[-1] >= len(solver_frames):
        raise ValueError("solver trajectory is shorter than the timebase sampling map")
    render_fps = int(timebase["render_fps"])
    canonical: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] = []
    previous_source = -1
    for frame_index, source_index in enumerate(indices):
        source = solver_frames[source_index]
        source_time = float(source.get("time_s", source.get("time", source_index / int(timebase["physics_hz"]))))
        time_s = frame_index / render_fps
        frame = deepcopy(source)
        frame.update(
            {
                "frame": frame_index,
                "time": round(time_s, 9),
                "source_solver_frame": source_index,
                "source_solver_time_s": round(source_time, 9),
            }
        )
        frame_contacts = []
        for raw_index in range(previous_source + 1, source_index + 1):
            raw = solver_frames[raw_index]
            raw_time = float(raw.get("time_s", raw.get("time", raw_index / int(timebase["physics_hz"]))))
            for event in raw.get("contacts") or []:
                if not isinstance(event, dict):
                    continue
                sampled = deepcopy(event)
                sampled.update(
                    {
                        "frame": frame_index,
                        "time": round(time_s, 9),
                        "source_solver_frame": int(raw.get("frame", raw_index)),
                        "source_solver_time_s": round(raw_time, 9),
                    }
                )
                frame_contacts.append(sampled)
                contacts.append(sampled)
        frame["contacts"] = frame_contacts
        canonical.append(frame)
        previous_source = source_index
    return canonical, contacts
