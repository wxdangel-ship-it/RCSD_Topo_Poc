# Research: P05-PTO-P0

## 决策 1：先验证候选空间，不直接训练第二个 decoder

R2 Gate 1/2 已排除“输出语言不完备”和“完全不可学习”，Gate 3 暴露的是跨 Case object matching 失败。PTO 将生成拆成“高召回候选”和“全局评分选择”；P0 只证明候选可达和约束可解，避免在候选缺失时继续消耗训练资源。

## 决策 2：业务策略只作 proposal，不作最终判定

T03/T04/T05/T06 可以从 raw/T01 产生具有业务语义的有限候选。PTO 不把策略结果当作最终 RoadGraph，而是将其转换为 R2 edit/pointer 候选；未来由 learned scorer 决定选择。P0 的 Oracle cost 只验证正确选择存在。

## 决策 3：允许独立重放与 truth 内容相同

禁止的是 truth-derived proposal，不是确定性策略恰好重放出相同结果。候选必须通过代码 commit、外部输入 hash、命令和输出路径证明独立来源；候选路径不得等于 truth 路径，且候选 manifest 必须在标签层之前冻结。

## 决策 4：复用 R2 edit language 和物化器

Road `COPY/UPDATE/SPLIT/CREATE/DROP`、Node `COPY/UPDATE/CREATE/DROP` 与精确 T05 pointer 已在 51 Case 证明完备。PTO 不创建第二套对象语义，只新增候选来源、去重、cost 和 group-choice 约束。

## 决策 5：P0 使用可证明最优的分组 exact solver

每个 base object group 选择一个候选 action；CREATE/pointer 采用显式选择组。Oracle cost 对 truth-equivalent 候选赋零成本，其它候选为正成本。只有当所有局部最小选择组成的全局图也满足通用约束时，局部下界之和才是全局下界，因而得到 gap=0 证书；若耦合约束使其不可行，P0 失败，不通过修图或放宽约束掩盖。

## 决策 6：性能口径分层且不隐藏 replay

策略全量重放可能比未来候选生成服务慢。正式报告同时给出：replay、候选构建、求解、物化评价和端到端耗时。缓存 replay 可用于重复开发，但不能替代端到端成本结论。
