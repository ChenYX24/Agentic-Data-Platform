# Agent Usage

Use this repository as a CLI/toolkit harness. The frontend is not the main
interface.

## Agent-Facing Tool Flow

1. Discover capabilities.
2. Select or generate case specs.
3. Resolve asset intent and registry paths.
4. Run fallback for schema/verifier debugging or UE for real artifacts.
5. Read verifier/report JSON.
6. Repair case/backend/capability based on diagnosis.
7. Package dataset-ready artifacts.

## Commands

List capabilities:

```bash
python3.13 scripts/harness_list_capabilities.py --json
```

Run smoke:

```bash
python3.13 scripts/harness_smoke.py --backend fallback
```

Run one case:

```bash
python3.13 scripts/harness_run_case.py \
  cases/billiards/low_speed_single_contact.json \
  --backend fallback \
  --output-root runs/harness_cases
```

Generate cases:

```bash
python3.13 scripts/harness_generate_cases.py \
  --suite billiards \
  --count 20 \
  --seed 42 \
  --out cases/generated/billiards_seed42
```

Run batch:

```bash
python3.13 scripts/harness_run_case_batch.py \
  cases/generated/billiards_seed42 \
  --backend fallback
```

Run UE:

```bash
python3.13 scripts/harness_run_case.py \
  cases/billiards/six_ball_triangle_low_speed.json \
  --backend ue \
  --mode both \
  --views front_static,side_static,top_down,tracking_subject,event_closeup \
  --render-passes rgb,depth,segmentation
```

## Paths Agents Must Fill

Required for UE:

| Variable | Meaning |
|---|---|
| `SIM_STUDIO_UE_PROJECT` | Absolute path to `.uproject`. |
| `SIM_STUDIO_UE_EXECUTABLE` | `UnrealEditor-Cmd` or `UnrealEditor`. |
| `SIM_STUDIO_UE_MAP` | UE map package path. |
| `SIM_STUDIO_UE_ACTOR_CLASS` | Actor class used by the runner, usually `/Script/Engine.StaticMeshActor`. |
| `SIM_STUDIO_ASSET_REGISTRY` | JSON asset registry with physics-critical metadata. |
| `SIM_STUDIO_UE_CONTACT_EXPORT` | Must be `1` for UE verification. |
| `SIM_STUDIO_UE_RUNNER_CMD` | Usually `python3.13 scripts/harness_local_ue_runner.py`. |

Optional:

| Variable | Meaning |
|---|---|
| `SIM_STUDIO_UE_WIDTH` / `SIM_STUDIO_UE_HEIGHT` | Render resolution. |
| `SIM_STUDIO_UE_FPS` | Frame rate and physics trace sampling target. |
| `SIM_STUDIO_UE_RENDER_MODE` | `rgb`, `data`, or `both`. |
| `SIM_STUDIO_UE_RGB_CAPTURE_BACKEND` | Use `scene_capture` for stable synchronized output. |

## What To Read After A Run

Primary files:

- `run_readiness.json`
- `verifier_report.json`
- `render_sync_report.json`
- `manifest.json`
- `trajectory.json`
- `contact_events.json`
- `views/<camera_id>/meta.json`

Decision rules:

- `render_sync_report.status=pass`: RGB/depth/segmentation alignment is valid.
- `verifier_report.status=pass`: physics causality invariant passed.
- `run_readiness.reference_ready=true`: both rendering and physics verifier gates passed.

## Billiards Capability Rule

The old billiards failure was caused by passive target balls receiving hidden
initial velocity. This harness forbids that:

- cue ball can have initial velocity;
- passive targets must start at zero velocity;
- target movement must be caused by contact events;
- expected collision graph edges must appear in `contact_events`.

Use `cases/billiards/negative_hidden_target_velocity.json` to test that the
verifier catches the forbidden shortcut.
