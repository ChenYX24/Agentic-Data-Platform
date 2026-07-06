"""Agent-facing physics-aware simulation harness."""

from harness.core.capability import Capability, CapabilityStore
from harness.core.case_spec import CaseSpec, load_case_spec, validate_case_spec
from harness.verification.physics_verifier import PhysicsVerifier

__all__ = [
    "Capability",
    "CapabilityStore",
    "CaseSpec",
    "PhysicsVerifier",
    "load_case_spec",
    "validate_case_spec",
]
