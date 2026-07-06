# Case Spec Schema

当前 schema version：

```text
harness_case_spec_v1
```

必填字段：

| 字段 | 含义 |
|---|---|
| `case_id` | 稳定 case id |
| `capability_id` | 绑定的 capability |
| `prompt` | 自然语言意图 |
| `expected_physics` | 物理预期、坐标系、碰撞图等 |
| `objects` | 对象列表，必须有稳定 id/role |
| `active_objects` | 可主动受力/初速度对象 |
| `passive_objects` | 必须由物理事件触发的对象 |
| `required_assets` | 资产需求 |
| `required_signals` | 运行必须产出的信号 |
| `verifier_expectation` | 预期 pass/fail 和 failure type |
| `should_pass` | smoke 中的期望 |
| `notes` | 人类说明 |

示例：

```bash
python3 -m json.tool cases/billiards/low_speed_single_contact.json >/dev/null
```

Case spec 是可执行 contract，不是 prompt 模板。
