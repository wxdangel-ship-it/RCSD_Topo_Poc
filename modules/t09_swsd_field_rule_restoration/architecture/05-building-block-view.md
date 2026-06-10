# 05 Building Block View

## 1. 稳定阶段链

```text
load_t09_inputs
  -> build_t09_arm_universe
  -> restore_field_rules
  -> write_restoration_outputs
  -> run_t09_frcsd_restriction_modeling
```

## 2. 构件职责

| 构件 | 职责 |
|---|---|
| `io.py` | 读取 SWSD Node / Road、T01 Segment、restriction、arrow，并做 CRS 归一和输入审计。 |
| `arm_builder.py` | 构建 SWSD Arm，识别进入、退出、内部、特殊 carrier road。 |
| `movement_builder.py` | 基于 Arm 构建 Arm-to-Arm Movement 和 carrier universe。 |
| `restriction_evidence.py` | 匹配 restriction road-pair，生成显式禁止证据。 |
| `arrow_codes.py` | 解析 SW arrow code，区分原始 code 与规范 token。 |
| `arrow_evidence.py` | 生成 arrow 支持、排除、冲突、不可用等证据。 |
| `special_carrier.py` | 识别提前左转、提前右转、辅路提右等现场 carrier 证据。 |
| `restoration.py` | 汇总证据并生成 Movement 状态和 restored field rules。 |
| `outputs.py` | 写出 Step1/2 GPKG / CSV / JSON / summary。 |
| `frcsd_restriction.py` | 执行 Step3 F-RCSD restriction 投影。 |
| `text_bundle.py` | 导出 / 解包 Step3 输入证据包。 |
| `runner.py` | 组织 Step1/2 callable 主流程。 |

## 3. 入口构件

- `run_t09_swsd_field_rule_restoration`
- `run_t09_frcsd_restriction_modeling`
- `run_t09_export_step3_input_text_bundle`
- `run_t09_decode_text_bundle`

当前无 repo CLI 主 runner。
