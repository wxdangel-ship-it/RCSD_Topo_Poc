# Research：现有资产与方案决策

## 1. 可继承资产

1. T01 冻结骨架、T07 前置证据和 T10 Case 组织可直接继承。
2. P05 已有 inventory、Case split、artifact hash、候选检索、Road/Node 对齐、
   OOF 与安全 gate 代码可复用其基础设施，但旧标签本体不能直接继承。
3. T03/T04 单点 Case、T10 Case/Segment 标签、T11 人工锚定记录和五个人工裁决
   共同构成联合训练监督。
4. T06 成功替换标准可用于结构化标签与评价：方向、端点、required junction、Road
   完整性、所有权、拓扑和 surface 证据。
5. P12R/P12R-R1 已证明 AdvanceRight 候选覆盖基本足够；应改变条件化表征，而不是
   继续扩候选。

## 2. 历史实验结论

- M2R（约 18.32M）：OOF Road F1 约 0.64653，51/51 有向拓扑失败；
- R2（约 40.19M）：能小批过拟合且 Oracle 可表达，但 OOF Road F1=0、
  pointer accuracy=0、51/51 拓扑失败；
- P13-P0（480,739 参数）：只做 AdvanceRight candidate-local carrier scorer，
  raw exact=0.646907，低于 5m Local Control=0.680412；accepted coverage=0.017677，
  unsafe auto RCSD=14、Review auto=2、unreachable auto=1。

这些结果否定旧表示/旧 scorer 和自由生成训练方式，不否定联合神经系统。P13 的核心
缺陷是无法观察相邻普通 Segment 完成替换后的最终 access Road 状态。

## 3. 方案比较

### 方案 1：分层多任务 Graph/Set Transformer + 约束 decoder（采用）

- shared encoder：几何 polyline encoder + Set Transformer + 稀疏异构 Graph
  Transformer；
- heads：anchor、ordinary plan、clue/risk、AdvanceRight conditional；
- decoder：普通 Segment 冲突组先求解，锁定 access 后求解提右；
- 规模：建议 10M–20M；
- 优点：符合业务先后关系，可复用所有分层标签，易做 OOF 条件化和结构化安全 gate；
- 风险：plan candidate schema 和弱标签 mask 复杂。

### 方案 2：联合潜变量 teacher-student

- teacher 学习 T03–T06 终态与隐藏中间状态，student 只消费推理事实；
- 优点：可利用未完全审核的 Case 级弱标签；
- 风险：teacher 容易把旧策略偏差蒸馏给 student，且难证明无终态泄漏；
- 结论：可作为后续预训练，不作为首个正式实现。

### 方案 3：端到端 constrained pointer decoder

- encoder 后直接对 Road/Node/打断位置做指针式组合生成；
- 优点：输出表达力高；
- 风险：现有样本规模下 pointer 学习不稳定，R2 已提供负面证据；
- 结论：只保留为 plan head 内部的候选选择机制，不单独承担全图自由生成。

## 4. 关键技术决策

采用“方案 1 encoder + 方案 3 的候选约束 decoder”：

- encoder 联合学习锚定、Road 几何、局部拓扑和共享冲突上下文；
- decoder 只能在 truth-free 生成的完整 plan candidates 中选择；
- 锚定结果是后续硬条件并 stop-gradient；
- ordinary 训练先 teacher forcing，再换成 cross-fit/OOF anchor 条件；
- AdvanceRight 先 teacher forcing 读取 ordinary truth access，再逐步换成 OOF
  ordinary access；
- 多解标签使用 acceptable-set marginal loss，preferred 只作次级排序损失；
- 不明原因的 `no_valid_relation` 只监督 anchor 不成功，不补造 KEEP 或 clue 原因。

## 5. 现有监督仍不能识别的内容

第一版明确缺少“同一个 SWSD 语义路口同时对应 RCSD Junction + RCSD Road 并需要
联合打断”的人工标签。该场景不是泛泛的数据不足，而是缺少复合锚定对象、Road 和打断
位置三者的联合监督，因此第一版必须输出 `UNSUPPORTED_COMPOSITE_ANCHOR` 并回退。

城市级性能也不能由现有小 Case 证明；这需要无标签城市数据的 I/O、显存和 decoder
连通组 profile，不要求新增人工标签。
