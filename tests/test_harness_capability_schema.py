from __future__ import annotations

import unittest

from harness.core.capability import CapabilityStore, canonical_capability_id


class HarnessCapabilitySchemaTests(unittest.TestCase):
    def test_all_capabilities_are_schema_valid(self) -> None:
        capabilities = CapabilityStore().list()
        self.assertGreaterEqual(len(capabilities), 6)
        ids = {item.id for item in capabilities}
        self.assertIn("rigid_body_contact_causality", ids)
        self.assertIn("prompt_case_capability_planning", ids)
        self.assertIn("explicit_physics_control_surface", ids)
        self.assertIn("physics_verifier_truth_gate", ids)
        self.assertIn("canonical_signal_capture", ids)
        self.assertIn("dataset_artifact_packaging", ids)
        self.assertIn("asset_intent_resolution", ids)
        self.assertIn("pipeline_stage_orchestration", ids)
        self.assertIn("physics_property_constraint_validation", ids)
        self.assertIn("asset_runtime_binding_invocation", ids)
        self.assertIn("runtime_actor_placement_compilation", ids)
        self.assertIn("runtime_backend_execution", ids)
        self.assertIn("render_signal_sync_validation", ids)
        self.assertIn("bounce_restitution_ball", ids)
        self.assertIn("rolling_friction_ball", ids)
        self.assertIn("sliding_crate_friction", ids)
        self.assertIn("force_field_wind_drift", ids)
        self.assertIn("magnetic_force_field", ids)
        self.assertIn("mass_ratio_momentum_transfer", ids)
        self.assertIn("angular_damping_spin_decay", ids)
        self.assertIn("agent_rigidbody_action_coupling", ids)
        self.assertIn("constraint_distance_pendulum_motion", ids)
        self.assertIn("constraint_momentum_transfer", ids)
        self.assertIn("elastic_energy_launch", ids)
        self.assertIn("elastic_constraint_rebound", ids)
        self.assertIn("brittle_impact_fracture", ids)
        self.assertNotIn("billiard_causality_compiler", ids)
        contact = next(item for item in capabilities if item.id == "rigid_body_contact_causality")
        self.assertEqual(contact.capability_type, "physics_constraint")
        placement = next(item for item in capabilities if item.id == "runtime_actor_placement_compilation")
        self.assertEqual(placement.capability_type, "pipeline_stage")
        runtime = next(item for item in capabilities if item.id == "runtime_backend_execution")
        self.assertEqual(runtime.capability_type, "pipeline_stage")
        render_sync = next(item for item in capabilities if item.id == "render_signal_sync_validation")
        self.assertEqual(render_sync.capability_type, "verification")
        elastic = next(item for item in capabilities if item.id == "elastic_energy_launch")
        self.assertEqual(elastic.capability_type, "physics_constraint")
        elastic_constraint = next(item for item in capabilities if item.id == "elastic_constraint_rebound")
        self.assertEqual(elastic_constraint.capability_type, "physics_constraint")
        fracture = next(item for item in capabilities if item.id == "brittle_impact_fracture")
        self.assertEqual(fracture.capability_type, "physics_constraint")
        self.assertIn("cases/fracture/glass_impact_position_matrix/left_x_m0p45.json", fracture.smoke_cases)
        self.assertIn("cases/fracture/glass_impact_position_matrix/right_x_p0p45.json", fracture.smoke_cases)
        magnetic = next(item for item in capabilities if item.id == "magnetic_force_field")
        self.assertEqual(magnetic.capability_type, "physics_constraint")

    def test_deprecated_scene_alias_is_canonicalized_without_being_active(self) -> None:
        self.assertEqual(canonical_capability_id("billiard_causality_compiler"), "rigid_body_contact_causality")
        self.assertEqual(canonical_capability_id("rigid_body_contact_causality"), "rigid_body_contact_causality")


if __name__ == "__main__":
    unittest.main()
