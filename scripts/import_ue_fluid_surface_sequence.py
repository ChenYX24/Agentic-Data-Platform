from __future__ import annotations

import json
import os
from pathlib import Path

import unreal


manifest_path = Path(os.environ["SIM_STUDIO_FLUID_REPLAY_MANIFEST"]).expanduser().resolve()
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
asset_root = str((manifest.get("ue") or {}).get("asset_root") or "").rstrip("/")
if not asset_root.startswith("/Game/"):
    raise RuntimeError(f"invalid UE asset root: {asset_root}")

tasks = []
for frame in manifest.get("frames") or []:
    source = (manifest_path.parent / str(frame["ue_obj"])).resolve()
    if not source.is_file():
        raise RuntimeError(f"surface frame missing: {source}")
    task = unreal.AssetImportTask()
    task.filename = str(source)
    task.destination_path = asset_root
    task.destination_name = Path(str(frame["ue_asset_path"])).name
    task.automated = True
    task.replace_existing = True
    task.replace_existing_settings = True
    task.save = True
    tasks.append(task)

unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
imported = []
loaded_assets = []
default_material = unreal.load_asset("/Engine/EngineMaterials/DefaultMaterial.DefaultMaterial")
if not default_material:
    raise RuntimeError("default material is unavailable for fluid surface material-slot initialization")
mesh_editor = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
if not mesh_editor:
    raise RuntimeError("StaticMeshEditorSubsystem is unavailable for fluid surface section mapping")
for frame, task in zip(manifest.get("frames") or [], tasks):
    expected = str(frame["ue_asset_path"])
    object_path = f"{expected}.{expected.rsplit('/', 1)[-1]}"
    asset = unreal.load_asset(object_path)
    if not asset or asset.get_class().get_name() != "StaticMesh":
        raise RuntimeError(f"fluid surface frame did not import as StaticMesh: {object_path}")
    static_materials = asset.get_editor_property("static_materials")
    if len(static_materials) == 0:
        asset.add_material(default_material)
        static_materials = asset.get_editor_property("static_materials")
    if len(static_materials) == 0:
        raise RuntimeError(f"fluid surface frame has no material slot after initialization: {object_path}")
    section_count = int(asset.get_num_sections(0))
    if section_count <= 0:
        raise RuntimeError(f"fluid surface frame has no render section: {object_path}")
    for section_index in range(section_count):
        mesh_editor.set_lod_material_slot(asset, 0, 0, section_index)
    section_slots = [int(mesh_editor.get_lod_material_slot(asset, 0, index)) for index in range(section_count)]
    if any(slot != 0 for slot in section_slots):
        raise RuntimeError(f"fluid surface render sections are not mapped to slot 0: {object_path}: {section_slots}")
    imported.append(
        {
            "object_path": object_path,
            "material_slot_count": len(static_materials),
            "section_count": section_count,
            "section_material_slots": section_slots,
        }
    )
    loaded_assets.append(asset)

save_many = getattr(unreal.EditorAssetLibrary, "save_loaded_assets", None)
if callable(save_many):
    save_many(loaded_assets, only_if_is_dirty=True)
else:
    for asset in loaded_assets:
        unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=True)

report = {
    "schema_version": "harness_ue_fluid_surface_import_v1",
    "status": "completed",
    "manifest": str(manifest_path),
    "asset_root": asset_root,
    "frame_count": len(imported),
    "assets": imported,
    "material_slot_gate": "every imported frame has at least one slot and every LOD0 section maps to slot 0",
    "replay_contract": "swap one StaticMesh per render frame; stable actor and instance id; reapply material slot 0",
}
report_path = Path(os.environ["SIM_STUDIO_FLUID_IMPORT_REPORT"]).expanduser().resolve()
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
try:
    unreal.EditorPythonScripting.set_keep_python_script_alive(False)
except Exception:
    pass
try:
    unreal.SystemLibrary.quit_editor()
except Exception:
    unreal.SystemLibrary.execute_console_command(None, "QUIT_EDITOR")
