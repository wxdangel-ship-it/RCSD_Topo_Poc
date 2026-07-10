# Plan：T09 多证据通行规则恢复能力升级

## 1. 实施原则

- 先同步模块级源事实和接口契约，再实现，再做分层验证。
- `restriction_only_v1` 保持默认；`multi_evidence_v2` 必须显式选择。
- SWSD 规则恢复与 F-RCSD 投影分层，Road 级结论不在 Step3 放大。
- 新字段只表达任务书已确认的语义；条件字段语义不清时保留 raw 并标记 unknown。
- 不修改 T06/T08/T10 实现、对外调用接口、正式入口或业务输入；只同步用户已授权的 T10 当前基线源事实文档。

## 2. 方案分层

| 层 | 计划 | 主要证据 |
|---|---|---|
| 文档与契约 | 同步 SPEC、INTERFACE_CONTRACT、architecture 01-06 | 文档 diff、`git diff --check` |
| Schema | 增加策略、决策、scope、优先级、验证、条件和覆盖链字段 | schema 单测、序列化回归 |
| Restriction | 保留 Road-Pair / condition identity，逐 condition 消费正式 T01 或显式 parallel 证明，并拦截 geometry fan-out | Restriction 场景 1-5 与直接 Gate 测试 |
| Laneinfo | 按进入 Road 聚合完整车道序列和方向并集 | Laneinfo 场景 6-11 |
| Special carrier | 用 formway bit 识别候选，按 Arm 与核心路口拓扑分析 | 场景 12-17 |
| 决策 | 统一执行 Restriction > Laneinfo > special carrier | 场景 18-20 |
| Step3 | stable / candidate 分层与 scope-aware carrier 映射 | 场景 21-26 |
| 六 Case | 同 upstream handoff 跑 v1/v2 并生成差异报告 | 两个 run root、对比表、summary |

## 3. 研发拆分

### 3.1 Schema 与兼容层

- 在现有 `ProhibitionStatus` 兼容层之外增加统一决策枚举。
- 给两个 callable 增加默认 `strategy_version="restriction_only_v1"`；调用方不传参时保持 v1。
- 让新增字段具有兼容默认值，GPKG / CSV / JSON 字段同步。
- summary 和 restored rule 记录策略版本；Step3 拒绝或审计策略不一致输入。

### 3.2 Restriction 与条件

- 保留 `(restriction_id, in_link_id, out_link_id)` 基础 Road-Pair 匹配身份；v2 完整实例再包含 `condition_identity`。
- 从输入 properties 继承 `CondType` 和全部 raw condition payload。
- 每个 condition identity 独立评估 carrier 覆盖与 scope promotion；两个完整条件分别提升，完整与 partial 混合时各自保持独立结果，不跨 condition 合并。
- 多 Road 等价优先消费正式 T01 Segment membership 或显式 parallel-branch 审计；输出 `t01_segment_ids / segment_membership_status`。Road 自带 segmentid 与 T01 冲突时不得作为 membership 等价证明，只有独立的显式 parallel-branch 审计才能提供替代证明。
- 同一 raw Restriction geometry 一对多匹配多个 Road-Pair 时保留 evidence 与 ambiguity，转人工复核且不得进入 verified stable。
- 输出 `road_pair_explicit / arm_to_arm_confirmed / partial_coverage / suspected_arm_to_arm / manual_review_required` 的提升审计。

### 3.3 Laneinfo 与 special carrier

- Laneinfo 按 approach Road 汇总全部 lane code；完整性、方向和可解释性任一失败即 unknown。
- 只在目标 Movement 存在时形成方向支持 / 排除。
- 加入左转—调头联动和明确调头箭头例外。
- special carrier 使用 `formway & 128/256` 识别，按 Arm 角色和核心路口拓扑分类；不使用 `kind` 后缀作为强规则。

### 3.4 统一决策与输出

- 建立确定性优先级决策器，记录 supporting / conflicting evidence 和 override chain。
- v1 继续只让 restriction 改变禁行结论。
- v2 允许完整 Laneinfo 形成 Road 级结论，special carrier 只形成弱推导。
- Step3 stable 只消费可证明 scope；未验证 Road 级派生规则写入 candidates。

## 4. 测试计划

### 4.1 单元与集成

- 现有 T09 测试必须继续通过。
- 新增独立 v2 测试文件，逐项映射 Spec 的 26 类场景，并直接覆盖逐 condition 完整/部分组合、正式 T01 membership 冲突和 raw geometry fan-out Gate。
- 增加 v1 默认参数与显式 v1 等价测试、输出序列化测试、条件 raw round-trip 测试。

### 4.2 六 Case 对比

1. 从冻结基线定位六 Case 的 T01、T06 与 T08 handoff。
2. 在全新输出根运行默认 v1，禁止覆盖冻结基线。
3. 在另一全新输出根显式运行 v2。
4. v1 对比兼容字段、规则 key、stable restriction key 与计数。
5. v2 输出逐 Case和合计状态 / scope / source / override / condition / candidate 变化。
6. 对差异抽样回溯到原始 evidence、Movement、T06 relation 和 F-RCSD carrier。

## 5. QA Gate

| Gate | 通过标准 |
|---|---|
| CRS | 输入 CRS、目标 CRS 和坐标变换写入 summary；缺 CRS 显式失败 / 跳过 |
| 拓扑 | Road/Arm/Movement/T06 carrier 对应可解释，任何缺口无 silent fix |
| 几何 | restriction 和 candidate 几何可回溯到具体 carrier；构造失败有原因 |
| 审计 | strategy、condition、evidence、override、scope、verification、skip 全可定位 |
| 性能 | summary 有阶段耗时；六 Case v1/v2 报告可比较耗时，不接受未说明的数量级退化 |
| 范围 | 除用户授权的 T10 基线源事实文档外，`git diff` 不包含 T06/T08/T10 实现、接口、入口或业务输入 |

## 6. 风险与回退

- 若条件字段定义不充分：只保留 raw payload 和 unknown，不进入强规则。
- 若 Restriction 无法证明 Arm scope：保留 Road-Pair / partial，不提升。
- 若 special carrier 拓扑类型无法区分：输出 unknown / manual review，不猜测。
- 若缺 RCSD Laneinfo：Road 级派生结果只进 candidates。
- 若 v1 回归不一致：先修兼容层，不以 v2 收益替代 v1 Gate。

## 7. 交付顺序

1. SpecKit 与正式文档。
2. Schema / 输入 / 决策实现。
3. Laneinfo、special carrier、Restriction scope 实现。
4. stable / candidates 输出与 Step3。
5. 单测、全量 T09 回归、六 Case v1/v2。
6. 完成审计、变更说明和剩余限制清单。
