from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.verification.particle_cache_verifier import verify_particle_cache


class ParticleCacheVerifierTests(unittest.TestCase):
    def test_valid_particle_and_surface_cache_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "frame.obj").write_text("v 0 0 0\nf 1 1 1\n", encoding="utf-8")
            cache = particle_cache()
            report = verify_particle_cache(cache, root=root)

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["checks"]["stable_particle_count"])
        self.assertTrue(report["checks"]["container_bounds_respected"])
        self.assertTrue(report["checks"]["surface_topology_consistent"])
        self.assertTrue(report["checks"]["surface_container_bounds_respected"])
        self.assertTrue(report["checks"]["surface_rigid_intersections_absent"])

    def test_particle_loss_and_missing_surface_fail(self) -> None:
        cache = particle_cache()
        cache["frames"][1]["positions_m"].pop()

        report = verify_particle_cache(cache, root="/missing")

        self.assertEqual(report["status"], "fail")
        self.assertIn("particle_count_changed", report["failure_codes"])
        self.assertIn("surface_mesh_missing", report["failure_codes"])

    def test_container_penetration_fails(self) -> None:
        cache = particle_cache()
        cache["frames"][1]["positions_m"][0] = [0.0, 0.0, -0.2]

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "fail")
        self.assertIn("container_penetration", report["failure_codes"])

    def test_invalid_surface_topology_fails(self) -> None:
        cache = particle_cache()
        cache["frames"][1]["surface"] = {**cache["frames"][1]["surface"], "topology_consistent": False, "topology_issue": "open edge"}

        report = verify_particle_cache(cache)

        self.assertIn("surface_topology_invalid", report["failure_codes"])

    def test_reconstructed_surface_outside_basin_fails(self) -> None:
        cache = particle_cache()
        cache["frames"][1]["surface"] = {
            **cache["frames"][1]["surface"],
            "bounds_m": {"min_m": [-0.31, -0.2, 0.0], "max_m": [0.2, 0.2, 1.0]},
        }

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "fail")
        self.assertIn("surface_container_penetration", report["failure_codes"])

    def test_reconstructed_surface_inside_rigid_body_fails(self) -> None:
        cache = particle_cache()
        cache["frames"][1]["surface"] = {
            **cache["frames"][1]["surface"],
            "rigid_intersection_vertex_count": 4,
        }

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "fail")
        self.assertIn("surface_rigid_intersection", report["failure_codes"])

    def test_container_bounds_follow_declared_basin_center(self) -> None:
        cache = particle_cache()
        cache["environment"]["center_xy_m"] = [1.0, -2.0]
        for frame in cache["frames"]:
            frame["positions_m"] = [[row[0] + 1.0, row[1] - 2.0, row[2]] for row in frame["positions_m"]]
            frame["surface"] = {
                **frame["surface"],
                "bounds_m": {"min_m": [1.0, -2.0, 0.0], "max_m": [1.1, -1.9, 1.0]},
            }

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "pass", report)

    def test_buoyant_and_dense_bodies_require_separation_and_splash(self) -> None:
        cache = particle_cache()
        cache["environment"].update({
            "initial_condition": {"type": "container_fill"},
            "initial_liquid_surface_z_m": 0.9,
            "minimum_splash_rise_m": 0.05,
            "minimum_float_sink_separation_m": 0.04,
            "maximum_initial_surface_outlier_m": 0.11,
            "rigid_objects": [
                {"id": "rubber", "radius_m": 0.05, "expected_response": "float"},
                {"id": "lead", "radius_m": 0.05, "expected_response": "sink"},
            ],
        })
        cache["frames"][0]["rigid_objects"] = {"rubber": {"position_m": [0, 0, 1]}, "lead": {"position_m": [0, 0, 1]}}
        cache["frames"][1]["rigid_objects"] = {"rubber": {"position_m": [0, 0, 0.12]}, "lead": {"position_m": [0, 0, 0.05]}}
        cache["frames"][1]["positions_m"][0][2] = 0.96

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "pass", report)
        self.assertGreaterEqual(report["checks"]["float_sink_separation_m"], 0.04)
        self.assertGreaterEqual(report["checks"]["splash_rise_m"], 0.05)
        self.assertEqual(report["checks"]["splash_measurement_start_frame"], 1)

    def test_preimpact_residual_droplet_does_not_inflate_splash(self) -> None:
        cache = particle_cache()
        cache["environment"].update({
            "initial_condition": {"type": "container_fill"},
            "initial_liquid_surface_z_m": 0.2,
            "minimum_splash_rise_m": 0.05,
            "minimum_float_sink_separation_m": 0.04,
            "maximum_initial_surface_outlier_m": 1.0,
            "rigid_objects": [
                {"id": "rubber", "radius_m": 0.05, "expected_response": "float"},
                {"id": "lead", "radius_m": 0.05, "expected_response": "sink"},
            ],
        })
        cache["frames"][0]["positions_m"] = [[0, 0, 1.0], [0.1, 0, 0.2]]
        cache["frames"][0]["rigid_objects"] = {"rubber": {"position_m": [0, 0, 1]}, "lead": {"position_m": [0, 0, 1]}}
        cache["frames"][1]["positions_m"] = [[0, 0, 0.24], [0.1, 0, 0.26]]
        cache["frames"][1]["rigid_objects"] = {"rubber": {"position_m": [0, 0, 0.12]}, "lead": {"position_m": [0, 0, 0.05]}}

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "pass", report)
        self.assertAlmostEqual(report["checks"]["splash_rise_m"], 0.06)

    def test_unsettled_container_fill_is_rejected_before_render(self) -> None:
        cache = particle_cache()
        cache["environment"].update({
            "initial_condition": {"type": "container_fill"},
            "initial_liquid_surface_z_m": 0.2,
            "maximum_initial_surface_outlier_m": 0.08,
        })
        cache["frames"][0]["positions_m"] = [[0, 0, 0.2], [0.1, 0, 0.6]]

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "fail")
        self.assertIn("initial_surface_not_settled", report["failure_codes"])

    def test_uniform_initial_flow_requires_speed_direction_and_displacement(self) -> None:
        cache = particle_cache()
        cache["environment"].update({
            "initial_condition": {
                "type": "container_fill",
                "shape": "box",
                "velocity_field": {"type": "uniform", "velocity_m_s": [0.5, 0.0, 0.0]},
            },
            "initial_liquid_surface_z_m": 1.0,
            "maximum_initial_surface_outlier_m": 0.1,
            "minimum_initial_flow_speed_m_s": 0.4,
            "minimum_horizontal_displacement_m": 0.05,
        })
        cache["frames"][0]["velocities_m_s"] = [[0.5, 0.0, 0.0], [0.5, 0.0, 0.0]]
        cache["frames"][1]["positions_m"] = [[0.1, 0.0, 0.9], [0.2, 0.0, 0.9]]

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["checks"]["initial_flow_type"], "uniform")
        self.assertGreaterEqual(report["checks"]["horizontal_displacement_m"], 0.05)

    def test_fragmented_final_surface_is_rejected(self) -> None:
        cache = particle_cache()
        cache["environment"]["minimum_final_surface_component_fraction"] = 0.8
        cache["frames"][-1]["surface"] = {
            **cache["frames"][-1]["surface"],
            "connected_component_count": 12,
            "largest_component_triangle_fraction": 0.3,
        }

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "fail")
        self.assertIn("final_surface_too_fragmented", report["failure_codes"])

    def test_asset_bound_container_transfer_requires_source_to_receiver_occupancy(self) -> None:
        cache = particle_cache()
        cache["environment"] = {
            "type": "asset_bound_container_transfer",
            "workspace_bounds_m": {"min_m": [-1.0, -1.0, -0.1], "max_m": [1.0, 1.0, 2.0]},
            "penetration_tolerance_m": 0.01,
            "minimum_initial_source_fraction": 0.9,
            "minimum_final_receiver_fraction": 0.9,
            "minimum_source_fraction_decrease": 0.85,
            "maximum_final_spill_fraction": 0.08,
        }
        cache["frames"][0]["transfer_state"] = {
            "source_fraction": 0.95,
            "receiver_fraction": 0.0,
            "outside_both_fraction": 0.05,
        }
        cache["frames"][1]["transfer_state"] = {
            "source_fraction": 0.0,
            "receiver_fraction": 0.94,
            "outside_both_fraction": 0.06,
        }

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["checks"]["transfer_event_frame"], 1)
        self.assertAlmostEqual(report["checks"]["final_receiver_fraction"], 0.94)

    def test_asset_bound_container_transfer_rejects_spill(self) -> None:
        cache = particle_cache()
        cache["environment"] = {
            "type": "asset_bound_container_transfer",
            "workspace_bounds_m": {"min_m": [-1.0, -1.0, -0.1], "max_m": [1.0, 1.0, 2.0]},
            "penetration_tolerance_m": 0.01,
            "minimum_initial_source_fraction": 0.9,
            "minimum_final_receiver_fraction": 0.9,
            "minimum_source_fraction_decrease": 0.85,
            "maximum_final_spill_fraction": 0.08,
        }
        cache["frames"][0]["transfer_state"] = {"source_fraction": 0.95, "receiver_fraction": 0.0, "outside_both_fraction": 0.05}
        cache["frames"][1]["transfer_state"] = {"source_fraction": 0.0, "receiver_fraction": 0.7, "outside_both_fraction": 0.3}

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "fail")
        self.assertIn("container_transfer_receiver_fraction_too_low", report["failure_codes"])
        self.assertIn("container_transfer_spill_too_high", report["failure_codes"])

    def test_asset_bound_container_transfer_rejects_blob_like_ejection(self) -> None:
        cache = particle_cache()
        cache["environment"] = {
            "type": "asset_bound_container_transfer",
            "workspace_bounds_m": {"min_m": [-1.0, -1.0, -0.1], "max_m": [1.0, 1.0, 2.0]},
            "penetration_tolerance_m": 0.01,
            "minimum_source_evacuation_duration_s": 0.5,
            "maximum_source_fraction_drop_per_frame": 0.2,
        }
        template = cache["frames"][0]
        cache["frames"] = []
        for frame, source in enumerate((1.0, 0.98, 0.62, 0.25, 0.0)):
            cache["frames"].append({
                **template,
                "frame": frame,
                "time_s": frame * 0.1,
                "transfer_state": {
                    "source_fraction": source,
                    "receiver_fraction": 0.0 if source else 1.0,
                    "outside_both_fraction": 1.0 - source if source else 0.0,
                },
            })

        report = verify_particle_cache(cache)

        self.assertEqual(report["status"], "fail")
        self.assertIn("container_transfer_source_evacuation_too_abrupt", report["failure_codes"])
        self.assertIn("container_transfer_single_frame_discharge_too_large", report["failure_codes"])


def particle_cache() -> dict:
    surface = {
        "path": "frame.obj",
        "vertex_count": 3,
        "triangle_count": 1,
        "bounds_m": {"min_m": [0.0, 0.0, 0.0], "max_m": [0.1, 0.1, 1.0]},
        "rigid_intersection_vertex_count": 0,
    }
    return {
        "schema_version": "harness_particle_cache_v1",
        "solver": {"gravity_m_s2": [0, 0, -9.81]},
        "particles": {"count": 2, "stable_ids": [0, 1]},
        "environment": {"type": "five_plane_basin", "floor_z_m": 0.0, "wall_half_extent_m": 0.3, "penetration_tolerance_m": 0.01},
        "frames": [
            {"frame": 0, "time_s": 0.0, "positions_m": [[0, 0, 1], [0.1, 0, 1]], "velocities_m_s": [[0, 0, 0], [0, 0, 0]], "surface": surface},
            {"frame": 1, "time_s": 0.1, "positions_m": [[0, 0, 0.9], [0.1, 0, 0.9]], "velocities_m_s": [[0, 0, -1], [0, 0, -1]], "surface": surface},
        ],
    }


if __name__ == "__main__":
    unittest.main()
