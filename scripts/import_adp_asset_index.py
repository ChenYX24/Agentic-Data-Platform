#!/usr/bin/env python3
"""Import the AgenticDataPlatform AssetIndex into Simulator Studio manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SOURCE_NAME = "agenticdataplatform_asset_index"
DEFAULT_QUERIES = [
    "water plane",
    "ball sphere",
    "MarketEnvironment Day",
    "traffic cone",
    "wood crate",
    "gas station",
    "gear metal",
    "bottle domino",
]
QUERY_ALIASES = {
    "football": ("football", "soccer", "ball", "sphere", "8ball", "8-ball"),
    "soccer": ("soccer", "football", "ball", "sphere", "8ball", "8-ball"),
    "water": ("water", "liquid", "lake", "ocean", "pond", "pool"),
    "map": ("map", "level", "scene", "world"),
    "scene": ("scene", "map", "level", "world"),
    "gas": ("gas", "fuel", "station", "pump"),
    "bottle": ("bottle", "can", "drink", "domino"),
}


def resolve_index_path(source: str | Path) -> Path:
    path = Path(source)
    if path.is_dir():
        return path / "AssetIndex" / "ASSETS_INDEX.json"
    return path


def infer_repo_root(source: str | Path, repo_root: str | Path | None = None) -> Path | None:
    if repo_root:
        return Path(repo_root)
    path = Path(source)
    if path.is_dir() and (path / "AssetIndex" / "ASSETS_INDEX.json").exists():
        return path
    for parent in path.parents:
        if (parent / "AssetIndex" / "ASSETS_INDEX.json").exists() and (parent / "Content").exists():
            return parent
    return None


def asset_key(asset_id: str) -> str:
    return asset_id.strip("/").replace("/", "_").replace(".", "_").lower()


def object_path(asset_id: str) -> str:
    name = asset_id.rsplit("/", 1)[-1]
    return asset_id if "." in name else f"{asset_id}.{name}"


def package_file_path(repo_root: Path | None, package_name: str, class_name: str | None) -> Path | None:
    if not repo_root or not package_name.startswith("/Game/"):
        return None
    ext = ".umap" if class_name == "World" else ".uasset"
    return repo_root / "Content" / f"{package_name.removeprefix('/Game/')}{ext}"


def is_materialized(path: Path | None) -> bool:
    if not path or not path.is_file():
        return False
    return not path.read_bytes()[:80].startswith(b"version https://git-lfs.github.com/spec/v1")


def category_pair(item: dict[str, Any]) -> tuple[str, str]:
    category = str(item.get("category") or "asset").lower()
    subcategory = str(item.get("subcategory") or "generic").lower()
    name = str(item.get("asset_name") or item.get("asset_id") or "").lower()
    tags = " ".join(item.get("tags") or []).lower()
    haystack = f"{category} {subcategory} {name} {tags}"
    if item.get("ue_class") == "World":
        return "map", subcategory
    if "water" in haystack and any(word in haystack for word in ("plane", "material", "water")):
        return "environment", "water"
    if any(word in haystack for word in ("8-ball", "8ball", "sphere", "ball", "pool-ball")):
        return "prop", "ball"
    if any(word in haystack for word in ("chair", "table", "desk", "sofa")):
        if "chair" in haystack:
            return "furniture", "chair"
        if "table" in haystack:
            return "furniture", "table"
        return "furniture", "generic"
    if any(word in haystack for word in ("vehicle", "car", "truck", "bike", "motorcycle")):
        return "vehicle", "generic"
    if any(word in haystack for word in ("character", "mannequin", "citizen", "boy", "adventurer")):
        return "character", "humanoid"
    if category == "props":
        return "prop", subcategory
    if category == "maps":
        return "environment", subcategory
    return category, subcategory


def material_guess(item: dict[str, Any]) -> str:
    haystack = " ".join(
        str(value).lower()
        for value in (
            item.get("asset_name", ""),
            item.get("asset_id", ""),
            item.get("semantic_name", ""),
            item.get("full_description", ""),
            " ".join(item.get("tags") or []),
        )
    )
    for material in ("water", "metal", "steel", "wood", "glass", "rubber", "plastic", "stone", "concrete", "fabric"):
        if material in haystack:
            return "metal" if material == "steel" else material
    return "plastic"


def bbox_size_m(item: dict[str, Any]) -> list[float] | None:
    bbox = (item.get("geometry") or {}).get("bbox_cm")
    if not bbox:
        return None
    return [round(float(value) / 100.0, 5) for value in bbox]


def dependency_file_paths(repo_root: Path | None, dependencies: list[str]) -> list[str]:
    paths: list[str] = []
    for dependency in dependencies:
        dep_file = package_file_path(repo_root, dependency, None)
        if dep_file:
            paths.append(str(dep_file))
    return paths


def convert_asset(asset_id: str, item: dict[str, Any], materialize_repo_root: Path | None, metadata_repo_root: Path | None = None) -> dict[str, Any]:
    category_l1, category_l2 = category_pair(item)
    class_name = item.get("ue_class")
    dependencies = item.get("dependencies") or []
    local_file = package_file_path(materialize_repo_root, asset_id, class_name)
    metadata_file = package_file_path(metadata_repo_root or materialize_repo_root, asset_id, class_name)
    dependency_materialized_count = sum(
        1 for dependency in dependencies if is_materialized(package_file_path(materialize_repo_root, dependency, None))
    )
    return {
        "asset_id": asset_key(asset_id),
        "name": item.get("asset_name") or asset_id.rsplit("/", 1)[-1],
        "description": item.get("full_description") or item.get("semantic_name") or "",
        "category_l1": category_l1,
        "category_l2": category_l2,
        "tags": item.get("tags") or [],
        "bbox_size_m": bbox_size_m(item),
        "physics": {"material": material_guess(item), "estimated_mass_kg": item.get("estimated_mass_kg")},
        "paths": {"ue5": object_path(asset_id), "thumbnail": item.get("thumbnail")},
        "ue": {
            "object_path": object_path(asset_id),
            "package_name": asset_id,
            "package_path": item.get("package_path"),
            "class_name": class_name,
            "dependencies": dependencies,
            "material_paths": [dep for dep in dependencies if "/Material" in dep or "/Materials" in dep],
        },
        "adp": {
            "asset_id": asset_id,
            "semantic_name": item.get("semantic_name"),
            "interaction": item.get("interaction"),
            "estimated_mass_kg": item.get("estimated_mass_kg"),
            "repo_file": str(metadata_file) if metadata_file else None,
            "dependency_files": dependency_file_paths(metadata_repo_root or materialize_repo_root, dependencies),
            "dependency_materialized_count": dependency_materialized_count,
        },
        "source": SOURCE_NAME,
        "materialized": is_materialized(local_file),
    }


def build_registry(
    source: str | Path,
    repo_root: str | Path | None = None,
    metadata_repo_root: str | Path | None = None,
    metadata_source_path: str | Path | None = None,
) -> dict[str, Any]:
    index_path = resolve_index_path(source)
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"ADP index must be a JSON object: {index_path}")
    repo = infer_repo_root(source, repo_root)
    metadata_repo = Path(metadata_repo_root) if metadata_repo_root else repo
    assets = [convert_asset(asset_id, item, repo, metadata_repo) for asset_id, item in raw.items()]
    class_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    materialized_counts = {"materialized": 0, "missing": 0}
    for asset in assets:
        class_name = asset["ue"].get("class_name") or "Unknown"
        class_counts[class_name] = class_counts.get(class_name, 0) + 1
        category = asset["category_l1"]
        category_counts[category] = category_counts.get(category, 0) + 1
        materialized_counts["materialized" if asset.get("materialized") else "missing"] += 1
    return {
        "source": SOURCE_NAME,
        "source_path": str(metadata_source_path or index_path),
        "repo_root": str(metadata_repo) if metadata_repo else None,
        "asset_count": len(assets),
        "assets": assets,
        "class_counts": dict(sorted(class_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "materialized_counts": materialized_counts,
    }


def expanded_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in query.lower().replace("_", " ").replace("-", " ").split():
        for alias in QUERY_ALIASES.get(raw, (raw,)):
            if alias not in terms:
                terms.append(alias)
    return terms


def searchable_text(asset: dict[str, Any]) -> str:
    ue = asset.get("ue") or {}
    adp = asset.get("adp") or {}
    return " ".join(
        str(part)
        for part in (
            asset.get("asset_id", ""),
            asset.get("name", ""),
            asset.get("description", ""),
            asset.get("category_l1", ""),
            asset.get("category_l2", ""),
            " ".join(asset.get("tags") or []),
            ue.get("object_path", ""),
            ue.get("package_path", ""),
            ue.get("class_name", ""),
            adp.get("semantic_name", ""),
        )
    ).lower()


def search_assets(registry: dict[str, Any], query: str, top_k: int = 8, materialized_only: bool = False) -> list[dict[str, Any]]:
    terms = expanded_terms(query)
    results = []
    for asset in registry.get("assets", []):
        if materialized_only and not asset.get("materialized"):
            continue
        text = searchable_text(asset)
        score = sum(1 for term in terms if term in text)
        if query.lower() in text:
            score += 4
        if asset.get("materialized"):
            score += 1
        if score:
            results.append({**asset, "score": score})
    results.sort(key=lambda item: (-int(item["score"]), not bool(item.get("materialized")), str(item.get("name") or "")))
    return results[:top_k]


def compact(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": asset.get("score"),
        "asset_id": asset.get("asset_id"),
        "name": asset.get("name"),
        "category_l1": asset.get("category_l1"),
        "category_l2": asset.get("category_l2"),
        "class_name": asset.get("ue", {}).get("class_name"),
        "ue5_path": asset.get("paths", {}).get("ue5"),
        "materialized": asset.get("materialized"),
        "repo_file": asset.get("adp", {}).get("repo_file"),
        "dependency_count": len(asset.get("ue", {}).get("dependencies") or []),
    }


def build_search_report(registry: dict[str, Any], queries: list[str], top_k: int) -> dict[str, Any]:
    return {
        "source": registry.get("source"),
        "source_path": registry.get("source_path"),
        "repo_root": registry.get("repo_root"),
        "asset_count": registry.get("asset_count"),
        "class_counts": registry.get("class_counts"),
        "category_counts": registry.get("category_counts"),
        "materialized_counts": registry.get("materialized_counts"),
        "queries": {query: [compact(asset) for asset in search_assets(registry, query, top_k=top_k)] for query in queries},
    }


def build_scenario_manifest(registry: dict[str, Any]) -> dict[str, Any]:
    maps = []
    for asset in registry.get("assets", []):
        if asset.get("ue", {}).get("class_name") != "World" and asset.get("category_l1") != "map":
            continue
        deps = asset.get("ue", {}).get("dependencies") or []
        materialized_deps = int((asset.get("adp") or {}).get("dependency_materialized_count") or 0)
        maps.append(
            {
                **compact(asset),
                "dependency_count": len(deps),
                "materialized_dependency_count": materialized_deps,
                "missing_dependency_count": max(len(deps) - materialized_deps, 0),
                "dependencies": deps,
            }
        )
    maps.sort(key=lambda item: (not item.get("materialized"), item.get("name") or ""))
    return {
        "source": registry.get("source"),
        "source_path": registry.get("source_path"),
        "repo_root": registry.get("repo_root"),
        "map_count": len(maps),
        "maps": maps,
    }


def manifest_entry(key: str, asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "asset_id": asset.get("asset_id"),
        "name": asset.get("name"),
        "category_l1": asset.get("category_l1"),
        "category_l2": asset.get("category_l2"),
        "ue5_path": asset.get("paths", {}).get("ue5"),
        "material_path": None,
        "material": (asset.get("physics") or {}).get("material"),
        "tags": list(asset.get("tags") or []),
        "bbox_size_m": asset.get("bbox_size_m"),
        "physics": dict(asset.get("physics") or {}),
        "source": "asset_database_materialized",
        "materialized": asset.get("materialized"),
        "class_name": asset.get("ue", {}).get("class_name"),
        "repo_file": asset.get("adp", {}).get("repo_file"),
    }


def first_materialized(registry: dict[str, Any], queries: tuple[str, ...], class_name: str | None = "StaticMesh") -> dict[str, Any] | None:
    for query in queries:
        for asset in search_assets(registry, query, top_k=20, materialized_only=True):
            if class_name and str(asset.get("ue", {}).get("class_name") or "") != class_name:
                continue
            return asset
    return None


def build_default_manifest(registry: dict[str, Any]) -> dict[str, Any]:
    selection = {
        "water_plane": first_materialized(registry, ("SM_WaterPlane", "water plane")),
        "visual_ball": first_materialized(registry, ("SM_8Ball", "ball sphere", "soccer ball")),
        "sphere": first_materialized(registry, ("SM_8Ball", "ball sphere", "soccer ball")),
        "cube": first_materialized(registry, ("SM_ToothedGear_01", "SM_BigStone_01", "stone")),
        "floor": first_materialized(registry, ("SM_WoodenDisc_01", "SM_WoodenBridge_01", "floor")),
        "wall": first_materialized(registry, ("SM_WoodenFence_2m_01", "SM_WoodenPole_01")),
        "chair": first_materialized(registry, ("SM_FlowerPot", "SM_WoodenPole_03", "SM_WoodenDisc_01")),
        "table": first_materialized(registry, ("SM_Table_01", "SM_WoodenDisc_01", "table")),
        "rock": first_materialized(registry, ("SM_Stone_01", "SM_BigStone_01", "stone")),
        "bush": first_materialized(registry, ("SM_Plant_Grass_01", "SM_CoconutTree_01", "plant")),
        "traffic_cone": first_materialized(registry, ("SM_Cone", "traffic cone")),
        "market_bottle": first_materialized(registry, ("SM_Bottle_01a", "bottle")),
        "market_box": first_materialized(registry, ("SM_Apple_Box", "wood crate", "box")),
    }
    assets = {key: manifest_entry(key, asset) for key, asset in selection.items() if asset}
    scene = first_materialized(registry, ("MarketEnvironment Day", "Day"), class_name="World")
    return {
        "resolver": "asset_database_materialized_only",
        "source": "agenticdataplatform_modelscope",
        "source_path": registry.get("source_path"),
        "repo_root": registry.get("repo_root"),
        "policy": "asset_database_only_no_engine_or_startercontent_fallback",
        "registry_asset_count": registry.get("asset_count"),
        "materialized_counts": registry.get("materialized_counts"),
        "assets": assets,
        "materials": {},
        "scene": manifest_entry("scene", scene) if scene else None,
        "missing_required_keys": sorted(key for key, asset in selection.items() if not asset),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="ADP repo root or AssetIndex/ASSETS_INDEX.json")
    parser.add_argument("--repo-root", default=None, help="Optional ADP repo root for materialized checks")
    parser.add_argument("--metadata-repo-root", default=None, help="Repo root path to write into generated metadata")
    parser.add_argument("--metadata-source-path", default=None, help="Asset index path to write into generated metadata")
    parser.add_argument("--output-dir", default="assets", help="Studio assets output directory")
    parser.add_argument("--top-k", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    registry = build_registry(args.source, args.repo_root, args.metadata_repo_root, args.metadata_source_path)
    manifest = build_default_manifest(registry)
    search_report = build_search_report(registry, DEFAULT_QUERIES, args.top_k)
    scenario_manifest = build_scenario_manifest(registry)
    write_json(output_dir / "full_asset_registry.json", registry)
    write_json(output_dir / "asset_database_manifest.json", manifest)
    write_json(output_dir / "gitlab_only_manifest.json", manifest)
    write_json(output_dir / "search_report.json", search_report)
    write_json(output_dir / "scenario_manifest.json", scenario_manifest)
    print(
        json.dumps(
            {
                "asset_count": registry["asset_count"],
                "class_counts": registry["class_counts"],
                "materialized_counts": registry["materialized_counts"],
                "map_count": scenario_manifest["map_count"],
                "missing_required_keys": manifest["missing_required_keys"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
