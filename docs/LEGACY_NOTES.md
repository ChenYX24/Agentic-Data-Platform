# Legacy Notes

本仓库当前主路径是 physics-aware harness：

```text
capabilities/ -> cases/ -> harness/ -> scripts/harness_*.py -> verifier/artifacts
```

以下路径是旧 Studio / prompt-to-video / viewer / benchmark 工作流，保留用于迁移和调试，但不作为默认入口：

| 路径 | 状态 | 说明 |
|---|---|---|
| `run_demo.py` | legacy | 旧 prompt-to-video demo pipeline。后续应由 harness case runner + UE backend 替代。 |
| `server.py` / `api/` | optional legacy API | 旧 API 服务 run 和前端 viewer。后续如果保留，应返回 harness artifact summary。 |
| `apps/demo_frontend/` | optional viewer | 前端不是核心 harness。恢复前端时应展示 capability verifier、diagnosis、artifact manifest，而不是只展示视频。 |
| `tools/draft_builder.py` | legacy planner bridge | 旧 prompt rewrite / object graph compiler。能力可迁移到 `harness/planning/`。 |
| `tools/ue_render_runner.py` | legacy UE runner | 当前真实 UE runner 的主要入口。新主路径应通过 `harness/runtime/ue_backend.py` 调用它。 |
| `benchmark_suite/` | research benchmark | M1 canonical benchmark。不是 harness quickstart。 |
| `scripts/package_dataset.py` | legacy dataset packager | 旧 dataset packaging；新主路径优先使用 `scripts/harness_package_dataset.py`。 |

不要把 `runs/`、`outputs/`、`artifacts/`、`agent-docs/`、`_local_inputs/`、`.env` 或 API token 提交到公开仓库。
