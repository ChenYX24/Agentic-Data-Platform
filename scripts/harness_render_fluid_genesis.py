from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.core.artifact_schema import read_json, write_json
from harness.core.artifact_manager import ArtifactManager
from harness.verification.rgb_observability import verify_expected_color_observability


def surface_frame_paths(cache: dict[str, Any], cache_root: Path) -> list[Path]:
    frames = cache.get("frames") if isinstance(cache.get("frames"), list) else []
    paths: list[Path] = []
    for expected, frame in enumerate(frames):
        if not isinstance(frame, dict) or int(frame.get("frame", -1)) != expected:
            raise ValueError("particle cache frames must be contiguous and zero-based")
        surface = frame.get("surface") if isinstance(frame.get("surface"), dict) else {}
        path = (cache_root / str(surface.get("path") or "")).resolve()
        if not path.is_file() or cache_root.resolve() not in path.parents:
            raise ValueError(f"particle cache surface is missing or outside its root: {path}")
        paths.append(path)
    if not paths:
        raise ValueError("particle cache has no surface frames")
    return paths


def encode_video(frames: Path, output: Path, fps: int) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
            "-i", str(frames / "frame_%04d.png"), "-c:v", "libx264",
            "-pix_fmt", "yuv420p", str(output),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render an existing Genesis fluid surface cache with the native rasterizer.")
    parser.add_argument("particle_cache")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--view",
        choices=("overview_static", "front_static", "side_static", "top_down", "event_closeup"),
        default="front_static",
    )
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--publish-dir")
    args = parser.parse_args()

    import genesis as gs
    import numpy as np
    from PIL import Image

    cache_path = Path(args.particle_cache).expanduser().resolve()
    cache = read_json(cache_path)
    surfaces = surface_frame_paths(cache, cache_path.parent)
    fps = int((cache.get("timebase") or {}).get("fps") or 0)
    if fps <= 0:
        raise SystemExit("particle cache has no valid fps")

    run_dir = Path(args.run_dir).expanduser().resolve()
    view_dir = run_dir / "views" / args.view
    rgb_frames = view_dir / "rgb_frames"
    depth_frames = view_dir / "depth_frames"
    depth_previews = view_dir / "depth_preview_frames"
    segmentation_frames = view_dir / "segmentation_frames"
    segmentation_previews = view_dir / "segmentation_preview_frames"
    for directory in (rgb_frames, depth_frames, depth_previews, segmentation_frames, segmentation_previews):
        directory.mkdir(parents=True, exist_ok=True)

    environment = cache.get("environment") or {}
    rigid_specs = environment.get("rigid_objects") if isinstance(environment.get("rigid_objects"), list) else []
    center_x, center_y = [float(value) for value in environment.get("center_xy_m") or [0.0, 0.0]]
    floor_z = float(environment.get("floor_z_m") or 0.0)
    extent = float(environment.get("wall_half_extent_m") or 0.3)
    initial_surface_z = float(environment.get("initial_liquid_surface_z_m") or floor_z + 0.18)
    wall_height = max(0.30, initial_surface_z - floor_z + 0.16)
    cutaway_height = min(0.08, wall_height)
    wall_thickness = 0.025

    gs.init(backend=gs.cpu, logging_level="warning")
    scene = gs.Scene(show_viewer=False, renderer=gs.renderers.Rasterizer())
    water_surface = gs.surfaces.Water(color=(0.08, 0.38, 0.90), opacity=0.78, roughness=0.12)
    basin_surface = gs.surfaces.Rough(color=(0.35, 0.38, 0.42, 1.0))
    fluid_entities = [
        scene.add_entity(
            morph=gs.morphs.Mesh(file=str(path), collision=False, fixed=True),
            material=gs.materials.Rigid(),
            surface=water_surface,
        )
        for path in surfaces
    ]
    rigid_entities = {
        str(item["id"]): scene.add_entity(
            morph=gs.morphs.Sphere(radius=float(item["radius_m"]), collision=False, fixed=True),
            material=gs.materials.Rigid(),
            surface=gs.surfaces.Rough(color=tuple(float(value) for value in item["visual_color_rgba"])),
        )
        for item in rigid_specs
    }
    basin_specs = [
        ((extent * 2.2, extent * 2.2, 0.04), (center_x, center_y, floor_z - 0.02)),
        ((wall_thickness, extent * 2.2, wall_height), (center_x - extent - wall_thickness / 2, center_y, floor_z + wall_height / 2)),
        ((wall_thickness, extent * 2.2, wall_height), (center_x + extent + wall_thickness / 2, center_y, floor_z + wall_height / 2)),
        # Keep the physical south plane in the solver, but render it as a low
        # inspection lip so the deeper liquid column remains observable.
        ((extent * 2.2, wall_thickness, cutaway_height), (center_x, center_y - extent - wall_thickness / 2, floor_z + cutaway_height / 2)),
        ((extent * 2.2, wall_thickness, wall_height), (center_x, center_y + extent + wall_thickness / 2, floor_z + wall_height / 2)),
    ]
    for size, position in basin_specs:
        scene.add_entity(
            morph=gs.morphs.Box(size=size, pos=position, collision=False, fixed=True),
            material=gs.materials.Rigid(),
            surface=basin_surface,
        )

    if args.view == "top_down":
        camera_position, camera_target, camera_up = (center_x, center_y, 1.7), (center_x, center_y, 0.2), (0.0, 1.0, 0.0)
    elif args.view == "side_static":
        camera_position, camera_target, camera_up = (-1.45, -0.80, 1.30), (center_x, center_y, 0.30), (0.0, 0.0, 1.0)
    elif args.view == "event_closeup":
        camera_position, camera_target, camera_up = (1.15, -1.25, 1.08), (center_x, center_y, 0.36), (0.0, 0.0, 1.0)
    else:
        camera_position, camera_target, camera_up = (1.1, -1.5, 1.35), (center_x, center_y, 0.42), (0.0, 0.0, 1.0)
    camera = scene.add_camera(
        res=(args.width, args.height), pos=camera_position, lookat=camera_target,
        up=camera_up, fov=50, near=0.1, far=20.0,
    )
    scene.build()

    hidden_positions = [(100.0 + index, 0.0, 0.0) for index in range(len(fluid_entities))]
    for entity, position in zip(fluid_entities, hidden_positions, strict=True):
        entity.set_pos(position, relative=False)

    rigid_instance_ids = {object_id: index + 2 for index, object_id in enumerate(rigid_entities)}
    basin_instance_id = len(rigid_instance_ids) + 2
    palette = {0: (0, 0, 0), 1: (30, 150, 255), basin_instance_id: (150, 150, 150)}
    for object_id, stable_id in rigid_instance_ids.items():
        spec = next(item for item in rigid_specs if str(item["id"]) == object_id)
        palette[stable_id] = tuple(int(round(255 * float(value))) for value in spec["visual_color_rgba"][:3])
    camera_poses = []
    for frame_index, entity in enumerate(fluid_entities):
        entity.set_pos((0.0, 0.0, 0.0), relative=False)
        rigid_states = cache["frames"][frame_index].get("rigid_objects") or {}
        for object_id, rigid_entity in rigid_entities.items():
            rigid_entity.set_pos(tuple(rigid_states[object_id]["position_m"]), relative=False)
        if args.view == "event_closeup":
            progress = frame_index / max(1, len(fluid_entities) - 1)
            eased = progress * progress * (3.0 - 2.0 * progress)
            angle = math.radians(-52.0 + 72.0 * eased)
            radius = 1.62
            camera_position = (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle),
                1.32 + 0.08 * math.sin(math.pi * progress),
            )
            rigid_z = [float(state["position_m"][2]) for state in rigid_states.values() if state.get("position_m")]
            target_z = min(0.58, max(0.30, sum(rigid_z) / len(rigid_z))) if rigid_z else 0.36
            camera_target = (center_x, center_y, target_z)
            camera.set_pose(pos=camera_position, lookat=camera_target, up=(0.0, 0.0, 1.0))
        camera_poses.append(
            {
                "frame": frame_index,
                "time_s": float(cache["frames"][frame_index]["time_s"]),
                "position_m": [float(value) for value in camera_position],
                "lookat_m": [float(value) for value in camera_target],
            }
        )
        rgb, depth, segmentation, _normal = camera.render(
            rgb=True, depth=True, segmentation=True, colorize_seg=False, force_render=True,
        )
        Image.fromarray(rgb).save(rgb_frames / f"frame_{frame_index:04d}.png")
        np.save(depth_frames / f"frame_{frame_index:04d}.npy", depth.astype(np.float32))
        valid = depth < 19.99
        normalized = np.clip((depth - 0.1) / 3.0, 0.0, 1.0)
        depth_preview = np.where(valid, (255.0 * (1.0 - normalized)).astype(np.uint8), 0)
        Image.fromarray(depth_preview).save(depth_previews / f"frame_{frame_index:04d}.png")

        fluid_id = int(entity.idx) + 1
        stable_segmentation = np.where(segmentation == fluid_id, 1, 0).astype(np.uint16)
        for object_id, rigid_entity in rigid_entities.items():
            stable_segmentation[segmentation == int(rigid_entity.idx) + 1] = rigid_instance_ids[object_id]
        stable_segmentation[(segmentation != 0) & (stable_segmentation == 0)] = basin_instance_id
        np.save(segmentation_frames / f"frame_{frame_index:04d}.npy", stable_segmentation)
        color = np.zeros((*stable_segmentation.shape, 3), dtype=np.uint8)
        for instance_id, rgb_color in palette.items():
            color[stable_segmentation == instance_id] = rgb_color
        Image.fromarray(color).save(segmentation_previews / f"frame_{frame_index:04d}.png")
        entity.set_pos(hidden_positions[frame_index], relative=False)

    rgb_video = view_dir / "rgb.mp4"
    depth_video = view_dir / "depth_preview.mp4"
    segmentation_video = view_dir / "segmentation_preview.mp4"
    encode_video(rgb_frames, rgb_video, fps)
    encode_video(depth_previews, depth_video, fps)
    encode_video(segmentation_previews, segmentation_video, fps)
    write_json(
        view_dir / "meta.json",
        {
            "camera_id": args.view,
            "frame_count_rgb": len(surfaces),
            "frame_count_depth": len(surfaces),
            "frame_count_segmentation": len(surfaces),
            "depth_format": "npy_float32_metric_m",
            "segmentation_format": "npy_uint16_stable_instance_id",
            "camera_mode": "trajectory" if args.view == "event_closeup" else "static",
            "camera_trajectory": camera_poses,
            "instance_mapping": {
                "0": "background",
                "1": "fluid_surface",
                **{str(stable_id): object_id for object_id, stable_id in rigid_instance_ids.items()},
                str(basin_instance_id): "basin",
            },
        },
    )
    rendered_views = sorted(path.name for path in (run_dir / "views").iterdir() if path.is_dir())
    observability = verify_expected_color_observability(
        run_dir, expected_rgb=[0.08, 0.38, 0.90], view_ids=rendered_views, write=True,
    )
    report = {
        "schema_version": "harness_genesis_native_surface_render_v1",
        "status": "pass" if observability["status"] == "pass" else "fail",
        "review_role": "diagnostic_probe",
        "backend": "genesis_native_rasterizer",
        "source_particle_cache": str(cache_path),
        "source_particle_cache_sha256": hashlib.sha256(cache_path.read_bytes()).hexdigest(),
        "solver_execution_count": 0,
        "frame_count": len(surfaces),
        "fps": fps,
        "resolution": [args.width, args.height],
        "view": args.view,
        "view_count": len(rendered_views),
        "views": rendered_views,
        "modalities": {
            "rgb": str(rgb_video.relative_to(run_dir)),
            "depth": str(depth_video.relative_to(run_dir)),
            "segmentation": str(segmentation_video.relative_to(run_dir)),
        },
        "canonical_sensor_truth": {
            "depth": "per-frame float32 metric-meter NPY",
            "segmentation": "per-frame uint16 stable-instance-ID NPY",
        },
        "rgb_observability": observability,
        "known_limitations": ["not a UE render", "Genesis rasterizer local preview"],
    }
    overall = ArtifactManager(run_dir).publish_run_overall()
    report["overall"] = {modality: str(path.relative_to(run_dir)) for modality, path in overall.items()}
    write_json(run_dir / "fluid_genesis_render_report.json", report)
    if args.publish_dir:
        publish_dir = Path(args.publish_dir).expanduser().resolve()
        publish_dir.mkdir(parents=True, exist_ok=True)
        for path in (rgb_video, depth_video, segmentation_video, run_dir / "fluid_genesis_render_report.json"):
            shutil.copy2(path, publish_dir / path.name)
    print(json.dumps({key: report[key] for key in ("status", "backend", "frame_count", "view", "modalities")}, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
