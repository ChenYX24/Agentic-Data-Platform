# Capability Authoring

新增能力时，先写 capability JSON，再写最小正负 case，再写 verifier 或 adapter。

## 文件

```text
capabilities/<capability_id>.json
cases/<family>/<case>.json
harness/verification/<family>_verifier.py
tests/test_<family>_verifier.py
```

## 必填内容

Capability 必须包含：

- physical assumptions
- required signals
- required assets
- verifier rules
- failure taxonomy
- repair suggestions
- smoke cases
- regression cases

## 原则

- 不要把 capability 写成某个 prompt 模板。
- 要写清楚物理因果规则。
- negative case 必须能稳定 fail。
- fallback backend 可以先用 deterministic toy trajectory，但必须显式标记 source。

## 验证

```bash
python3 -m json.tool capabilities/<capability_id>.json >/dev/null
python3.13 scripts/harness_smoke.py --backend fallback
python3.13 -m unittest discover -s tests -p 'test*.py'
```
