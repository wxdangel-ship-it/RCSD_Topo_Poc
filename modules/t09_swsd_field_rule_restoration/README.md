# T09 SWSD Field Rule Restoration

本文件是 T09 的凝练版需求说明，面向人快速理解模块业务目标、输入输出、关键步骤和对错边界。详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 模块定位

T09 基于 SWSD Laneinfo、restriction、SWSD Road / Node、T01 Segment 与 T06 F-RCSD 承载关系，还原现场路口级通行规则，并把显式禁止通行证据投影到融合后的 F-RCSD `LinkID -> outLinkID` restriction。

T09 当前覆盖 Step1 / Step2 / Step3：

1. Step1：构建 SWSD 语义路口 Arm 与 Arm-to-Arm Movement。
2. Step2：用 restriction、arrow 和特殊 carrier 证据还原 SWSD Movement 级现场规则。
3. Step3：基于 T06 Segment relation 将 `fully_prohibited + explicit_restriction` 投影为 F-RCSD road-to-road restriction。

## 2. 业务目标

- 让现场 SWSD 路口通行规则从原始 restriction / Laneinfo 证据中变成可审计的 Arm、Movement、Evidence、RestoredRule。
- 明确区分“显式禁止通行”“没有禁止证据”“拓扑不可达”“方向不适用”和“需要人工复核”。
- 使用 T06 输出的 SWSD-FRCSD Segment 承载关系，把已确认的 SWSD 禁止通行规则恢复到 F-RCSD。
- 为后续 T10 Case 证据包、人工分析和真实数据复核提供稳定文件证据。

## 3. 输入

### Step1 / Step2 输入

| 输入 | 用途 |
|---|---|
| SWSD Node | 按 `id / mainnodeid / kind_2 / geometry` 组织语义路口与 member nodes。 |
| SWSD Road | 按 `id / snodeid / enodeid / direction / geometry` 构建 Arm 的进入、退出和内部道路。 |
| T01 Segment | 辅助 Arm 主方向、连续性、远端终止和 Step3 承载映射。 |
| T08 Tool7 restriction | 最高优先级的显式禁止通行证据。 |
| T08 Tool8 arrow | 车道箭头现场证据，用于支持、排除、冲突和人工复核审计。 |

### Step3 输入

| 输入 | 用途 |
|---|---|
| T09 Step1/2 输出 | 提供 `arms / movements / restored_rules`。 |
| T06 `t06_frcsd_road` | F-RCSD Road 承载。 |
| T06 `t06_frcsd_node` | F-RCSD Node 与语义组。 |
| T06 `t06_step3_swsd_frcsd_segment_relation` | SWSD Segment 到 F-RCSD Road / Node 的稳定映射。 |

## 4. 输出

### Step1 / Step2 输出

- `t09_swsd_arms.gpkg/csv/json`
- `t09_arm_movements.gpkg/csv/json`
- `t09_evidence_items.gpkg/csv/json`
- `t09_restored_field_rules.gpkg/csv/json`
- `t09_swsd_field_rule_restoration_summary.json`

### Step3 输出

- `frcsd_restriction.gpkg`
- `frcsd_restriction.csv`
- `frcsd_restriction.json`
- `t09_step3_frcsd_restriction_summary.json`

## 5. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| 输入归一 | 将 SWSD / T01 / T08 / T06 输入读取到统一 CRS，并保留输入路径、字段和计数审计。 |
| Arm 构建 | 按 SWSD 语义路口聚合 member nodes，识别 internal、approach、exit、seed、special carrier road。 |
| Movement 构建 | 对同一路口内 Arm 两两建立 Movement，并记录候选 road-pair carrier universe。 |
| 证据匹配 | restriction 直接生成显式禁止证据；arrow、提前左转、提前右转等生成现场解释或冲突证据。 |
| 规则还原 | 只有 restriction 明确覆盖的 Movement 才进入禁止规则；没有证据不反推 allowed 或 prohibited。 |
| F-RCSD 投影 | 用 T06 relation 将 SWSD Arm 承载到 F-RCSD Road，生成 `LinkID -> outLinkID` 禁止通行关系。 |

## 6. 什么是对

- `fully_prohibited` 必须来自显式 restriction，且能追溯到 `T09EvidenceItem`。
- 单条 road-pair restriction 不能被放大为整个 Arm-Movement 禁止。
- 完整 arrow 排除只能作为现场证据；没有 restriction 时不能单独生成禁止规则。
- `topology_impossible / direction_incompatible / not_applicable` 只能表达不适用，不是交通规则禁止。
- F-RCSD restriction 必须通过 T06 relation 映射，不能假设 SWSD Road ID 与 F-RCSD Road ID 天然相等。
- 所有输出必须可追溯输入、参数、证据、匹配方式和跳过原因。

## 7. 什么是错

- 因为没有 allowed evidence 就输出 prohibited。
- 将 `9 / uninvestigated` 或 `o / empty` 箭头当成强禁止证据。
- 把提前左转、提前右转、辅路提右直接等价为整个 Movement 禁止。
- 修改 T06 / T08 / SWSD / F-RCSD 输入文件。
- 缺失 Segment relation、F-RCSD Road 或端点 Node 时 silent fix。
- 用 F-RCSD `source` 字段反推交通限制语义。

## 8. 当前入口

T09 当前以模块内 callable 为主，不提供 repo 官方 CLI 主 runner。

```python
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    run_t09_frcsd_restriction_modeling,
    run_t09_swsd_field_rule_restoration,
)
```

Step3 输入证据包存在已登记内网辅助脚本：

```bash
.venv/bin/python scripts/t09_export_step3_input_text_bundle_innernet.sh --help
```

该脚本用于提炼 Step3 输入证据，不替代 T09 主业务 callable。

## 9. 文档阅读顺序

1. `README.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/05-building-block-view.md`
5. `architecture/10-quality-requirements.md`
6. `architecture/11-risks-and-technical-debt.md`
