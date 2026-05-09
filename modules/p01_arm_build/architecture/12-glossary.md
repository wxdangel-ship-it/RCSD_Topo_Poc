# 12 术语表

- **P01**：POC 验证模块编号，本仓库中仍按标准模块目录结构治理。
- **P01-A**：Arm 构建阶段。
- **Semantic Junction**：按 `mainnodeid` 或单节点退化规则形成的语义路口。
- **Internal Road**：两端都在当前语义路口 member node 集合内的 Road。
- **Seed Road**：一端在当前语义路口、一端在外部的 Arm 追溯起点 Road。
- **InitialArm**：按 trace 终端聚合得到的初始 Arm。
- **FinalArm**：最终 Arm 输出。默认等同 InitialArm；在 trace 过度切碎且 LocalArmCandidate 完整覆盖时，可采用局部趋势兜底聚合。
- **ThroughDecisionAudit**：trace 过程中对中间语义节点组的 through / stop 业务状态审计。
- **ArmProfile**：A2 从 A1 FinalArm 归一化得到的配准画像。
- **LogicalArmGroup**：A2 跨 SWSD / RCSD / F-RCSD 后认为表达同一个真实 Arm 的逻辑分组。
- **RawArmAlignment**：A2 以 F-RCSD 为目标承载体输出的源 Arm 直接配准关系。
- **ArmBuildFeedback**：A2 对 A1 可能 over_split、over_merged 或规则不足的反馈对象；不直接改写 A1 输出。
- **ArmMovement**：A1 单源 Arm 到 Arm 的客观动作候选，不等同于允许通行。
- **SourceMovementPolicy**：P01-Final 中由 SWSD / RCSD RoadNextRoad evidence 形成的 role-level allowed policy。
- **F-RCSD RoadNextRoad**：P01-Final 生成的最终 F-RCSD 道路级允许通行关系。
