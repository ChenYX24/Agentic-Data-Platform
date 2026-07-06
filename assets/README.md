# Assets Directory

This repository does not commit large UE assets or private dataset dumps.

Use this directory for small, public-safe metadata only:

- `asset_registry.example.json`: minimal schema example.
- `asset_registry.local.json`: local asset index, ignored by git.
- `physics_materials.local.json`: local material/collider metadata, ignored by git.

Recommended local layout:

```text
assets/
  asset_registry.local.json
  physics_materials.local.json
  ue_imports/
    meshes/
    materials/
    textures/
```

Set the harness path explicitly:

```bash
export SIM_STUDIO_ASSET_REGISTRY="$PWD/assets/asset_registry.local.json"
```

Physics-critical assets should include collider, mass, material, and collision
profile metadata. Visual-only assets can be omitted or downgraded to analytic
proxy assets.
