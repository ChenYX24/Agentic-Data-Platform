# UE Setup

This harness uses Unreal Engine as the production renderer and signal source.
Fallback is for verifier/debug development only.

## Required UE Version

The local runner has been exercised with UE 5.7 on macOS:

```text
/Users/Shared/Epic Games/UE_5.7/Engine/Binaries/Mac/UnrealEditor-Cmd
```

Other UE 5.x versions may work, but the Python API and screenshot/MRQ behavior
must be revalidated.

## Repository UE Template

The repository includes:

```text
ue_template/
  SimulatorStudioTemplate.uproject
  Plugins/ADPPhysicsRuntime/
```

The plugin provides the runtime physics capture bridge used by the harness.
When opening the template project for the first time, let UE rebuild the plugin
if prompted.

## Environment Variables

Set these before running `--backend ue`:

```bash
export SIM_STUDIO_UE_PROJECT="$PWD/ue_template/SimulatorStudioTemplate.uproject"
export SIM_STUDIO_UE_EXECUTABLE="/Users/Shared/Epic Games/UE_5.7/Engine/Binaries/Mac/UnrealEditor-Cmd"
export SIM_STUDIO_UE_MAP="/Game/Maps/MarketEnvironment/Maps/Day.Day"
export SIM_STUDIO_UE_ACTOR_CLASS="/Script/Engine.StaticMeshActor"
export SIM_STUDIO_ASSET_REGISTRY="$PWD/assets/asset_registry.example.json"
export SIM_STUDIO_UE_CONTACT_EXPORT=1
export SIM_STUDIO_UE_RUNNER_CMD="python3.13 scripts/harness_local_ue_runner.py"
```

Optional render controls:

```bash
export SIM_STUDIO_UE_RENDER_MODE=both        # rgb | data | both
export SIM_STUDIO_UE_RGB_CAPTURE_BACKEND=scene_capture
export SIM_STUDIO_UE_WIDTH=1280
export SIM_STUDIO_UE_HEIGHT=720
export SIM_STUDIO_UE_FPS=60
export SIM_STUDIO_UE_RENDER_QUALITY=high
```

## Asset Registry

Do not commit large assets to this repository. Put local metadata in:

```text
assets/asset_registry.local.json
assets/physics_materials.local.json
assets/ue_imports/
```

Then point the harness at it:

```bash
export SIM_STUDIO_ASSET_REGISTRY="$PWD/assets/asset_registry.local.json"
```

Physics-critical assets should provide:

- `ue_path`
- collider type
- mass
- material friction/restitution
- collision profile
- whether analytic proxy is allowed

Visual-only assets can be omitted from the physics graph.

## Run One UE Case

```bash
python3.13 scripts/harness_run_case.py \
  cases/billiards/six_ball_triangle_low_speed.json \
  --backend ue \
  --mode both \
  --views front_static,side_static,top_down,tracking_subject,event_closeup \
  --render-passes rgb,depth,segmentation \
  --output-root runs/ue_cases
```

## Output Contract

The UE backend must produce:

```text
case_spec.json
scene_spec.json
camera_plan.json
trajectory.json
contact_events.json
camera_trajectory.json
render_manifest.json
render_pass_manifest.json
render_sync_report.json
verifier_report.json
run_readiness.json
views/<camera_id>/rgb.mp4
views/<camera_id>/depth.exr
views/<camera_id>/segmentation.png
views/<camera_id>/meta.json
```

Missing depth, segmentation, views, or sync should be a hard failure.

## Highres Viewport Blocker

`highres_viewport` relies on editor viewport screenshot frames. In offscreen or
headless UE runs it can fail by producing no `frame_*.png` files. This is not a
case/verifier failure.

Recommended fix:

1. Keep SceneCapture as the synchronized data path.
2. Add Movie Render Queue / Level Sequence as the high-quality RGB path.
3. Share `camera_trajectory.json` and physics trace between RGB and data passes.
4. Mark viewport screenshot capture as debug-only.

## Current Physics Caveat

SceneCapture RGB/depth/segmentation sync is working. Some rigid-body gravity
cases still require deeper UE runtime stepping work so the physical trajectory
passes verifier, not just render sync.
