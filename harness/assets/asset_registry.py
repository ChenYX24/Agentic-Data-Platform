from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


class AssetRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.environ.get("SIM_STUDIO_ASSET_REGISTRY") or ROOT / "assets" / "asset_physics_index.json"
        self.path = Path(configured)
        self.assets = self._load()

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        if not self.assets:
            return []
        q = query.casefold().strip()
        tokens = [token for token in re.split(r"[^a-z0-9_]+", q) if token]
        scored = []
        for item in self.assets:
            text = searchable_text(item)
            exact_values = {
                str(item.get(key) or "").casefold()
                for key in ("id", "asset_id", "name", "ue_path")
            }
            score = sum(1 for token in tokens if token in text)
            if q in exact_values:
                score += 20
            elif q and q in text:
                score += 4
            if item.get("materialized"):
                score += 1
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or pair[1].get("name") or "")))
        return [item for _, item in scored[:top_k]]

    def _load(self) -> list[dict[str, Any]]:
        path = self.path
        if not path.exists() and self.path.name == "asset_physics_index.json":
            path = ROOT / "assets" / "asset_registry.example.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [normalize_asset(item) for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            defaults = data.get("provenance_defaults") if isinstance(data.get("provenance_defaults"), dict) else {}
            for key in ("assets", "items", "entries"):
                if isinstance(data.get(key), list):
                    return [normalize_asset(item, defaults) for item in data[key] if isinstance(item, dict)]
        return []


def normalize_asset(item: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = {**(defaults or {}), **item}
    paths = normalized.get("paths") if isinstance(normalized.get("paths"), dict) else {}
    ue = normalized.get("ue") if isinstance(normalized.get("ue"), dict) else {}
    physics = normalized.get("physics") if isinstance(normalized.get("physics"), dict) else {}
    normalized.setdefault("asset_id", normalized.get("id") or normalized.get("name"))
    normalized.setdefault("ue_path", paths.get("ue5") or ue.get("object_path"))
    normalized.setdefault("category", normalized.get("category_l1"))
    normalized.setdefault("type", normalized.get("asset_kind") or ue.get("class_name"))
    normalized.setdefault("thumbnail", paths.get("thumbnail"))
    normalized.setdefault("mass_kg", physics.get("estimated_mass_kg"))
    normalized.setdefault("collision_profile", physics.get("collision_profile"))
    normalized.setdefault("collider", physics.get("collider"))
    if not isinstance(normalized.get("material"), dict) and isinstance(physics.get("material_properties"), dict):
        normalized["material"] = physics["material_properties"]
    if not normalized.get("source_uri") and normalized.get("source_kind") == "engine_builtin" and normalized.get("ue_path"):
        normalized["source_uri"] = f"ue://{str(normalized['ue_path']).lstrip('/')}"
    return normalized


def searchable_text(item: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "id",
        "asset_id",
        "name",
        "description",
        "semantic_name",
        "path",
        "ue_path",
        "tags",
        "aliases",
        "usage_groups",
        "category",
        "category_l1",
        "category_l2",
        "type",
        "collider",
        "shape",
    ):
        value = item.get(key)
        if isinstance(value, list):
            values.extend(str(entry) for entry in value)
        elif isinstance(value, dict):
            values.extend(str(entry) for entry in value.values())
        elif value is not None:
            values.append(str(value))
    return " ".join(values).casefold()
