from __future__ import annotations

from copy import deepcopy
import unittest

from harness.verification.physics_verifier import PhysicsVerifier


class HarnessBrittleFractureVerifierTests(unittest.TestCase):
    def test_brittle_impact_fracture_trace_passes(self) -> None:
        report = PhysicsVerifier().verify(case_spec(), passing_trace())
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["evidence"][0]["fractured_object_id"], "glass_panel")
        self.assertGreaterEqual(report["evidence"][0]["fragment_count"], 6)

    def test_missing_fracture_event_fails(self) -> None:
        trace = passing_trace()
        for frame in trace:
            frame["fracture_events"] = []
            frame["fragments"] = []
        report = PhysicsVerifier().verify(case_spec(), trace)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "fracture_event_present")

    def test_fracture_before_contact_fails(self) -> None:
        trace = passing_trace()
        trace[0]["fracture_events"] = [fracture_event(frame_id=0, time_s=0.0, fragment_count=6, impact_energy_j=4.8)]
        trace[1]["fracture_events"] = []
        report = PhysicsVerifier().verify(case_spec(), trace)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "fracture_frame_before_contact")

    def test_fracture_below_threshold_fails(self) -> None:
        trace = passing_trace()
        trace[1]["contacts"][0]["impact_energy_j"] = 0.7
        trace[1]["fracture_events"][0]["impact_energy_j"] = 0.7
        report = PhysicsVerifier().verify(case_spec(), trace)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "impact_energy_j")

    def test_too_few_fragments_fails(self) -> None:
        trace = passing_trace()
        trace[1]["fracture_events"][0]["fragment_count"] = 2
        for frame in trace[1:]:
            frame["fragments"] = frame["fragments"][:2]
        report = PhysicsVerifier().verify(case_spec(), trace)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "fragment_count")

    def test_external_strain_trace_passes(self) -> None:
        report = PhysicsVerifier().verify(strain_case_spec(), strain_trace())
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["evidence"][0]["external_strain"], 750000.0)
        self.assertEqual(report["evidence"][0]["damage_threshold"], 500000.0)

    def test_energy_response_selects_shatter_level_from_measured_energy(self) -> None:
        spec = strain_case_spec()
        response = spec["objects"][1]["fracture_response"]
        response.pop("external_strain")
        response["energy_response_levels"] = [
            {"damage_state": "cracked", "minimum_impact_energy_j": 2.0, "external_strain": 525000.0},
            {"damage_state": "shattered", "minimum_impact_energy_j": 10.0, "external_strain": 900000.0},
            {"damage_state": "burst", "minimum_impact_energy_j": 25.0, "external_strain": 2500000.0},
        ]
        trace = strain_trace()
        add_energy_gate_evidence(trace, energy_j=16.0, threshold_j=10.0, gate_passed=True)
        trace[1]["contacts"][0]["damage_state"] = "shattered"
        trace[2]["fracture_events"][0].update({"external_strain": 900000.0, "damage_state": "shattered"})

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["evidence"][0]["damage_state"], "shattered")

    def test_external_strain_reads_compiled_runtime_response(self) -> None:
        spec = strain_case_spec()
        spec["dynamic_objects"] = [
            {"id": obj["id"], "params": {"role": obj["role"], **({"fracture_response": obj["fracture_response"]} if "fracture_response" in obj else {})}}
            for obj in spec.pop("objects")
        ]
        self.assertEqual(PhysicsVerifier().verify(spec, strain_trace())["status"], "pass")

    def test_external_strain_allows_break_on_contact_frame(self) -> None:
        trace = strain_trace()
        trace[1]["fracture_events"] = trace[2].pop("fracture_events")
        trace[1]["fragments"] = trace[2].pop("fragments")
        trace[1]["fracture_events"][0].update({"frame": 1, "time_s": 0.1})
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["status"], "pass")

    def test_external_strain_rejects_break_before_contact(self) -> None:
        trace = strain_trace()
        trace[0]["fracture_events"] = trace[2].pop("fracture_events")
        trace[0]["fragments"] = trace[2].pop("fragments")
        trace[0]["fracture_events"][0].update({"frame": 0, "time_s": 0.0})
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "fracture_frame_before_contact")

    def test_external_strain_requires_native_collision_evidence(self) -> None:
        trace = strain_trace()
        trace[1]["contacts"][0].pop("native_collision")
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "native_collision_present")

    def test_external_strain_ignores_earlier_bounds_diagnostic_when_native_hit_follows(self) -> None:
        trace = strain_trace()
        trace[0]["contacts"] = [
            {
                "objects": ["steel_ball", "glass_panel"],
                "method": "ue_postsolve_bounds_inference",
                "raw_method": "adp_cpp_runtime_bounds_overlap_or_near_contact",
                "native_collision": False,
            }
        ]

        report = PhysicsVerifier().verify(strain_case_spec(), trace)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["evidence"][0]["contact_frame"], 1)

    def test_external_strain_below_energy_gate_stays_intact(self) -> None:
        spec = strain_case_spec()
        spec["objects"][1]["fracture_response"]["minimum_impact_energy_j"] = 5.0
        spec["expected_physics"]["expected_fracture"] = False
        trace = strain_trace()
        add_energy_gate_evidence(trace, energy_j=2.0, threshold_j=5.0, gate_passed=False)
        trace[2]["fracture_events"] = []
        trace[2]["fragments"] = []

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["evidence"][0]["fractured"])
        self.assertEqual(report["evidence"][0]["impact_energy_j"], 2.0)

    def test_external_strain_rejects_fracture_below_energy_gate(self) -> None:
        spec = strain_case_spec()
        spec["objects"][1]["fracture_response"]["minimum_impact_energy_j"] = 5.0
        trace = strain_trace()
        add_energy_gate_evidence(trace, energy_j=2.0, threshold_j=5.0, gate_passed=False)

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "fracture_below_impact_energy_gate")

    def test_external_strain_energy_gate_requires_precontact_provenance(self) -> None:
        spec = strain_case_spec()
        spec["objects"][1]["fracture_response"]["minimum_impact_energy_j"] = 5.0
        trace = strain_trace()
        trace[1]["contacts"][0]["impact_energy_j"] = 2.0
        trace[2]["fracture_events"] = []
        trace[2]["fragments"] = []

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "energy_model")

    def test_external_strain_rejects_low_energy_strain_command(self) -> None:
        spec = strain_case_spec()
        spec["objects"][1]["fracture_response"]["minimum_impact_energy_j"] = 5.0
        trace = strain_trace()
        add_energy_gate_evidence(trace, energy_j=2.0, threshold_j=5.0, gate_passed=False)
        trace[1]["contacts"][0]["external_strain_applied"] = True
        trace[2]["fracture_events"] = []
        trace[2]["fragments"] = []

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "external_strain_applied_matches_gate")

    def test_declared_intact_external_strain_case_rejects_break(self) -> None:
        spec = strain_case_spec()
        spec["expected_physics"]["expected_fracture"] = False
        spec["objects"][1]["fracture_response"]["minimum_impact_energy_j"] = 5.0
        trace = strain_trace()
        add_energy_gate_evidence(trace, energy_j=8.0, threshold_j=5.0, gate_passed=True)

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "unexpected_fracture")

    def test_declared_fracture_external_strain_case_rejects_low_energy_intact(self) -> None:
        spec = strain_case_spec()
        spec["expected_physics"]["expected_fracture"] = True
        spec["objects"][1]["fracture_response"]["minimum_impact_energy_j"] = 5.0
        trace = strain_trace()
        add_energy_gate_evidence(trace, energy_j=2.0, threshold_j=5.0, gate_passed=False)
        trace[2]["fracture_events"] = []
        trace[2]["fragments"] = []

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "expected_fracture")

    def test_external_strain_requires_runtime_damage_threshold(self) -> None:
        trace = strain_trace()
        trace[2]["fracture_events"][0].pop("damage_thresholds_runtime")
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "runtime_damage_threshold_present")

    def test_external_strain_requires_root_break(self) -> None:
        trace = strain_trace()
        trace[2]["fracture_events"][0]["root_broken"] = False
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "root_broken")

    def test_external_strain_requires_native_break_event(self) -> None:
        trace = strain_trace()
        trace[2]["fracture_events"][0].pop("native_break_event")
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "native_break_event_present")

    def test_external_strain_must_match_config(self) -> None:
        trace = strain_trace()
        trace[2]["fracture_events"][0]["external_strain"] = 700000.0
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "external_strain_matches_config")

    def test_external_strain_must_exceed_damage_threshold(self) -> None:
        spec = strain_case_spec()
        spec["objects"][1]["fracture_response"]["external_strain"] = 400000.0
        trace = strain_trace()
        trace[2]["fracture_events"][0]["external_strain"] = 400000.0
        report = PhysicsVerifier().verify(spec, trace)
        self.assertEqual(report["failure_type"], "F3_invalid_initial_physics_state")
        self.assertEqual(report["first_failure"]["metric"], "external_strain_below_damage_threshold")

    def test_external_strain_requires_fragment_count_and_manifest(self) -> None:
        for missing, metric in (("count", "fragment_count_present"), ("manifest", "fragment_manifest_present")):
            with self.subTest(missing=missing):
                trace = deepcopy(strain_trace())
                if missing == "count":
                    trace[2]["fracture_events"][0].pop("fragment_count")
                else:
                    trace[2]["fragments"] = []
                report = PhysicsVerifier().verify(strain_case_spec(), trace)
                self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
                self.assertEqual(report["first_failure"]["metric"], metric)

    def test_external_strain_rejects_anonymous_fragment_lineage(self) -> None:
        trace = strain_trace()
        trace[2]["fragments"][0].pop("fragment_id")
        report = PhysicsVerifier().verify(strain_case_spec(), trace)
        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "fragment_lineage_complete")

    def test_impact_centered_fracture_matches_native_contact_point(self) -> None:
        spec = strain_case_spec()
        spec["objects"][1]["fracture_response"]["center_source"] = "native_contact_impact_point"
        trace = strain_trace()
        trace[1]["contacts"][0]["impact_point_cm"] = [10.0, 20.0, 30.0]
        trace[2]["fracture_events"][0].update(
            {
                "fracture_center_cm": [10.0, 20.0, 30.0],
                "fracture_center_source": "native_contact_impact_point",
            }
        )

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["evidence"][0]["fracture_center_error_cm"], 0.0)

    def test_impact_centered_fracture_rejects_fixed_or_shifted_center(self) -> None:
        spec = strain_case_spec()
        spec["objects"][1]["fracture_response"].update(
            {"center_source": "native_contact_impact_point", "fracture_center_tolerance_cm": 0.1}
        )
        trace = strain_trace()
        trace[1]["contacts"][0]["impact_point_cm"] = [10.0, 20.0, 30.0]
        trace[2]["fracture_events"][0].update(
            {
                "fracture_center_cm": [10.0, 20.0, 31.0],
                "fracture_center_source": "native_contact_impact_point",
            }
        )

        report = PhysicsVerifier().verify(spec, trace)

        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "fracture_center_matches_native_impact_point")


def case_spec() -> dict:
    return {
        "schema_version": "harness_case_spec_v1",
        "case_id": "brittle_fracture_unit",
        "capability_id": "brittle_impact_fracture",
        "prompt": "A striker hits a brittle glass panel and it fractures only after impact energy exceeds threshold.",
        "expected_physics": {
            "impactor_object_id": "striker",
            "brittle_object_id": "glass_panel",
            "fracture_threshold_j": 2.4,
            "expected_min_fragment_count": 6,
            "expected_contact_pair": ["striker", "glass_panel"],
        },
        "objects": [
            {"id": "striker", "role": "active_impactor", "shape": "sphere", "mass_kg": 1.2, "initial_position_m": [-0.6, 0.0, 0.4], "initial_velocity_m_s": [2.8, 0.0, 0.0]},
            {"id": "glass_panel", "role": "brittle_fracture_body", "shape": "thin_box", "mass_kg": 0.7, "fracture_threshold_j": 2.4, "initial_position_m": [0.0, 0.0, 0.4], "initial_velocity_m_s": [0.0, 0.0, 0.0]},
        ],
        "active_objects": ["striker"],
        "passive_objects": ["glass_panel"],
        "required_assets": ["impactor rigid body", "brittle fracture body", "fracture fragments"],
        "required_signals": ["trajectory", "contact_events", "fracture_events", "fragment_manifest", "energy_labels"],
        "verifier_expectation": {"status": "pass"},
        "should_pass": True,
        "notes": "Unit fixture for brittle impact fracture verifier.",
    }


def passing_trace() -> list[dict]:
    return [
        {
            "frame": 0,
            "time_s": 0.0,
            "objects": {
                "striker": {"position_m": [-0.6, 0.0, 0.4], "velocity_m_s": [2.8, 0.0, 0.0]},
                "glass_panel": {"position_m": [0.0, 0.0, 0.4], "velocity_m_s": [0.0, 0.0, 0.0]},
            },
            "contacts": [],
            "fracture_events": [],
            "fragments": [],
        },
        {
            "frame": 1,
            "time_s": 0.2,
            "objects": {
                "striker": {"position_m": [-0.05, 0.0, 0.4], "velocity_m_s": [0.4, 0.0, 0.0]},
                "glass_panel": {"position_m": [0.0, 0.0, 0.4], "velocity_m_s": [0.0, 0.0, 0.0]},
            },
            "contacts": [{"objects": ["striker", "glass_panel"], "frame": 1, "time_s": 0.2, "impact_energy_j": 4.8, "normal_impulse_n_s": 2.2}],
            "fracture_events": [fracture_event(frame_id=1, time_s=0.2, fragment_count=6, impact_energy_j=4.8)],
            "fragments": [{"fragment_id": f"glass_panel_frag_{idx}", "source_object_id": "glass_panel"} for idx in range(6)],
        },
        {
            "frame": 2,
            "time_s": 0.4,
            "objects": {
                "striker": {"position_m": [0.05, 0.0, 0.4], "velocity_m_s": [0.1, 0.0, 0.0]},
                "glass_panel": {"position_m": [0.0, 0.0, 0.4], "velocity_m_s": [0.0, 0.0, 0.0], "fractured": True},
            },
            "contacts": [],
            "fracture_events": [],
            "fragments": [{"fragment_id": f"glass_panel_frag_{idx}", "source_object_id": "glass_panel"} for idx in range(6)],
        },
    ]


def fracture_event(*, frame_id: int, time_s: float, fragment_count: int, impact_energy_j: float) -> dict:
    return {
        "event_type": "fracture",
        "object_id": "glass_panel",
        "caused_by_object_id": "striker",
        "frame": frame_id,
        "time_s": time_s,
        "impact_energy_j": impact_energy_j,
        "fracture_threshold_j": 2.4,
        "fragment_count": fragment_count,
    }


def strain_case_spec() -> dict:
    return {
        "schema_version": "harness_case_spec_v1",
        "case_id": "external_strain_fracture_unit",
        "capability_id": "brittle_impact_fracture",
        "expected_physics": {
            "impactor_object_id": "striker",
            "brittle_object_id": "glass_panel",
            "expected_min_fragment_count": 3,
        },
        "objects": [
            {"id": "striker", "role": "active_impactor"},
            {
                "id": "glass_panel",
                "role": "brittle_fracture_body",
                "fracture_response": {
                    "mode": "contact_external_strain",
                    "impactor_id": "striker",
                    "external_strain": 750000.0,
                    "damage_thresholds": [500000.0, 50000.0, 5000.0],
                },
            },
        ],
    }


def strain_trace() -> list[dict]:
    return [
        {"frame": 0, "time_s": 0.0, "contacts": [], "fracture_events": [], "fragments": []},
        {
            "frame": 1,
            "time_s": 0.1,
            "contacts": [{"objects": ["striker", "glass_panel"], "frame": 1, "time_s": 0.1, "native_collision": True, "method": "ue_native_collision_event"}],
            "fracture_events": [],
            "fragments": [],
        },
        {
            "frame": 2,
            "time_s": 0.2,
            "contacts": [],
            "fracture_events": [{
                "event_type": "fracture",
                "object_id": "glass_panel",
                "frame": 2,
                "time_s": 0.2,
                "root_broken": True,
                "native_break_event": True,
                "source": "ue_native_chaos_break_event",
                "external_strain": 750000.0,
                "damage_thresholds_runtime": [500000.0, 50000.0, 5000.0],
                "damage_threshold_source": "ue_geometry_collection_asset",
                "fragment_count": 3,
            }],
            "fragments": [{"fragment_id": f"glass_panel_frag_{idx}", "source_object_id": "glass_panel"} for idx in range(3)],
        },
    ]


def add_energy_gate_evidence(
    trace: list[dict],
    *,
    energy_j: float,
    threshold_j: float,
    gate_passed: bool,
) -> None:
    trace[1]["contacts"][0].update(
        {
            "impact_energy_j": energy_j,
            "minimum_impact_energy_j": threshold_j,
            "energy_model": "ue_component_precontact_sample_translational_energy",
            "energy_sample_frame": 0,
            "energy_gate_passed": gate_passed,
            "external_strain_applied": gate_passed,
        }
    )


if __name__ == "__main__":
    unittest.main()
