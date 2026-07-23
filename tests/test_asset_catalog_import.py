from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("import_adp_asset_index", ROOT / "scripts" / "import_adp_asset_index.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AssetCatalogImportTests(unittest.TestCase):
    def test_catalog_groups_dependencies_and_map_preview_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "AssetIndex" / "thumbnails").mkdir(parents=True)
            (source / "Content" / "Maps").mkdir(parents=True)
            (source / "Content" / "Props").mkdir(parents=True)
            (source / "Content" / "Maps" / "Day.umap").write_bytes(b"map")
            (source / "Content" / "Props" / "Ball.uasset").write_bytes(b"asset")
            (source / "AssetIndex" / "thumbnails" / "ball.png").write_bytes(b"png")
            (source / "AssetIndex" / "thumbnails" / "Game__Maps__Day.png").write_bytes(b"png")
            index = {
                "/Game/Maps/Day": {"asset_name": "Day", "ue_class": "World", "category": "Maps", "dependencies": []},
                "/Game/Props/Ball": {
                    "asset_name": "Ball",
                    "semantic_name": "billiard ball",
                    "full_description": "Glossy resin billiard ball",
                    "ue_class": "StaticMesh",
                    "category": "Props",
                    "tags": ["ball", "billiard"],
                    "thumbnail": "AssetIndex/thumbnails/ball.png",
                    "dependencies": ["/Game/Props/Materials/M_Ball"],
                    "estimated_mass_kg": 0.17,
                },
            }
            (source / "AssetIndex" / "ASSETS_INDEX.json").write_text(json.dumps(index), encoding="utf-8")

            registry = MODULE.build_registry(source)
            groups = MODULE.build_group_index(registry)
            maps = MODULE.build_scenario_manifest(registry)

            ball = next(asset for asset in registry["assets"] if asset["name"] == "Ball")
            day = next(asset for asset in registry["assets"] if asset["name"] == "Day")
            self.assertTrue(ball["materialized"])
            self.assertTrue(ball["paths"]["thumbnail"].endswith("ball.png"))
            self.assertTrue(day["paths"]["thumbnail"].endswith("Game__Maps__Day.png"))
            self.assertIn(ball["asset_id"], groups["usage_groups"]["prop/ball"])
            self.assertEqual(maps["schema_version"], "map_catalog.v1")
            self.assertEqual(maps["maps"][0]["preview_presets"][2]["runtime_status"], "planned_unverified")


if __name__ == "__main__":
    unittest.main()
