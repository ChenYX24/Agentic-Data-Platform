# Artifact Schema

Fallback backend 当前写出：

```text
case_spec.json
artifact_manifest.json
fallback_output/trajectory.json
fallback_output/summary.json
fallback_output/run_readiness.json
fallback_output/render_pass_manifest.json
harness_verifier.json
```

## Trajectory

每帧格式：

```json
{
  "frame": 0,
  "time_s": 0.0,
  "objects": {
    "object_id": {
      "position_m": [0, 0, 0],
      "velocity_m_s": [0, 0, 0],
      "rotation_deg": [0, 0, 0]
    }
  },
  "contacts": [
    {"objects": ["a", "b"], "frame": 1, "time_s": 0.1}
  ]
}
```

## Verifier Report

统一 schema：

```json
{
  "case_id": "...",
  "capability_id": "...",
  "status": "pass|fail|warning",
  "failure_type": "...",
  "first_failure": {
    "object_id": "...",
    "frame": 0,
    "time": 0.0,
    "metric": "...",
    "value": 0.0
  },
  "evidence": [],
  "repair_suggestions": [],
  "artifact_completeness": {}
}
```

## 坐标系

Harness fallback 使用 `z_up`。下落验证默认检查 `z` 是否下降。
