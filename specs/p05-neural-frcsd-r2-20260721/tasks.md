# Tasks: P05-R2 可完备 RoadGraph 生成 POC

## Phase 1 - Specify / Plan

- [x] T001 [产品] 冻结 R2 目标、数据范围、非生产边界和三道门禁。
- [x] T002 [架构] 冻结 Road/Node edit-set、精确 T05 pointer、oracle label-only 和通用约束边界。
- [x] T003 [产品/架构/研发/测试/QA] 建立 spec/plan/research/data-model/contract/checklist/tasks。
- [x] T004 [架构] 同步项目/P05 source-of-truth 和 R2 callable 契约。

## Phase 2 - Gate 1 表示完备

- [x] T005 [测试] 编写 COPY/UPDATE/SPLIT/CREATE/DROP、pointer 和 materializer fixture。
- [x] T006 [研发] 实现 R2 oracle edit encoder 与不可变输出。
- [x] T007 [研发] 实现 no-rule oracle materializer 和 normalized evaluator adapter。
- [x] T008 [QA] 对 51 Case 运行 oracle roundtrip，审计 coverage、CRS、引用、几何与有向拓扑。
- [x] T009 [产品/架构] 按 SC-001~SC-004 判定是否允许进入 Gate 2。

## Phase 3 - Gate 2 模型可学习

- [x] T010 [测试] 编写 R2 dataset、pointer/edit target、mask、泄漏和 normalization fixture。
- [x] T011 [研发] 实现 R2 dataset/query tensor 与 entity guard。
- [x] T012 [测试] 编写共享编码器、pointer/edit decoder、loss、梯度与 checkpoint fixture。
- [x] T013 [研发] 实现 `20M~50M` R2 模型和多任务 loss。
- [x] T014 [测试/QA] 完成必选 Head 与图编辑 small-batch overfit。
- [x] T015 [产品/架构] 按 SC-005~SC-007 判定是否允许进入 Gate 3。

## Phase 4 - Gate 3 grouped OOF

- [x] T016 [研发] 完成五折训练与资源记录。
- [x] T017 [研发/测试] 实现同 logits free/constrained 解码和 no-rule materialization。
- [x] T018 [QA] 生成逐 Case GPKG、task/edit/pointer 指标和 intervention audit。
- [x] T019 [QA] 完成重复推理确定性、最差 Case、基线和资源比较。
- [x] T020 [产品/架构] 按 SC-008~SC-016 形成 go/no-go。

## Phase 5 - 完成审计

- [x] T021 [研发] 运行 P05 全量测试、编译和最小回归。
- [x] T022 [架构] 检查源码体量、依赖、entrypoint registry 和 source fact 一致性。
- [x] T023 [QA] 核对 GIS 五项证据和全部 manifest/hash。
- [x] T024 [产品/架构/研发/测试/QA] 逐项形成 R2 validation summary。
- [x] T025 按已修改/已验证/待确认正式交付。
