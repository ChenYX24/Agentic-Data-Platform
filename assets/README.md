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

Every selected asset must record `source_kind`, `source_uri`, `license`,
`quality_status`, and `ue_path`. Materialized local, Fab, open-source, and
generated files must also record their SHA-256 as `sha256`. Engine built-ins and
analytic proxies use their UE URI as content identity and do not require a file
hash.

Physics-critical assets must additionally include `collider`, `mass_kg`,
`material`, and `collision_profile`. The resolver skips candidates that fail
this gate and falls back to an analytic proxy. Recommended acquisition order:

1. approved local/Fab asset;
2. approved open-source asset;
3. generated asset with recorded generator inputs;
4. approved analytic proxy.
