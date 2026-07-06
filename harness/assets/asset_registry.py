from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


class AssetRegistry:
    def __init__(self, path: str | Path = ROOT / "assets" / "asset_physics_index.json") -> None:
        self.path = Path(path)
        self.assets = self._load()

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        if not self.assets:
            return []
        q = query.casefold()
        scored = []
        for item in self.assets:
            text = " ".join(str(item.get(key, "")) for key in ("id", "name", "path", "tags", "category")).casefold()
            score = sum(1 for token in q.split() if token and token in text)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or pair[1].get("name") or "")))
        return [item for _, item in scored[:top_k]]

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("assets", "items", "entries"):
                if isinstance(data.get(key), list):
                    return [item for item in data[key] if isinstance(item, dict)]
        return []
