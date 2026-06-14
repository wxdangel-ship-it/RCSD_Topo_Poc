# T09 - INTERFACE_CONTRACT

## 定位

本文件是 `t09_swsd_field_rule_restoration` 的稳定接口契约。
凝练业务说明见 `SPEC.md`。
详细业务落地见 `architecture/04-solution-strategy.md`。
阅读入口见 `README.md`。

## 1. 目标与范围

### 1.1 当前正式支持

- Step1：基于 SWSD Node / Road 与 T01 Segment 构建 SWSD Arm。
- Step2：基于 restriction、arrow 与特殊 carrier 证据还原 SWSD Movement 级现场规则。
- Step3：基于 T06 SWSD-FRCSD Segment relation，将显式禁止通行 Movement 投影为 F-RCSD `LinkID -> outLinkID` restriction。
- Step3：若 T09 Arm 的 seed road 未进入 T06 Segment relation，但该 SWSD Road 仍以 `source=2` 出现在 T06 Step3 F-RCSD Road 输出中，可按原 SWSD junction alias 与 road direction 作为保留 SWSD carrier fallback，并在 risk flags 中标记。
- 输出结构化 GPKG / CSV / JSON 与 summary，支持人工复核和 T10 Case 证据组织。

### 1.2 当前非目标

- 不生成 F-RCSD `RoadNextRoad`。
- 不执行 F-RCSD 独立 Arm 构建作为主策略。
- 不消费 F-RCSD Laneinfo 或轨迹通行证据。
- 不修改 T06、T08、SWSD 或 F-RCSD 输入。
- 不新增 repo CLI、root scripts、Makefile 目标或模块主入口。

## 2. Inputs

### 2.1 Step1 / Step2 callable 输入

`run_t09_swsd_field_rule_restoration` 接受：

| 参数 | 必选 | 语义 |
|---|---|---|
| `swnode_gpkg` | 是 | SWSD Node 输入，至少包含 `id / mainnodeid / kind_2 / geometry`。 |
| `swroad_gpkg` | 是 | SWSD Road 输入，至少包含 `id / snodeid / enodeid / direction / geometry`。 |
| `segment_gpkg` | 否 | T01 Segment 输入，用于 Arm 与 Segment 关系。 |
| `restriction_gpkg` | 否 | T08 Tool7 显性 restriction 或等价 restriction LineString。 |
| `arrow_gpkg` | 否 | T08 Tool8 显性 arrow 或等价 Laneinfo arrow LineString。 |
| `output_dir` | 是 | 输出根目录。 |
| `run_id` | 否 | 输出批次 ID；缺省自动生成。 |
| `target_epsg` | 否 | 统一处理 CRS，默认 `3857`。 |

所有输入只读。缺关键字段、缺 CRS 或几何无法解释时，不得 silent fix。

### 2.2 Step3 callable 输入

`run_t09_frcsd_restriction_modeling` 接受：

| 参数 | 必选 | 语义 |
|---|---|---|
| `arms_path` | 是 | T09 Step1 输出的 `t09_swsd_arms.*`。 |
| `movements_path` | 是 | T09 Step1/2 输出的 `t09_arm_movements.*`。 |
| `restored_rules_path` | 是 | T09 Step2 输出的 `t09_restored_field_rules.*`。 |
| `frcsd_road_path` | 是 | T06 Step3 输出的 `t06_frcsd_road.*`。 |
| `frcsd_node_path` | 是 | T06 Step3 输出的 `t06_frcsd_node.*`。 |
| `segment_relation_path` | 是 | T06 Step3 输出的 `t06_step3_swsd_frcsd_segment_relation.*`。 |
| `output_dir` | 是 | 输出根目录。 |
| `run_id` | 否 | 输出批次 ID；缺省自动生成。 |
| `target_epsg` | 否 | 统一处理 CRS，默认 `3857`。 |

Step3 支持 GPKG / CSV / JSON 中的结构化输入，但 F-RCSD Road 输入必须有几何。

## 3. Outputs

### 3.1 Step1 / Step2 输出

输出目录：

```text
<output_dir>/<run_id>/
```

文件：

- `t09_swsd_arms.gpkg/csv/json`
- `t09_arm_movements.gpkg/csv/json`
- `t09_evidence_items.gpkg/csv/json`
- `t09_restored_field_rules.gpkg/csv/json`
- `t09_swsd_field_rule_restoration_summary.json`

### 3.2 Step3 输出

输出目录：

```text
<output_dir>/<run_id>/
```

文件：

- `frcsd_restriction.gpkg`
- `frcsd_restriction.csv`
- `frcsd_restriction.json`
- `t09_step3_frcsd_restriction_summary.json`

`frcsd_restriction` 至少包含：

- `restriction_id`
- `CondType`
- `LinkID`
- `inLinkID`
- `outLinkID`
- `junction_id`
- `frcsd_junction_id`
- `from_arm_id`
- `to_arm_id`
- `movement_id`
- `movement_type`
- `restriction_source`
- `source_rule_status`
- `confidence`
- `supporting_evidence_ids`
- `from_road_source`
- `to_road_source`
- `arm_relation_status`
- `risk_flags`

## 4. Business Rules

- restriction 是唯一能改变 Movement 禁行结果的显式禁止证据。
- arrow、完整 arrow 排除、提前左转、提前右转和特殊 carrier 只作为现场证据、解释证据或冲突证据。
- `fully_prohibited` 必须能追溯到 `explicit_restriction`。
- `partially_prohibited` 不自动放大为 F-RCSD 全 Arm 禁行。
- `no_prohibition_evidence / unknown / not_a_traffic_rule` 不生成 F-RCSD restriction。
- `relation_status=retained_swsd` 或 `relation_status=replaced+retained_swsd` 的 `source=2` relation road 只能在其 road id 属于当前 T09 Arm 的 `approach_road_ids` / `exit_road_ids` 时进入该 Arm 的 F-RCSD approach / exit carrier；不得仅因同属一个 T06 Segment relation 且端点命中 junction alias，就把其他 Arm 的 SWSD Road 混入当前 Movement。
- 未进入 Segment relation 的 Arm seed road 只有在同 ID road 以 `source=2` 仍存在于 T06 F-RCSD Road 输出、且端点方向能在 SWSD junction alias 上解释为 approach / exit 时，才可作为 `retained_swsd_seed_fallback` carrier；该路径必须输出 `retained_swsd_seed_carrier_fallback` 风险标记。
- Step3 去重键为 `LinkID + outLinkID + junction_id + movement_type`。

## 5. EntryPoints

### 5.1 模块 callable

```python
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    run_t09_swsd_field_rule_restoration,
    run_t09_frcsd_restriction_modeling,
)
```

### 5.2 已登记辅助脚本

```bash
.venv/bin/python scripts/t09_export_step3_input_text_bundle_innernet.sh --help
```

该脚本只用于 Step3 输入证据包导出，不是 T09 主 runner。

## 6. Params

- 路径参数必须显式传入，不硬编码内网路径。
- `target_epsg` 默认 `3857`，summary 必须记录 CRS 归一口径。
- layer 参数只用于读取多图层文件，不改变业务语义。
- `run_id` 只影响输出目录命名，不影响判定结果。

## 7. Acceptance

1. Step1 / Step2 输出 arms、movements、evidence、restored rules 和 summary。
2. Step3 只对 `fully_prohibited + explicit_restriction` 生成 F-RCSD restriction。
3. 每条 restored rule 和 F-RCSD restriction 都能回溯证据、Movement 和 T06 relation；若使用 retained SWSD seed fallback，必须能回溯到 T09 Arm seed road 与 T06 F-RCSD `source=2` road。
4. 没有 restriction 的 arrow 排除、特殊 carrier、拓扑不可达不生成禁止规则。
5. summary 记录输入计数、输出计数、跳过原因、CRS、审计与性能信息。
