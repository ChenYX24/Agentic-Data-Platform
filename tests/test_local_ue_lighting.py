from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scripts.harness_local_ue_runner import default_lighting_controls


class LocalUELightingTests(unittest.TestCase):
    def test_balanced_fill_is_brighter_than_data_neutral(self) -> None:
        with patch.dict(os.environ, {"SIM_STUDIO_UE_LIGHTING_PRESET": "data_neutral"}, clear=False):
            neutral = default_lighting_controls("data")
        with patch.dict(os.environ, {"SIM_STUDIO_UE_LIGHTING_PRESET": "map_lights_balanced_fill"}, clear=False):
            balanced = default_lighting_controls("data")

        self.assertGreater(balanced["sun_intensity"], neutral["sun_intensity"])
        self.assertGreater(balanced["fill_intensity"], neutral["fill_intensity"])
        self.assertEqual(balanced["preset"], "map_lights_balanced_fill")

    def test_explicit_intensity_overrides_preset(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SIM_STUDIO_UE_LIGHTING_PRESET": "map_lights_balanced_fill",
                "SIM_STUDIO_UE_SUN_INTENSITY": "36.5",
                "SIM_STUDIO_UE_EXPOSURE_BIAS": "0.8",
            },
            clear=False,
        ):
            controls = default_lighting_controls("data")

        self.assertEqual(controls["sun_intensity"], 36.5)
        self.assertEqual(controls["exposure_bias"], 0.8)

    def test_case_lighting_preset_is_used_without_environment_override(self) -> None:
        case_spec = {"scene": {"lighting_preset": "map_lights_balanced_fill"}}
        with patch.dict(os.environ, {}, clear=True):
            controls = default_lighting_controls("data", case_spec)

        self.assertEqual(controls["preset"], "map_lights_balanced_fill")
        self.assertEqual(controls["sun_intensity"], 48.0)


if __name__ == "__main__":
    unittest.main()
