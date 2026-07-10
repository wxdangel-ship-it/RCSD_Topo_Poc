# T09 模块规格：SWSD 现场通行规则恢复

## 1. 模块定位

T09 基于 SWSD restriction、Laneinfo、Road / Node、T01 Segment 与 T06 F-RCSD 承载关系，先在 SWSD 层恢复可审计且作用域明确的通行规则，再把可证明的规则投影到 F-RCSD。T09 是主链中从融合拓扑走向通行能力恢复的正式模块，但不改写任何上游输入事实。

## 2. 业务目标

- 将 restriction、Laneinfo 和提前左转 / 提前右转证据统一组织为 Arm、Movement、Evidence 和 RestoredRule。
- 在 `multi_evidence_v2` 中固定执行 `Restriction > Laneinfo > 提前左转 / 提前右转`，保留每次冲突与覆盖链。
- 区分 Arm 级、Road-Pair 级、Road-to-Arm、Road 方向排除、special carrier 与核心路口位移，不把 Road 级事实放大为 Arm 级事实。
- 保留 restriction 的条件 / 时段 raw payload；语义不明确时标记 unknown，不扁平化为全时普通禁止。
- 使用 T06 Segment relation 恢复 F-RCSD carrier，并把稳定 restriction 与未验证 candidates 分层发布。
- 保持现有 Restriction-only 调用和基线兼容。

## 3. 策略与兼容性

T09 有两个显式策略：

| `strategy_version` | 业务口径 |
|---|---|
| `restriction_only_v1` | 默认。保持既有规则：只有 restriction 能改变最终禁行结论；Laneinfo / special carrier 只作解释、冲突和风险证据。 |
| `multi_evidence_v2` | 显式选择。允许完整有效 Laneinfo 形成 Road 级支持 / 排除，允许 special carrier 形成弱推导，并按统一优先级决策。 |

调用方不传 `strategy_version` 时必须得到 v1。不得通过环境变量、隐藏常量或运行数据静默切换；何时把 v2 设为默认策略必须另行需求确认。

## 4. 三类现实限制来源

### 4.1 Restriction

Restriction 是最高优先级显式证据。`(restriction_id, in_link_id, out_link_id)` 是基础 Road-Pair 匹配身份，同一 ID 下的多组 pair 不得折叠；`multi_evidence_v2` 的完整证据实例还必须包含 `condition_identity`，同一 Road-Pair 的不同条件不得互相覆盖或去重。

Restriction 默认只证明 `road_to_road`。只有同一条件身份内覆盖全部等价 carrier，且同一 from/to Arm、正式 T01 Segment 或显式 parallel-branch 能证明平行 / 切分承载等价、核心路径几何或精确 Link 身份以及未解释 carrier 均通过审计时，才能提升为 `arm_to_arm`。显式 parallel 证明只在 v2 生效，并把同角色、同 terminal、同方向 bundle 的全部 Road 作为一个等价组；不得按 Road ID 任意指定 core / branch。Road 自带 segmentid 与正式 T01 membership 冲突、同一 raw Restriction geometry 一对多匹配、部分覆盖、疑似 Arm 语义或证据冲突都必须保持 Road 级、partial 或人工复核，禁止“任一命中即全 Arm”。geometry fan-out 按同一次 restore run 内的 raw restriction identity 跨 Movement 汇总；精确 Link ID 证据保持权威，额外 geometry fallback 必须降为人工复核。

### 4.2 Laneinfo

Laneinfo 是 Road 级车道箭头证据。对每个进入 Road 聚合全部车道箭头，在 Road 与 Laneinfo 方向匹配、车道序列完整、所有 code 可解释且路口确实存在目标 Movement 时，才可对有效箭头方向取并集：

- 并集包含目标方向：该 Road 对该方向 `supported`。
- 并集不包含目标方向：生成 `road_direction_exclusion` 的 Road 级 `prohibited`。
- 任一必要条件不满足，或出现 `9`、`o`、未知码：结果为 `unknown`，不形成确定禁止。

数字 `0` 与字母 `o` 必须严格区分。缺左转箭头时左转受限，调头原则上联动受限；若有明确调头箭头，只解除调头联动，左转仍按箭头并集判断。Restriction 与 Laneinfo 冲突时 Restriction 优先。

### 4.3 提前左转 / 提前右转

特殊通道是最低优先级的弱推导，必须按 Arm 汇总后分析：

- `formway & 128 != 0` 标识提前右转候选。
- `formway & 256 != 0` 标识提前左转候选。
- `kind` 后缀只可保留为 raw audit，不得作为强识别规则。

特殊 Road 默认支持其专用方向；没有更高优先级证据时，其它方向可形成 `special_carrier` 弱限制候选。主路方向可能被特殊通道移出核心路口，形成 `core_junction_displacement`；若主路 Laneinfo 明确支持该方向，主路仍支持，Laneinfo 覆盖弱推导。辅路提右、绕开核心路口的提右和经过核心路口的路口前提右必须由 Arm 角色与拓扑证据区分；证据不足时输出 unknown / 人工复核，不猜测。每条 special 决策必须保留实际触发分类的 `source_carrier_road_ids`，不能把被评估的目标 Road 冒充证据来源。

## 5. 正式范围

### 5.1 支持

- Step1：构建 SWSD Arm、Movement 和 Road-Pair carrier universe。
- Step2：恢复 Restriction scope、Laneinfo Road 级规则、special carrier 弱规则与统一决策。
- Step3：基于 T06 relation 做 scope-aware F-RCSD 投影。
- 输出 GPKG / CSV / JSON、stable restriction、candidate 和 summary。

### 5.2 非目标

- 不生成 F-RCSD `RoadNextRoad`。
- 不以 F-RCSD 独立 Arm 构建作为主策略。
- 不消费或伪造当前不存在的 RCSD Laneinfo / 轨迹通行证据。
- 不修改 T06/T08/T10 实现、接口、正式入口和业务输入；本轮只按用户授权同步 T10 当前统计基线文档，不改写 T10 编排逻辑。
- 不根据 F-RCSD `source` 推断交通限制语义。
- 不新增 repo CLI、root script、Makefile 目标或模块主入口。

## 6. 上下游与输入

| 来源 | 用途与边界 |
|---|---|
| SWSD Node / Road | 构建语义路口、Arm、Road 方向与 special carrier 候选。 |
| T01 Segment | 提供 Arm 连续性与 T06 映射辅助，不替代 Road 证据。 |
| T08 Tool7 | 提供显性 restriction Road-Pair 和原始条件属性。 |
| T08 Tool8 | 提供 Laneinfo arrow、lane 顺序 / 数量和 raw properties。 |
| T06 | 提供 F-RCSD Road / Node、Segment relation 和 carrier source 审计。 |
| T10 / 人工审计 | 消费 T09 输出组织 Case 证据，不改写 T09 规则。 |

所有输入只读。字段缺失、CRS 缺失、方向或几何不可解释时，必须失败、跳过或进入审计，不得 silent fix。空间 JSON 必须由顶层 CRS 或每个含几何 feature 的等价 CRS 完整声明；比较采用 CRS 语义等价，不以字符串相等代替，也不把缺失 CRS 默认为目标 CRS。

## 7. 输出分层

| 输出 | 业务含义 |
|---|---|
| `t09_swsd_arms.*` | SWSD Arm 结构、Road 角色、special carrier 与风险。 |
| `t09_arm_movements.*` | Movement、真实方向、carrier universe 和兼容状态。 |
| `t09_evidence_items.*` | 三类原始 / 派生证据、优先级、条件和 provenance。 |
| `t09_restored_field_rules.*` | 带 DecisionStatus、RuleScope、override chain 的 SWSD 规则。 |
| `t09_swsd_field_rule_restoration_summary.json` | Step1/2 策略、计数、冲突、QA 与性能。 |
| `frcsd_restriction.*` | 已证明的稳定 Restriction F-RCSD 投影。 |
| `frcsd_restriction_candidates.*` | 未验证、待复核或不能安全提升的 F-RCSD 候选。 |
| `t09_step3_frcsd_restriction_summary.json` | stable / candidate、carrier、跳过、QA 与性能。 |

当前缺少 RCSD Laneinfo，因此 Laneinfo / special carrier 派生的 Road 级规则只能进入 candidates，并标记 `unverified_due_to_missing_frcsd_laneinfo`。

## 8. 决策与作用域

统一决策至少表达 `prohibited`、`supported`、`unknown`、`not_applicable`、`conflict`、`manual_review_required`、`unverified`。统一作用域至少表达：

- `arm_to_arm`
- `road_to_road`
- `road_to_arm`
- `road_direction_exclusion`
- `special_carrier`
- `core_junction_displacement`

现有 `ProhibitionStatus` 和 `field_rule_status` 是 v1 兼容字段，不再承担 v2 全部语义。每条 v2 结论必须记录策略、决策来源、scope、优先级、推理等级、验证状态、supporting / conflicting evidence、from/to road 和 Arm、Movement、condition payload、override chain 与风险。

## 9. 条件与时段

- `CondType` 和全部可追溯原始条件属性必须端到端保留。
- 只有正式字段定义存在时才能输出结构化时间窗、日期或车辆类型。
- 本轮没有正式定义的字段只进入 raw `condition_payload`，并标记 `condition_semantics_status=unknown`。
- 不同 raw condition identity 的 Road-Pair 不能合并证明全时 Arm 禁止。
- Step3 必须继承条件，禁止把条件 restriction 改写为硬编码普通全时禁止。

## 10. 什么是对

- 默认调用结果仍是 `restriction_only_v1`，显式 v2 才启用多证据决策。
- Restriction 高于 Laneinfo，Laneinfo 高于 special carrier，覆盖链完整。
- Laneinfo 只在完整有效时形成 Road 级结论；缺证据不是 prohibited。
- Restriction 仅在安全证明后提升 Arm scope；Road 级规则按具体 carrier 投影。
- stable 输出与缺 RCSD Laneinfo 的 candidate 明确分层。
- 所有输出可回溯输入、参数、证据、T06 relation、F-RCSD carrier、条件和跳过原因。

## 11. 什么是错

- 静默把 v2 设为默认或破坏 v1 基线。
- 因没有 allowed evidence 就输出 prohibited。
- 把 `9`、`o`、未知码、不完整或方向不匹配 Laneinfo 当强证据。
- 把单条 Road special 属性直接放大为整个 Arm / Movement 禁止。
- 把不同条件 payload 合并为全时禁止。
- 缺 RCSD Laneinfo 时伪造 F-RCSD Road 级验证通过。
- 缺 Relation、Road、Node 或几何时 silent fix。

## 12. 验收

- v1 默认与既有 T09 回归兼容，v2 可显式运行。
- Restriction、Laneinfo、special carrier 和优先级的 26 类场景有直接测试。
- 六个冻结 T10 Case 使用同一 upstream handoff 生成独立 v1/v2 对比工件。
- summary 清楚记录策略、scope、状态、条件、冲突、覆盖、候选、未验证、跳过、CRS、性能和 QA。
- 完成 CRS、拓扑、几何语义、审计追溯和性能验证。
