from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.core.artifact_schema import read_json, write_json
from harness.runtime.fluid_surface_adapter import convert_obj_m_rh_to_cm_lh, file_sha256


class DeformableSurfaceAdapterError(RuntimeError):
    pass


def prepare_ue_deformable_replay(
    cache_manifest_path: str | Path,
    destination: str | Path,
    *,
    ue_asset_root: str,
) -> dict[str, Any]:
    cache_manifest_path = Path(cache_manifest_path).expanduser().resolve()
    source_root = cache_manifest_path.parent
    destination = Path(destination).expanduser().resolve()
    output_root = destination / "obj_frames_cm_lh"
    output_root.mkdir(parents=True, exist_ok=True)
    cache = read_json(cache_manifest_path)
    frames = cache.get("frames") if isinstance(cache.get("frames"), list) else []
    timebase = cache.get("timebase") if isinstance(cache.get("timebase"), dict) else {}
    if cache.get("schema_version") != "harness_deformable_mesh_cache_v1" or not frames:
        raise DeformableSurfaceAdapterError("deformable cache manifest is missing frames")
    if not ue_asset_root.startswith("/Game/"):
        raise DeformableSurfaceAdapterError("UE asset root must start with /Game/")
    canonical_state = (source_root / str(cache.get("canonical_state") or "")).resolve()
    if not canonical_state.is_file() or not canonical_state.is_relative_to(source_root):
        raise DeformableSurfaceAdapterError("canonical deformable state is missing or outside the cache root")
    declared_state_hash = str(cache.get("canonical_state_sha256") or "")
    if not declared_state_hash or file_sha256(canonical_state) != declared_state_hash:
        raise DeformableSurfaceAdapterError("canonical state hash mismatch")

    replay_frames: list[dict[str, Any]] = []
    for expected_frame, frame in enumerate(frames):
        if int(frame.get("frame") or 0) != expected_frame:
            raise DeformableSurfaceAdapterError("deformable frames must be contiguous and start at zero")
        source = (source_root / str(frame.get("surface") or "")).resolve()
        if not source.is_file() or not source.is_relative_to(source_root):
            raise DeformableSurfaceAdapterError(f"deformable surface frame is missing: {source}")
        declared_surface_hash = str(frame.get("sha256") or "")
        if not declared_surface_hash or file_sha256(source) != declared_surface_hash:
            raise DeformableSurfaceAdapterError(f"deformable surface hash mismatch at frame {expected_frame}")
        output = output_root / f"frame_{expected_frame:04d}.obj"
        vertex_count, triangle_count = convert_obj_m_rh_to_cm_lh(source, output)
        if vertex_count != int(frame.get("vertex_count") or 0) or triangle_count != int(frame.get("triangle_count") or 0):
            raise DeformableSurfaceAdapterError(f"deformable OBJ count mismatch at frame {expected_frame}")
        replay_frames.append({
            "frame": expected_frame,
            "time_s": round(float(frame.get("time_s") or 0.0), 8),
            "source_surface": source.relative_to(source_root).as_posix(),
            "ue_obj": output.relative_to(destination).as_posix(),
            "ue_asset_path": f"{ue_asset_root.rstrip('/')}/SM_Cloth_{expected_frame:04d}",
            "vertex_count": vertex_count,
            "triangle_count": triangle_count,
            "sha256": file_sha256(output),
        })

    replay = {
        "schema_version": "harness_deformable_surface_replay_v1",
        "adapter": "fixed_topology_obj_sequence_to_ue_static_mesh_swap_v1",
        "state_truth": str(canonical_state),
        "state_truth_sha256": declared_state_hash,
        "surface_truth_role": "derived_render_representation",
        "coordinate_transform": {
            "source": "right-handed z-up metres",
            "target": "Unreal left-handed z-up centimetres",
            "position": "(x, y, z) m -> (100*x, -100*y, 100*z) cm",
            "triangle_winding": "reversed",
        },
        "timebase": {
            "fps": int(timebase.get("fps") or 0),
            "frame_count": len(replay_frames),
            "frame_selection": "surface frame index equals render frame index",
        },
        "ue": {
            "asset_root": ue_asset_root.rstrip("/"),
            "actor_id": "cloth_surface",
            "collision_enabled": False,
            "segmentation_id_policy": "one stable instance id for every mesh frame",
            "material_role": "fabric_opaque_two_sided",
            "replay_method": "swap preimported static mesh at the render-frame seam",
        },
        "frames": replay_frames,
    }
    write_json(destination / "deformable_surface_replay.json", replay)
    return replay
