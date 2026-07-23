from __future__ import annotations

import json
import os
from pathlib import Path

import unreal


source_mesh = os.environ.get("SIM_STUDIO_GLASS_SOURCE_MESH", "/Engine/BasicShapes/Cube.Cube")
material = os.environ.get(
    "SIM_STUDIO_GLASS_MATERIAL",
    "/Game/DD_Vehicles_Advanced/Materials/Material_Instances/Glass/MI_DestructibleGlass.MI_DestructibleGlass",
)
output_package = os.environ.get(
    "SIM_STUDIO_GLASS_OUTPUT_PACKAGE",
    "/Game/HarnessGenerated/Glass/GC_GlassPanelRadial",
)
panel_size_cm = [
    float(value)
    for value in os.environ.get("SIM_STUDIO_GLASS_PANEL_SIZE_CM", "160,2,100").split(",")
]
if len(panel_size_cm) != 3:
    raise RuntimeError("SIM_STUDIO_GLASS_PANEL_SIZE_CM must contain x,y,z")
fracture_center_local_cm = [
    float(value)
    for value in os.environ.get("SIM_STUDIO_GLASS_FRACTURE_CENTER_LOCAL_CM", "0,0,15").split(",")
]
if len(fracture_center_local_cm) != 3:
    raise RuntimeError("SIM_STUDIO_GLASS_FRACTURE_CENTER_LOCAL_CM must contain x,y,z")

created = unreal.ADPPhysicsRuntimeLibrary.create_fractured_glass_panel_asset(
    source_mesh,
    material,
    output_package,
    unreal.Vector(*panel_size_cm),
    unreal.Vector(*fracture_center_local_cm),
    int(os.environ.get("SIM_STUDIO_GLASS_VORONOI_SITES", "48")),
    int(os.environ.get("SIM_STUDIO_GLASS_RANDOM_SEED", "1701")),
)
if not created:
    raise RuntimeError(f"failed to create {output_package}")

object_path = f"{output_package}.{output_package.rsplit('/', 1)[-1]}"
asset = unreal.load_asset(object_path)
if not asset or "GeometryCollection" not in asset.get_class().get_name():
    raise RuntimeError(f"generated asset is not a GeometryCollection: {object_path}")

report = {
    "schema_version": "harness_generated_ue_asset_v1",
    "asset_kind": "geometry_collection",
    "object_path": object_path,
    "source_mesh": source_mesh,
    "material": material,
    "panel_size_cm": panel_size_cm,
    "fracture_pattern": "radial_voronoi",
    "fracture_center_local_cm": fracture_center_local_cm,
    "voronoi_sites": int(os.environ.get("SIM_STUDIO_GLASS_VORONOI_SITES", "48")),
    "random_seed": int(os.environ.get("SIM_STUDIO_GLASS_RANDOM_SEED", "1701")),
    "watertight_source_required": True,
}
report_path = os.environ.get("SIM_STUDIO_UE_ASSET_GENERATION_REPORT")
if report_path:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

print(json.dumps(report))
