# Optional Viewer

`apps/demo_frontend/` 是 optional viewer，不是核心 harness。

## 当前定位

前端可用于：

- 浏览 run artifact。
- 查看视频或 preview。
- 展示 asset selection。
- 展示 render pass / signal 状态。

但 harness 的核心验收不依赖前端。核心路径是：

```text
CLI/API -> artifact schema -> verifier report -> diagnosis -> tests
```

## 为什么降级

- Code agent 更需要稳定 JSON/CLI/API。
- 前端容易让项目被误解为 prompt-to-video demo。
- 物理 correctness 必须由 verifier gate 决定，不由 UI 或视频观感决定。

## 后续前端如果恢复主力展示，应优先展示

- capability id
- verifier status
- failure type
- first failing object/frame
- trajectory/contact evidence
- repair suggestions
- artifact manifest

不要只展示视频。
