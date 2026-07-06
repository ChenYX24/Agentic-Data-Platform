from __future__ import annotations

import unittest

from harness.assets.asset_intent import intent_from_object


class HarnessAssetIntentTests(unittest.TestCase):
    def test_physics_critical_and_visual_only_classification(self) -> None:
        rigid = intent_from_object({"id": "ball", "role": "passive_target", "shape": "sphere"})
        visual = intent_from_object({"id": "label", "role": "decal", "asset_query": "logo decal"})
        self.assertTrue(rigid.physics_critical)
        self.assertIn("collider", rigid.required_properties)
        self.assertFalse(visual.physics_critical)
        self.assertEqual(visual.category, "visual_only")


if __name__ == "__main__":
    unittest.main()
