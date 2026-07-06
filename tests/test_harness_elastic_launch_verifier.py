from __future__ import annotations

import unittest

from harness.verification.physics_verifier import PhysicsVerifier


class HarnessElasticLaunchVerifierTests(unittest.TestCase):
    def test_spring_launch_trace_passes_energy_release_invariant(self) -> None:
        report = PhysicsVerifier().verify(case_spec(), positive_trace())
        self.assertEqual(report["status"], "pass")
        self.assertIsNone(report["failure_type"])
        self.assertEqual(report["evidence"][0]["launched_object_id"], "payload")

    def test_missing_release_event_is_rejected(self) -> None:
        trace = positive_trace()
        for frame in trace:
            frame["spring_events"] = []
        report = PhysicsVerifier().verify(case_spec(), trace)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "release_event_present")

    def test_payload_must_move_after_release(self) -> None:
        trace = positive_trace()
        for frame in trace:
            frame["objects"]["payload"]["velocity_m_s"] = [0.0, 0.0, 0.0]
        report = PhysicsVerifier().verify(case_spec(), trace)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "post_release_speed_m_s")

    def test_energy_gain_above_declared_envelope_is_rejected(self) -> None:
        trace = positive_trace()
        trace[-1]["objects"]["payload"]["velocity_m_s"] = [5.0, 0.0, 5.0]
        report = PhysicsVerifier().verify(case_spec(), trace)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "energy_ratio")


def case_spec() -> dict:
    return {
        "schema_version": "harness_case_spec_v1",
        "case_id": "spring_launch_arc",
        "capability_id": "elastic_energy_launch",
        "prompt": "A compressed spring releases a payload upward and forward.",
        "expected_physics": {
            "coordinate_system": "z_up",
            "launcher_object_id": "spring",
            "launched_object_id": "payload",
            "spring_constant_n_m": 120.0,
            "compression_m": 0.18,
            "payload_mass_kg": 0.5,
            "release_frame": 1,
            "release_time_s": 0.2,
            "expected_min_launch_speed_m_s": 1.1,
            "expected_max_energy_ratio": 1.25,
            "expected_min_height_gain_m": 0.18,
            "expected_min_forward_displacement_m": 0.18,
        },
        "objects": [
            {"id": "spring", "role": "elastic_launcher", "shape": "spring_proxy", "spring_constant_n_m": 120.0, "compression_m": 0.18, "initial_position_m": [0.0, 0.0, 0.1], "initial_velocity_m_s": [0.0, 0.0, 0.0]},
            {"id": "payload", "role": "launched_body", "shape": "sphere", "radius_m": 0.12, "mass_kg": 0.5, "initial_position_m": [0.0, 0.0, 0.22], "initial_velocity_m_s": [0.0, 0.0, 0.0]},
            {"id": "floor", "role": "support", "shape": "box", "initial_position_m": [0.0, 0.0, 0.0]},
        ],
        "active_objects": ["spring"],
        "passive_objects": ["payload"],
        "required_assets": ["elastic launcher", "launched rigid body", "support"],
        "required_signals": ["trajectory", "spring_events", "energy_labels"],
        "verifier_expectation": {"status": "pass"},
        "should_pass": True,
        "notes": "Spring launcher is a smoke family for generic elastic-energy release.",
    }


def positive_trace() -> list[dict]:
    return [
        {
            "frame": 0,
            "time_s": 0.0,
            "objects": {
                "spring": {"position_m": [0.0, 0.0, 0.1], "velocity_m_s": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]},
                "payload": {"position_m": [0.0, 0.0, 0.22], "velocity_m_s": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]},
                "floor": {"position_m": [0.0, 0.0, 0.0], "velocity_m_s": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]},
            },
            "contacts": [{"objects": ["payload", "spring"], "frame": 0, "time_s": 0.0}],
            "spring_events": [],
        },
        {
            "frame": 1,
            "time_s": 0.2,
            "objects": {
                "spring": {"position_m": [0.0, 0.0, 0.1], "velocity_m_s": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]},
                "payload": {"position_m": [0.13, 0.0, 0.42], "velocity_m_s": [1.1, 0.0, 1.6], "rotation_deg": [0, 0, 0]},
                "floor": {"position_m": [0.0, 0.0, 0.0], "velocity_m_s": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]},
            },
            "contacts": [],
            "spring_events": [{"event_type": "release", "launcher_id": "spring", "target_id": "payload", "frame": 1, "time_s": 0.2, "compression_m": 0.18}],
        },
        {
            "frame": 2,
            "time_s": 0.4,
            "objects": {
                "spring": {"position_m": [0.0, 0.0, 0.1], "velocity_m_s": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]},
                "payload": {"position_m": [0.34, 0.0, 0.68], "velocity_m_s": [0.8, 0.0, 0.7], "rotation_deg": [0, 0, 0]},
                "floor": {"position_m": [0.0, 0.0, 0.0], "velocity_m_s": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]},
            },
            "contacts": [],
            "spring_events": [],
        },
    ]


if __name__ == "__main__":
    unittest.main()
