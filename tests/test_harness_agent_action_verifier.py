from __future__ import annotations

import unittest
from pathlib import Path

from harness.core.case_spec import load_case_spec
from harness.runtime.fallback_backend import trajectory_for_case
from harness.verification.physics_verifier import PhysicsVerifier


ROOT = Path(__file__).resolve().parents[1]


class HarnessAgentActionVerifierTests(unittest.TestCase):
    def verify_case(self, rel_path: str) -> dict:
        case = load_case_spec(ROOT / rel_path)
        trajectory = trajectory_for_case(case.data)
        return PhysicsVerifier().verify(case.data, trajectory)

    def test_positive_agent_action_cases_pass(self) -> None:
        for rel_path in (
            "cases/agent_action/agent_push_box_contact.json",
            "cases/agent_action/agent_throw_ball_release.json",
        ):
            report = self.verify_case(rel_path)
            self.assertEqual(report["status"], "pass", rel_path)
            self.assertIsNone(report["failure_type"])
            self.assertTrue(report["evidence"])

    def test_target_preaction_motion_is_rejected(self) -> None:
        report = self.verify_case("cases/agent_action/negative_target_preaction_motion.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F5_passive_precontact_motion")
        self.assertEqual(report["first_failure"]["metric"], "preaction_velocity_m_s")

    def test_missing_action_trace_is_rejected(self) -> None:
        report = self.verify_case("cases/agent_action/negative_missing_action_trace.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F7_runtime_artifact_incomplete")
        self.assertEqual(report["first_failure"]["metric"], "action_trace_count")

    def test_no_post_action_motion_is_rejected(self) -> None:
        report = self.verify_case("cases/agent_action/negative_no_post_action_motion.json")
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_type"], "F4_causality_violation")
        self.assertEqual(report["first_failure"]["metric"], "post_action_response")


if __name__ == "__main__":
    unittest.main()
