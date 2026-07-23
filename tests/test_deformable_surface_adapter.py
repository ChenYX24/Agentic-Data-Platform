from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.core.artifact_schema import write_json
from harness.runtime.deformable_surface_adapter import (
    DeformableSurfaceAdapterError,
    prepare_ue_deformable_replay,
)
from harness.runtime.fluid_surface_adapter import file_sha256


class DeformableSurfaceAdapterTests(unittest.TestCase):
    def test_converts_metres_and_handedness_for_ue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = root / "surface" / "frame_0000.obj"
            surface.parent.mkdir()
            surface.write_text("v 1 2 3\nv 0 0 0\nv 1 0 0\nf 1 2 3\n", encoding="utf-8")
            state = root / "deformable_cache.npz"
            state.write_bytes(b"canonical-state")
            write_json(root / "deformable_cache.json", {
                "schema_version": "harness_deformable_mesh_cache_v1",
                "canonical_state": "deformable_cache.npz",
                "canonical_state_sha256": file_sha256(state),
                "timebase": {"fps": 24},
                "frames": [{
                    "frame": 0,
                    "time_s": 0.0,
                    "surface": "surface/frame_0000.obj",
                    "vertex_count": 3,
                    "triangle_count": 1,
                    "sha256": file_sha256(surface),
                }],
            })
            replay = prepare_ue_deformable_replay(
                root / "deformable_cache.json",
                root / "ue",
                ue_asset_root="/Game/Test/Cloth",
            )
            converted = (root / "ue/obj_frames_cm_lh/frame_0000.obj").read_text(encoding="utf-8")
            self.assertIn("v 100.00000000 -200.00000000 300.00000000", converted)
            self.assertIn("f 1 3 2", converted)
            self.assertEqual(replay["ue"]["actor_id"], "cloth_surface")
            self.assertEqual(replay["frames"][0]["ue_asset_path"], "/Game/Test/Cloth/SM_Cloth_0000")

    def test_rejects_canonical_state_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = root / "frame.obj"
            surface.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
            (root / "deformable_cache.npz").write_bytes(b"tampered")
            write_json(root / "deformable_cache.json", {
                "schema_version": "harness_deformable_mesh_cache_v1",
                "canonical_state": "deformable_cache.npz",
                "canonical_state_sha256": "a" * 64,
                "timebase": {"fps": 24},
                "frames": [{
                    "frame": 0,
                    "time_s": 0.0,
                    "surface": "frame.obj",
                    "vertex_count": 3,
                    "triangle_count": 1,
                    "sha256": file_sha256(surface),
                }],
            })
            with self.assertRaisesRegex(DeformableSurfaceAdapterError, "canonical state hash mismatch"):
                prepare_ue_deformable_replay(
                    root / "deformable_cache.json",
                    root / "ue",
                    ue_asset_root="/Game/Test/Cloth",
                )


if __name__ == "__main__":
    unittest.main()
