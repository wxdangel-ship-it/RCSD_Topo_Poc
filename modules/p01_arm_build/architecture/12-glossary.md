# 12 术语表

- **P01**：POC 验证模块编号，本仓库中仍按标准模块目录结构治理。
- **P01-A**：Arm 构建阶段。
- **Semantic Junction**：按 `mainnodeid` 或单节点退化规则形成的语义路口。
- **Internal Road**：两端都在当前语义路口 member node 集合内的 Road。
- **Seed Road**：一端在当前语义路口、一端在外部的 Arm 追溯起点 Road。
- **InitialArm**：按 trace 终端聚合得到的初始 Arm。
- **FinalArm**：当前阶段等同 InitialArm，保留后续合并字段。
- **ThroughDecisionAudit**：trace 过程中对中间语义节点组的 through / stop 业务状态审计。
