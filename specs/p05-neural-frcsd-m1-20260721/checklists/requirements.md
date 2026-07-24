# Specification Quality Checklist: P05 M1

- [x] 目标固定为直接生成 T06 F-RCSD Road/Node，而非中间 replaceable。
- [x] 输入与 T06 label-only 边界明确。
- [x] `0.7/0.3` RoadGraph 权重与 T03/T04 `1.0` 辅助任务边界明确。
- [x] M0 Case split 的实体重叠风险有独立门禁。
- [x] DROP/KEEP/SPLIT 和 uncovered truth 分母无歧义。
- [x] 确定性 baseline、MLP baseline 和图模型可公平比较。
- [x] 固定 test、开发 CV 和标准 T10 shadow holdout 分层。
- [x] materializer no-business-rule、no-silent-fix 边界明确。
- [x] CRS、拓扑、几何、审计、性能五项完整。
- [x] 产品、架构、研发、测试、QA 五类职责完整。
- [x] optional 训练依赖与无正式 repo CLI 边界明确。
- [x] 成功标准可量化，无 NEEDS CLARIFICATION。

