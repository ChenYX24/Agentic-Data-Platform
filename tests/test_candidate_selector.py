from __future__ import annotations

import unittest

from harness.verification.candidate_selector import choose_best_candidate


class CandidateSelectorTests(unittest.TestCase):
    def test_passed_candidate_beats_higher_scoring_failure(self) -> None:
        rows = [
            {"attempt": 1, "quality": {"hard_gate_passed": False, "hard_gate": {"failure_count": 1}, "ranking": {"technical_score": None}}},
            {"attempt": 2, "quality": {"hard_gate_passed": True, "hard_gate": {"failure_count": 0}, "ranking": {"technical_score": 78.0}}},
            {"attempt": 3, "quality": {"hard_gate_passed": True, "hard_gate": {"failure_count": 0}, "ranking": {"technical_score": 82.0}}},
        ]

        self.assertEqual(choose_best_candidate(rows)["attempt"], 3)

    def test_all_failed_keeps_fewest_failures(self) -> None:
        rows = [
            {"attempt": 1, "quality": {"hard_gate_passed": False, "hard_gate": {"failure_count": 4}}},
            {"attempt": 2, "quality": {"hard_gate_passed": False, "hard_gate": {"failure_count": 2}}},
        ]

        self.assertEqual(choose_best_candidate(rows)["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
