from __future__ import annotations

import unittest

from harness.core.capability import CapabilityStore


class HarnessCapabilitySchemaTests(unittest.TestCase):
    def test_all_capabilities_are_schema_valid(self) -> None:
        capabilities = CapabilityStore().list()
        self.assertGreaterEqual(len(capabilities), 6)
        ids = {item.id for item in capabilities}
        self.assertIn("billiard_causality_compiler", ids)
        self.assertIn("asset_intent_resolution", ids)


if __name__ == "__main__":
    unittest.main()
