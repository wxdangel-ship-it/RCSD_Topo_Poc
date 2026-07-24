# Tasks: P05 多任务神经 F-RCSD 直出 POC M2R

## Phase 1 - 产品与架构冻结

- [x] T001 [产品] 冻结 T03/T04/T05/T06 必选、T07 可选和最终 T06 RoadGraph 目标。
- [x] T002 [架构] 冻结模型业务内容所有权、通用约束白名单和零事后业务修图边界。
- [x] T003 [产品/架构/研发/测试/QA] 建立 spec/plan/research/data-model/output-contract/checklist/tasks。
- [x] T004 [架构] 同步 P05 与项目 source-of-truth、接口契约和 M2R callable。

## Phase 2 - 多任务监督就绪性

- [x] T005 [测试] 编写 T03/T04/T05/T06/T07 task target、Unknown mask、Error 非负类和 exclusion fixture。
- [x] T006 [测试/QA] 编写 artifact lineage/hash/CRS、归档版本 grouping 和跨 fold 泄漏 fixture。
- [x] T007 [研发] 实现 M2R supervision inventory 与任务级 target contract。
- [x] T008 [QA] 对真实 741 样本生成不可变 supervision run，统计每个任务的可用/Unknown/异常和类别 fold 覆盖。
- [x] T009 [产品/QA] 对 T03/T04 执行用户确认的正式策略重放，区分业务 rejected 与 runtime_failed；对仍无法证明的 output 形成最小复核清单。

## Phase 3 - 联合数据集

- [x] T010 [测试] 编写共享 scene graph、task mask、train-only normalization 和 label leakage fixture。
- [x] T011 [研发] 实现统一 scene graph/raster 特征与 grouped OOF 数据视图。
- [x] T012 [QA] 真实数据验证 candidate/target coverage、零泄漏、CRS 和性能。

## Phase 4 - 多任务模型

- [x] T013 [测试] 编写共享编码器及 T03/T04/T05/T06/T07 Head forward/loss/checkpoint fixture。
- [x] T014 [研发] 实现 `8M~20M` 共享编码器和任务 Head。
- [x] T015 [测试/研发] 实现任务 mask/权重、多任务 loss 和梯度贡献审计。
- [x] T016 [测试/QA] 对每个必选 Head 完成 small-batch overfit；未达 `0.95` 时停止对应 Head 泛化声明。

## Phase 5 - 解码与物化

- [x] T017 [测试] 编写 free decoder、通用约束、无合法动作和 intervention audit fixture。
- [x] T018 [研发] 实现 free/constrained decoder，共用同一模型 logits。
- [x] T019 [测试/研发] 复用并扩展 no-rule materializer，保证零事后内容修复。
- [x] T020 [QA] 合成与真实 Case 验证 CRS、引用、重复 ID、几何与有向拓扑 hard failure。

## Phase 6 - OOF训练、T07消融与最终判定

- [x] T021 [研发] 在 grouped folds 训练必选多任务模型，记录 checkpoint、seed、耗时、RAM/VRAM。
- [x] T022 [测试/QA] 生成全部 RoadGraph Case 的 OOF free/constrained 预测和逐 Case GPKG。
- [x] T023 [架构/QA] 执行 T07 on/off 消融，按冻结标准决定是否保留。
- [x] T024 [产品/QA] 核对中间 Head、Road F1、基线差值、最差 Case、属性和 hard failure。
- [x] T025 [QA] 核对约束触发率、原始/最终合法率和事后内容修复为零。

## Phase 7 - 完成审计

- [x] T026 [研发] 运行 P05 全量测试、编译和受影响最小回归。
- [x] T027 [架构] 检查源码体量、code-size audit、依赖和 entrypoint registry 一致性。
- [x] T028 [QA] 核对 CRS、拓扑、几何语义、审计追溯和性能五项证据。
- [x] T029 [产品/架构/研发/测试/QA] 逐项核对 FR-001~FR-027、SC-001~SC-015并形成 validation summary。
- [x] T030 按已修改/已验证/待确认交付，不把运行完成表述为目标成功。
