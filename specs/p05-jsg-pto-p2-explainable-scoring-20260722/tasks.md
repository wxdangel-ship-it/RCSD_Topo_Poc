# P05-JSG-PTO-P2 任务清单

## T001 源事实与合同

- [x] 建立 SpecKit、数据模型、研究决策和输出合同。
- [x] 同步项目/P05 source-of-truth 与 callable 合同。

## T002 Dataset 与泄漏门禁

- [x] 验证 P1 candidate/label 与 M0 split/hash。
- [x] 生成 JSG/PTO ID-free feature tokens。
- [x] 生成 51 Case、5-fold、权重和 leakage audit。

## T003 V0/V1 scorer

- [x] 实现冻结 V0 显式代价。
- [x] 实现训练折内 V1 加性线性模型。
- [x] 输出可重建 explanation、margin/confidence/uncertainty。

## T004 PTO-A/PTO-B 与物化

- [x] 以 V0/V1 cost 完成 PTO-A/PTO-B 选择。
- [x] 验证 dependency、Review、multi-THROUGH 和 graph constraint。
- [x] 物化 selected JSG/Road/Node 并运行 evaluator。

## T005 测试

- [x] 单元、fold/ID 泄漏、未知 token、infeasible、确定性测试。
- [x] 完整 P05 回归测试（隔离 CPU `torch==2.9.1` 环境，94 passed）。

## T006 正式验收

- [x] Dataset formal run。
- [x] OOF Run A/B。
- [x] ranking/JSG/RoadGraph/GIS/resource/determinism audit。
- [x] validation summary 与 P2/P3 决策。
