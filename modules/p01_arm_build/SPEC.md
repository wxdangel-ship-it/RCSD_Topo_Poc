# P01 模块规格：Arm 构建与 F-RCSD RoadNextRoad POC

## 1. 模块定位

P01 是 Active POC / 成果模块，面向异构路口通行能力验证。它在 SWSD / RCSD / F-RCSD 三源道路和节点上构建 Arm、配准跨源 Arm，并生成面向 F-RCSD Road 的 RoadNextRoad 结果。P01 不替代 T09 的正式通行规则恢复契约；它用于沉淀更完整的路口通行能力建模经验和成果样例。

## 2. 业务目标

- 从 SWSD、RCSD、F-RCSD 的 Node / Road 中构建可审计的语义路口 Arm。
- 识别提前右转、提前左转等特殊转向结构，并保留结构证据。
- 基于同源 RoadNextRoad allowed evidence 构建 ArmMovement、ReceivingRoadRole 和 trunk 修正。
- 将三源 Arm 配准成 LogicalArmGroup，区分源缺失、部分覆盖、过拆、过合和冲突。
- 基于源侧通行规则和 F-RCSD 道路角色投影生成 F-RCSD RoadNextRoad。
- 输出 JSON、GeoJSON、GPKG、PNG、summary、review index、audit 和 issue report，支持机器审计和人工复核。

## 3. 当前范围

### 3.1 正式支持

- P01-A1：单源 Arm 构建、特殊转向识别、ArmMovement 和 trunk 修正。
- P01-A2：三源 Arm 配准和 LogicalArmGroup 构建。
- P01-Final：生成 `frcsd_road_next_road.geojson`。
- 内网单 Case 端到端执行脚本。
- 单路口文本证据包和开发复现 helper。

### 3.2 当前非目标

- 不替代 T09 正式通行规则恢复。
- 不实现 P01-A3 正式跨源 Movement 空间。
- 不实现 P01-B 禁行证据迁移和条件通行裁决。
- 不使用 `grade / grade_2` 作为 P01 主规则。
- 不用 RoadNextRoad `turnType / turntype` 判断 movement type。
- 不提供 repo 官方 CLI；稳定调用面是模块内 callable 和已登记内网脚本。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | SWSD / RCSD / F-RCSD Node/Road | 提供三源 Arm 构建基础。 |
| 上游 | 可选 RoadNextRoad | 提供同源 allowed movement evidence。 |
| 上游 | T06 F-RCSD | 提供融合后的承载道路和节点。 |
| 下游 | POC 成果 / 人工评审 | 消费 Arm、LogicalArmGroup、F-RCSD RoadNextRoad 和审计图层。 |
| 参考 | T09 | P01 可为后续通行能力建模提供经验，但不替代 T09 契约。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| SWSD / RCSD / F-RCSD Nodes | 语义路口 member nodes 和 mainnode 分组。 |
| SWSD / RCSD / F-RCSD Roads | Arm seed、internal road、trunk、特殊转向和角色投影。 |
| Junction group | 指定三源语义路口对应关系。 |
| SWSD / RCSD / F-RCSD RoadNextRoad | 同源 movement evidence 和最终生成参考。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| A1 Arm / trace / movement JSON | 单源结构、方向和通行证据审计。 |
| A1 review GPKG / PNG | 人工复核 Arm 和 movement。 |
| A2 LogicalArmGroup / feedback / issue | 三源配准结果和问题反馈。 |
| P01-Final `frcsd_road_next_road.geojson` | F-RCSD RoadNextRoad POC 成果。 |
| source profiles / final decisions / source maps | 解释规则来源、投影路径和风险。 |
| summary / review index / issue report | 批量筛查和质量排序。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| A1 语义路口上下文 | 按有效 `mainnodeid` 聚合节点，区分 member、internal road 和 seed road。 |
| A1 特殊转向 | 用 `formway` bit 识别提前右转 / 提前左转，并输出结构证据。 |
| A1 trace / Arm 聚合 | 沿道路拓扑追溯 seed 外侧，形成 InitialArm、FinalArm 和补充 corridor evidence。 |
| A1 Movement | 基于 RoadNextRoad allowed evidence 生成同源 ArmMovement 和 trunk 修正。 |
| A2 配准 | 以 F-RCSD Arm 为目标承载，结合结构、走廊、角色和几何辅助证据形成 LogicalArmGroup。 |
| Final 生成 | 将源侧通行规则投影到 F-RCSD 道路角色，生成去重后的 RoadNextRoad。 |

## 8. 什么是对

- 结构证据优先，几何只作为辅助解释。
- RoadNextRoad 缺失表示无 allowed evidence，不等于禁止。
- 特殊转向进入 Arm、Movement 和 issue 审计，而不是静默删除。
- A2 明确区分 source missing / partial 与 grouping error。
- P01-Final 输出能回溯到 source profile、generation decision 和 source map。

## 9. 什么是错

- 用 `grade / grade_2` 判定 P01 主规则。
- 用 `turnType / turntype` 直接判断 movement type。
- 把 P01-Final 结果当作 T09 正式契约。
- 用几何接近替代缺失的结构证据。
- 在多源配准冲突时自动拆分或合并而不输出 feedback。

## 10. 当前治理缺口

- P01 仍是 POC / 成果模块，后续若要进入正式通行规则链路，必须独立 SpecKit 任务明确与 T09 的边界。
- RoadNextRoad 编码仍有外部规范缺口，当前仓库内部编码不得被下游强解释为 RCSD 官方规范。
