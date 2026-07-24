# P05-JSG-PTO-P1 研究决策

## R-001：不重新训练 scorer

P1 先证明候选域和约束可解性。候选缺失或约束错误不能由模型训练掩盖。

## R-002：复用 truth-free RoadGraph candidate

既有 `p05_pto_candidate_20260721_02` 已记录 `truth_input_count=0`、`truth_derived_candidate_count=0`，且 Road/Node candidate reachability 已在历史 PTO-P0 证明。P1 复用其候选/lineage 基础设施作为 PTO-B 输入，但重新验证 manifest/hash，不复用其 Oracle 结论冒充 P1。

## R-003：PTO-A 使用 carrier-free 语义投影

StandardSegment 的 carrier IDs、Relation access legs、Movement path 和 Connector carrier 属于 PTO-B；PTO-A reachability 比较身份、端点、附属 Junction、结构角色、方向、类型、状态和 loop 等业务语义字段。这样避免把 T06 truth carrier 泄漏到候选层。

## R-004：候选 alternatives 有限化

Junction/Segment/Relation 只枚举合同内有限 enum；Movement 只在同一 Junction incident Segment 间生成；Connector 只对应 T01 `advance_right`。禁止全 Case 任意 Junction/Segment 笛卡尔积。

## R-005：在线性能结论分层

P1 从冻结 candidate 开始验证增量链资源；历史 strategy replay 成本继续列入上游 proposal 成本。即使 P1 增量链通过，也不能自动改写 RoadGraph PTO-P0 的在线性能 no-go。
