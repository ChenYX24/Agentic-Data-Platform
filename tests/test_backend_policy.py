from __future__ import annotations

import unittest

from harness.runtime.backend_policy import backend_plan


class BackendPolicyTests(unittest.TestCase):
    def test_validated_rigid_and_planned_advanced_backends_are_explicit(self) -> None:
        self.assertEqual(backend_plan("rigid_body_contact_causality")["status"], "validated")
        self.assertEqual(
            backend_plan("rigid_body_contact_causality")["preferred_backend"],
            "ue_chaos_initial_state",
        )
        self.assertEqual(
            backend_plan("rigid_body_contact_causality")["validation_backend"],
            "mujoco_rigid",
        )
        self.assertEqual(backend_plan("fluid_particle_dynamics")["preferred_backend"], "genesis_sph")
        self.assertEqual(backend_plan("fluid_particle_dynamics")["status"], "prototype_validated")
        self.assertEqual(backend_plan("fluid_particle_dynamics")["validation_backend"], "sphinxsys")
        self.assertEqual(backend_plan("elastic_constraint_rebound")["preferred_backend"], "mujoco_constraint_adapter")
        self.assertEqual(backend_plan("elastic_constraint_rebound")["status"], "prototype_validated")
        self.assertEqual(backend_plan("elastic_constraint_rebound")["coupling_contract"], "rigid_transforms_constraint_trace")
        self.assertEqual(backend_plan("brittle_impact_fracture")["preferred_backend"], "ue_chaos_destruction")
        self.assertEqual(backend_plan("soft_body_deformation")["preferred_backend"], "taichi_cloth")
        self.assertEqual(backend_plan("soft_body_deformation")["status"], "prototype_validated")
        self.assertEqual(
            backend_plan("soft_body_deformation")["coupling_contract"],
            "vertices_to_fixed_topology_mesh_cache",
        )
        self.assertFalse(backend_plan("magnetic_force_field")["fallback_is_reference_truth"])

    def test_unknown_capability_is_not_silently_routed(self) -> None:
        self.assertEqual(backend_plan("unknown_effect")["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
