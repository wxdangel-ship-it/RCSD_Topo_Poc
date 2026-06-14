# T09 模块规格：SWSD 现场通行规则恢复

## 1. 模块定位

T09 基于 SWSD Laneinfo、restriction、SWSD Road / Node、T01 Segment 与 T06 F-RCSD 承载关系，还原现场路口级通行规则，并把显式禁止通行证据投影到融合后的 F-RCSD `LinkID -> outLinkID` restriction。T09 是当前主链中从融合拓扑走向通行能力恢复的正式模块。

## 2. 业务目标

- 将 SWSD restriction / Laneinfo 证据还原为可审计的 Arm、Movement、Evidence 和 RestoredRule。
- 明确区分显式禁止通行、无禁止证据、拓扑不可达、方向不适用和人工复核。
- 使用 T06 SWSD-FRCSD Segment relation，把确认的 SWSD 禁止通行规则恢复到 F-RCSD；对未进入 Segment relation 但仍在 T06 F-RCSD 输出中以 `source=2` 保留的 SWSD Arm seed road，可作为保留 SWSD carrier fallback。
- 为 T10 Case 证据包、人工分析和真实数据复核提供稳定文件证据。

## 3. 当前范围

### 3.1 正式支持

- Step1：基于 SWSD Node / Road 与 T01 Segment 构建 SWSD Arm。
- Step2：基于 restriction、arrow 与特殊 carrier 证据还原 SWSD Movement 级现场规则。
- Step3：基于 T06 SWSD-FRCSD Segment relation，将显式禁止通行 Movement 投影为 F-RCSD restriction。
- 输出 GPKG / CSV / JSON 与 summary。

### 3.2 当前非目标

- 不生成 F-RCSD `RoadNextRoad`。
- 不把 F-RCSD 独立 Arm 构建作为主策略。
- 不消费 F-RCSD Laneinfo 或轨迹通行证据。
- 不修改 T06、T08、SWSD 或 F-RCSD 输入。
- 不新增 repo CLI、root scripts、Makefile 目标或模块主入口。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T08 Tool7 | 提供显性 SWSD restriction。 |
| 上游 | T08 Tool8 | 提供显性 Laneinfo arrow。 |
| 上游 | T01 | 提供 SWSD Segment 与 Arm 连续性辅助。 |
| 上游 | T06 | 提供 F-RCSD Road/Node 与 SWSD-FRCSD Segment relation。 |
| 下游 | T10 / 人工审计 | 消费 T09 输出组织 Case 证据和分析通行能力。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| SWSD Node | 按 `id / mainnodeid / kind_2 / geometry` 组织语义路口和 member nodes。 |
| SWSD Road | 按 `id / snodeid / enodeid / direction / geometry` 构建 Arm 进入、退出和内部道路。 |
| T01 Segment | 辅助 Arm 主方向、连续性和 Step3 承载映射。 |
| T08 restriction | 最高优先级的显式禁止通行证据。 |
| T08 arrow | 车道箭头现场证据，用于支持、排除、冲突和复核审计。 |
| T06 F-RCSD Road/Node/relation | Step3 将 SWSD 禁止规则投影到 F-RCSD 的承载关系；`source=2` 且仍在 F-RCSD 输出中的 SWSD seed road 可用于保留 carrier fallback。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `t09_swsd_arms.*` | SWSD Arm 结构和风险标记。 |
| `t09_arm_movements.*` | Arm-to-Arm Movement 候选和状态。 |
| `t09_evidence_items.*` | restriction / arrow / special carrier 证据项。 |
| `t09_restored_field_rules.*` | SWSD Movement 级规则还原结果。 |
| `t09_swsd_field_rule_restoration_summary.json` | Step1/2 summary、输入输出和 QA 信息。 |
| `frcsd_restriction.*` | F-RCSD `LinkID -> outLinkID` 禁止通行关系。 |
| `t09_step3_frcsd_restriction_summary.json` | Step3 投影 summary 和跳过原因。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| 输入归一 | 统一 CRS，保留输入路径、字段、计数和异常审计。 |
| Arm 构建 | 按语义路口聚合 member nodes，识别 internal、approach、exit、seed 和 special carrier road。 |
| Movement 构建 | 对 Arm 两两建立候选通行方向，形成 road-pair carrier universe。 |
| restriction 匹配 | road-pair restriction 是唯一能改变禁行结论的显式禁止证据。 |
| arrow / carrier 解释 | arrow 和特殊 carrier 只作为现场证据、解释证据、冲突证据或风险。 |
| 规则还原 | 只有 explicit restriction 支撑的 `fully_prohibited` 才输出稳定禁止规则。 |
| F-RCSD 投影 | 通过 T06 relation 映射 Arm 承载；`retained_swsd` 与 `replaced+retained_swsd` 的 `source=2` relation road 必须仍属于当前 Arm 的 approach / exit seed；未进入 relation 但仍由 T06 以 `source=2` 保留的 SWSD seed road 可补充保留 carrier，生成 F-RCSD restriction。 |

## 8. 什么是对

- `fully_prohibited` 必须来自显式 restriction，且能追溯到 evidence。
- 单条 road-pair restriction 不能放大为整个 Arm-Movement 禁止。
- arrow 排除没有 restriction 时不能单独生成禁止规则。
- F-RCSD restriction 必须通过 T06 relation 映射，或通过 T06 F-RCSD 输出中仍保留的 `source=2` SWSD seed road fallback 映射。
- 所有输出必须记录输入、参数、证据、匹配方式和跳过原因。

## 9. 什么是错

- 因为没有 allowed evidence 就输出 prohibited。
- 将 `9 / uninvestigated` 或 `o / empty` arrow 当成强禁止证据。
- 把提前左转、提前右转、辅路提右直接等价为整个 Movement 禁止。
- 修改 T06 / T08 / SWSD / F-RCSD 输入文件。
- 缺失 Segment relation、F-RCSD Road 或端点 Node 时 silent fix。
- 用 F-RCSD `source` 字段反推交通限制语义。

## 10. 当前治理缺口

- 当前缺少 RCSD Laneinfo 与轨迹通行证据，F-RCSD 通行能力恢复仍需迭代。
- Step3 输入证据包脚本只用于证据提炼，不替代 T09 主业务 callable。
