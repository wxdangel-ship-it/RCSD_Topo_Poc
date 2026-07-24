# P05-JSG-PTO-P3 任务清单

## T001 源事实与合同

- [x] 建立 P3 SpecKit、研究决策、数据模型和输出合同。
- [x] 同步项目/P05 source-of-truth 与 callable 合同。

## T002 Context dataset

- [x] 验证 P1/P2/M0 manifest、candidate/fold signature 与排除项。
- [x] 生成 ID-free self/dependency/reverse/case-profile context。
- [x] 完成 51 Case、191,331 groups、712,799 candidates leakage audit。

## T003 Neural scorer

- [x] 实现 candidate/context interaction network 与参数量门禁。
- [x] 实现 listwise loss、fold vocabulary、inner validation、early stopping。
- [x] 输出 checkpoint/model/context/score contract 与 ECE。

## T004 开发验证

- [x] candidate-only ablation 与小规模真实 Case probe。
- [x] 单 seed 5-fold OOF、逐类型/Review/资源误差诊断。
- [x] 冻结正式超参数。

## T005 正式验收

- [x] 执行 3 seeds × 5 folds。
- [x] 同 seed Run A/B 确定性验证。
- [x] PTO-A/PTO-B、RoadGraph、GIS、资源与 no-repair 审计。

## T006 测试与收口

- [x] 单元、泄漏、group loss、checkpoint、confidence 与破坏测试。
- [x] 完整 P05 回归测试。
- [x] validation summary、P3 GO/NO-GO 与 source-of-truth 完成态同步。
