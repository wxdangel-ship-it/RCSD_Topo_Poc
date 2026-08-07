# Analyze：跨工件一致性检查

## 结论

`spec.md`、`research.md`、`data-model.md`、`contracts/training-contract.md`、
`plan.md` 和 `tasks.md` 对目标边界、业务顺序、标签作用域、训练隔离和验收口径一致，
可以进入 implement。

## 产品视角

- 用户目标是替代 T03–T06 核心业务判断，不是继续优化局部 AdvanceRight scorer；
- positive KEEP 与 ABSTAIN fallback 已分离；
- 完整 Road 方案和整图 exact 是主指标。

## 架构视角

- T01/T07/T10 边界稳定；
- anchor -> ordinary -> locked access -> AdvanceRight 顺序不可反转；
- decoder 只组合完整候选，不重做业务事实；
- 城市 I/O 使用 immutable cache 和动态依赖子图；T01 依赖只作 encoder
  上下文。decoder 联合约束候选所有权，但 fallback 采用显式有限
  Segment/Junction directive，不计算传递连通组。

## 研发视角

- 新代码与历史 P13/M2R/R2 隔离为 `target_a_*`；
- 不修改 T01–T12 实现/接口，不新增生产入口；
- inference feature 与 label store 物理隔离。

## 测试视角

- 每项业务硬门禁均在 tasks 中有 unit/integration 项；
- OOF、acceptable-set、权重/mask 和 leakage 有独立验证；
- 几何容差不能掩盖业务对象选择错误。

## QA 视角

- 输入、hash、CRS、配置、split、checkpoint、ledger 可追溯；
- 零 silent fix；
- 硬安全门失败只能 NO_GO；
- 完整策略 paired comparison 和最差 fold/category 必须报告。

## 已知边界

- RCSD Junction + RCSD Road 复合锚定缺少联合人工标签，第一版安全回退；
- 现有小 Case 不能证明城市级性能，需无标签城市 profile；
- 这两项不要求用户新增已标注 Case，也不改变当前实现启动条件。
