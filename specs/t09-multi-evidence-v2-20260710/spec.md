# Spec：T09 多证据通行规则恢复能力升级

## 1. 文档定位

本文件是本轮变更的 SpecKit 需求工件，用于记录变更范围和验收依据；长期有效的业务口径以 `modules/t09_swsd_field_rule_restoration/SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/` 为准。本工件不替代模块级源事实。

## 2. 目标

在不静默改变现有 T09 口径的前提下，新增显式 `multi_evidence_v2` 策略，把 T09 从 `Restriction-only` 扩展为统一的多证据决策与作用域感知投影：

```text
Restriction > Laneinfo > 提前左转 / 提前右转
```

原调用方式继续默认使用 `restriction_only_v1`。是否将 v2 改为默认策略不属于本轮开发裁量范围。

## 3. 五类职责视角

### 3.1 产品视角

- 保留 restriction 的基础 Road-Pair 身份 `(restriction_id, in_link_id, out_link_id)`；v2 完整证据实例再包含 `condition_identity`，不把局部或条件性限制误报为全 Arm、全时禁止。
- 完整有效 Laneinfo 可形成 Road 级支持或方向排除；缺失、不完整、方向不匹配、`9`、`o` 或未知码只能得到 `unknown`。
- 提前左转 / 提前右转按 Arm 汇总，只形成弱推导；正式识别字段为 `formway & 256` 和 `formway & 128`。
- 缺少 RCSD Laneinfo 时，Laneinfo / special carrier 派生的 Road 级结果进入未验证候选，不混入稳定 F-RCSD restriction。

### 3.2 架构视角

- Step1/2 负责 SWSD 规则恢复，Step3 负责作用域感知的 F-RCSD 投影，两阶段不互相改写上游事实。
- 统一对象必须表达 `DecisionStatus`、`RuleScope`、`EvidencePriority`、`VerificationStatus`、`InferenceLevel`、条件 payload、provenance 与 `override_chain`。
- Restriction 提升为 `arm_to_arm` 必须有可审计的完整等价 carrier 证明；Road 级规则不得通过 Arm carrier 笛卡尔积放大。
- 每个 `condition_identity` 必须独立评估 scope promotion；完整条件组可以提升，partial 或 manual-review 条件组必须保持原子规则，禁止跨条件拼接覆盖。
- 多 Road 等价优先消费正式 T01 Segment membership 或显式 parallel-branch 审计；Road 自带 segmentid 与 T01 冲突时不得作为 membership 等价依据，只有独立的显式 parallel-branch 审计才能提供替代证明。同一 raw Restriction geometry 一对多匹配（geometry fan-out）必须转人工复核，未经唯一性证明不得进入 verified stable。
- 稳定输出与候选输出分层：`frcsd_restriction.*` 只承载已证明的 restriction 规则，`frcsd_restriction_candidates.*` 承载未验证或待复核候选。

### 3.3 研发视角

- 两个既有 callable 保持可用，通过显式 `strategy_version` 选择策略，默认值为 `restriction_only_v1`。
- 扩展 schema、输入条件继承、Laneinfo Road 级聚合、special carrier Arm 级分析、统一决策、输出与 Step3 投影。
- 不修改 T06、T08、T10 实现、对外调用接口、正式入口或业务输入，不新增 CLI、root script、Makefile 目标或模块主入口；仅按用户授权同步 T10 当前统计基线文档。
- 未定义条件字段只保留 raw payload 并标记语义未知；不得从局部数据反推字段含义。

### 3.4 测试视角

- 保留并执行现有 T09 回归，证明 v1 默认兼容。
- 新增覆盖 Restriction、Laneinfo、special carrier、优先级和 F-RCSD 投影的 26 类场景。
- 对冻结 T10 六 Case 使用同一组 T01/T06 handoff 分别运行 v1 与 v2，比较兼容字段和业务增量。

### 3.5 QA 视角

- 检查 CRS 与坐标变换、拓扑一致性、几何语义、输入参数与运行环境追溯、阶段耗时。
- 检查所有冲突、覆盖、跳过、条件未知、候选和未验证结果都进入结构化输出或 summary，不得仅记日志。
- 检查 Road 级规则没有 Arm 级扩张、缺 RCSD Laneinfo 没有伪造验证通过、T06 carrier 缺口没有 silent fix。

## 4. 范围

### 4.1 本轮包含

- T09 正式需求、契约和架构文档同步。
- v1/v2 策略与审计字段。
- Restriction 安全作用域判定和条件继承。
- Laneinfo Road 级支持 / 排除及禁左与调头联动。
- 提前左转 / 提前右转 Arm 级弱推导。
- 统一优先级与覆盖链。
- 稳定 / 候选两层 F-RCSD 输出。
- 单元、集成和六 Case 基线对比。
- 用户授权的 T10 当前统计基线文档同步；不修改 T10 编排实现或调用契约。

### 4.2 本轮不包含

- 将 `multi_evidence_v2` 设为默认策略。
- 新增或推断 RCSD Laneinfo、轨迹规则或未定义条件字段语义。
- 生成 F-RCSD `RoadNextRoad` 或独立重建 F-RCSD Arm。
- 修改 T06、T08、T10 实现、对外调用接口、正式入口或业务输入；用户授权的 T10 当前统计基线文档同步除外。
- 新增正式执行入口。

## 5. 核心需求

1. Restriction、Laneinfo、special carrier 进入同一证据框架，优先级固定为 `Restriction > Laneinfo > special carrier`。
2. 每次高优先级覆盖必须记录高低优先级证据、原因、原始 ID、结果和风险。
3. 规则作用域至少区分 `arm_to_arm`、`road_to_road`、`road_to_arm`、`road_direction_exclusion`、`special_carrier`、`core_junction_displacement`。
4. 决策至少表达 `prohibited`、`supported`、`unknown`、`not_applicable`、`conflict`、`manual_review_required`、`unverified`。
5. Restriction 基础 Road-Pair 身份固定为 `(restriction_id, in_link_id, out_link_id)`；v2 完整实例身份还包含 `condition_identity`，同一 ID 下的 Road-Pair 与不同 condition 不得折叠。
6. 每个 `condition_identity` 必须独立评估 carrier 覆盖与 scope promotion；完整组、部分组和人工复核组分别保留，禁止跨 condition 拼接成全时 Arm 禁止。
7. 多 Road 等价必须由正式 T01 Segment membership 或显式 parallel-branch 审计证明；Road 自带 segmentid 与 T01 冲突时不得作为 membership 等价依据，只有独立的显式 parallel-branch 审计才能提供替代证明。
8. 同一 raw Restriction geometry 一对多匹配多个 Road-Pair（geometry fan-out）时必须保留 ambiguity 并转人工复核，未经额外唯一性证明不得提升或进入 verified stable。
9. Laneinfo 只有在方向匹配、车道序列完整、所有 code 可解释且目标 Movement 存在时才能形成确定结论。
10. 缺左转箭头时左转受限，调头原则上联动受限；明确调头箭头只解除调头联动，不解除左转排除。
11. `formway & 128` 表示提前右转候选，`formway & 256` 表示提前左转候选；`kind` 后缀不作为强判定。
12. special carrier 必须按 Arm 汇总，只形成 `weak_derived` 结论，不能由单 Road 属性放大为整个 Movement 禁止。
13. F-RCSD stable 输出只接收已证明的 Restriction Arm 级规则或可精确映射的 Restriction Road-Pair；缺 RCSD Laneinfo 的 Road 级派生规则进入 candidates。
14. `CondType` 与原始条件属性端到端保留；语义不明时标记 unknown，不猜时间窗或适用对象。
15. summary 必须记录实际策略版本、状态 / scope 计数、冲突、覆盖、候选、未验证、跳过、CRS、性能和 QA。

## 6. 验收场景

以下 26 类场景必须由测试直接覆盖：

1. Restriction 禁止而 Laneinfo 支持，Restriction 获胜并记录冲突。
2. 同一 Restriction ID 的多组 Road-Pair 独立保留。
3. Restriction 部分覆盖不提升为全 Arm。
4. Restriction 完整覆盖等价 carrier 后可提升为 Arm-to-Arm。
5. 条件 / 分时 Restriction 保留原始条件且不扁平化。
6. 完整 Laneinfo 缺右转且存在右转 Movement，生成 Road 级排除。
7. 任一有效车道支持右转时，不生成右转排除。
8. 缺左转且缺调头箭头时，左转与调头均受限。
9. 缺左转但明确支持调头时，只限制左转。
10. `9`、`o`、未知码或序列不完整得到 unknown。
11. Laneinfo 与 Road 方向不匹配时不做确定推理。
12. Arm 有提前右转且主路无右转箭头时，形成位移 / 弱候选并支持特殊 Road 右转。
13. Arm 有提前右转且主路明确支持右转时，Laneinfo 覆盖弱推导。
14. 提前右转 Road 无其它方向箭头时，其它方向只形成弱候选。
15. 提前右转 Road 明确支持直行时，不限制直行。
16. 提前左转对称场景得到同等覆盖。
17. 辅路提右、绕开核心路口提右与路口前提右得到不同 carrier / displacement 状态。
18. 三类证据同时冲突时 Restriction 获胜并输出完整覆盖链。
19. 无 Restriction、Laneinfo 与 special carrier 冲突时 Laneinfo 获胜。
20. 仅 special carrier 时只形成弱推导。
21. Arm-to-Arm Restriction 生成稳定 F-RCSD restriction。
22. Laneinfo Road 级规则不扩张为整个 Arm restriction。
23. 缺 RCSD Laneinfo 时 Road 级派生结果进入未验证 candidates。
24. `replaced`、`retained_swsd`、`replaced+retained_swsd` carrier 映射正确。
25. retained SWSD seed fallback 可回溯并带风险标记。
26. 缺 Relation、Road、Node 或方向不可解释时明确跳过并记录原因。

## 7. 六 Case 基线验收

冻结基线：

```text
/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full
```

Case：`1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176`。

基线参考为 T10 `6/6 passed`，T09 v1 合计 `8947` Arms、`29145` Movements、`31112` Evidence、`3265` restored rules、`4357` stable F-RCSD restrictions。实施后必须以冻结产物重新核对这些数字，不把本 Spec 中的记录替代运行证据。

验收方式：复用每个 Case 的同一 T01/T06 handoff，在两个全新输出根分别运行默认 v1 与显式 v2。v1 对兼容字段、规则身份、状态和 stable restriction 做回归；v2 按 Case 与合计报告 DecisionStatus、RuleScope、override、condition、candidate / unverified、跳过与耗时变化。

## 8. 完成定义

- 模块正式文档、接口契约、代码和测试采用同一口径。
- v1 默认行为经单测和六 Case 回归证明兼容。
- v2 26 类场景全部通过，且六 Case 结果有独立、可定位的对比工件。
- GIS / 拓扑 / 几何语义 / 审计 / 性能五项 QA 均有结构化证据。
- 没有修改范围外模块、输入或官方入口。
