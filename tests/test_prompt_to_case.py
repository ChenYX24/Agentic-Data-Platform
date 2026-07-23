from __future__ import annotations

import unittest

from harness.core.case_spec import validate_case_spec
from harness.planning.prompt_to_case import prompt_to_case


class PromptToCaseTests(unittest.TestCase):
    def test_billiards_prompt_compiles_to_executable_reviewable_case(self) -> None:
        case = prompt_to_case("A cue ball hits a stationary billiard ball at 3 m/s", case_id="prompt_billiards")

        validate_case_spec(case)
        self.assertTrue(case["objects"])
        self.assertTrue(case["expected_physics"]["needs_agent_review"])
        cue = next(item for item in case["objects"] if item["id"] == "cue_ball")
        self.assertEqual(cue["initial_velocity_m_s"], [3.0, 0.0, 0.0])
        self.assertIn("segmentation", case["required_signals"])

    def test_empty_prompt_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            prompt_to_case("  ")

    def test_english_fluid_prompt_reaches_the_fluid_case_template(self) -> None:
        case = prompt_to_case("A water drop splashes into a rigid basin", case_id="prompt_fluid_en")

        validate_case_spec(case)
        self.assertEqual(case["capability_id"], "fluid_particle_dynamics")
        self.assertEqual(case["task_type"], "fluid_drop_in_basin")
        self.assertEqual(case["planning_trace"]["execution_strategy"]["preferred_runtime"], "GenesisSPH")

    def test_chinese_fluid_prompt_reaches_the_fluid_case_template(self) -> None:
        case = prompt_to_case("一团流体落入刚性盆中并产生水花", case_id="prompt_fluid_zh")

        validate_case_spec(case)
        self.assertEqual(case["capability_id"], "fluid_particle_dynamics")
        self.assertEqual(case["objects"][0]["role"], "fluid_volume")


if __name__ == "__main__":
    unittest.main()
