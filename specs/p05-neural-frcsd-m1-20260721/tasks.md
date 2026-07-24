# Tasks: P05 神经网络 F-RCSD 直出 POC M1

## Phase 1 - 产品与架构冻结

- [x] T001 [产品] 冻结 M1 可学习性目标、T06 最终 RoadGraph 评价分母和非生产边界。
- [x] T002 [架构] 完成真实候选空间、SPLIT 操作和跨 split Road ID 预审计。
- [x] T003 [产品/架构/测试/QA] 建立 spec/plan/research/data-model/output-contract/checklist。
- [x] T004 [架构] 同步 P05 模块 source-of-truth 与 M1 Python callable 契约。

## Phase 2 - 数据与泄漏门禁

- [x] T005 [测试] 编写冻结 M0 读取、t01_roads lineage、approved exclusion 和 hash fixture。
- [x] T006 [测试/QA] 编写 Case/Segment `0.7/0.3` 权重与 missing target relation fixture。
- [x] T007 [测试/QA] 编写跨 split entity priority 和一跳邻域移除 fixture。
- [x] T008 [研发] 实现 M1 candidate RoadGraph、操作标签、split geometry label 和 train-only normalization。
- [x] T009 [QA] 对真实 51 Case 生成不可变 dataset run，核验候选规模、operation coverage、uncovered truth 和零泄漏。

## Phase 3 - 基线

- [x] T010 [测试] 编写 keep-all、source-priority 和预测输出 schema fixture。
- [x] T011 [研发] 实现两种确定性 baseline 与统一逐对象预测格式。
- [x] T012 [研发/测试] 实现不使用图边的 MLP baseline、checkpoint 和固定 seed 重放。
- [x] T013 [QA] 在 validation 与开发集 CV 上冻结最强 baseline 和阈值，不访问固定 test 指标。

## Phase 4 - 图神经网络与物化

- [x] T014 [测试] 编写图模型 forward/loss/参数量/checkpoint fixture。
- [x] T015 [研发] 实现约 10M 参数的 RoadOperationGraphNet 和多任务加权 loss。
- [x] T016 [测试] 编写 KEEP/DROP/SPLIT_1/2/3、无效切分、Node 引用和 no-silent-fix 物化 fixture。
- [x] T017 [研发] 实现 Road/Node 确定性物化器和 per-Case 推理。
- [x] T018 [测试/QA] 用 M0 evaluator 对合成预测验证 CRS、属性、几何与有向拓扑门禁。

## Phase 5 - 训练与模型选择

- [x] T019 [研发] 建立隔离 PyTorch 运行环境，记录版本/CUDA/GPU，不污染核心依赖。
- [x] T020 [研发] 训练 MLP 和图模型，记录 seed、loss、wall time、RAM/VRAM、checkpoint hash。
- [x] T021 [测试/QA] 在 46 个开发 Case 内执行 group CV，报告均值/标准差/最差 fold。
- [x] T022 [架构/QA] 完成无图、无语义节点、无低可信上下文的消融，冻结模型与阈值。
- [x] T023 [产品/QA] 执行标准 T10 shadow holdout，单独记录分布风险。

## Phase 6 - 最终评估与完成审计

- [x] T024 [产品/QA] 对固定 test 5 Case 执行一次性最终评估，输出逐 Case GPKG 和指标。
- [x] T025 [QA] 核对 Road F1、基线差值、direction/source、最差 Case 与 hard failures。
- [x] T026 [QA] 核对 CRS、拓扑一致性、几何语义、审计追溯和性能五项证据。
- [x] T027 [研发] 运行 P05 全量测试、编译和受影响最小回归。
- [x] T028 [架构] 检查所有新增/修改源码体量、code-size audit、依赖与 entrypoint registry 一致性。
- [x] T029 [产品/架构/研发/测试/QA] 逐项核对 FR-001~FR-022、SC-001~SC-010，形成 validation summary 和 M2 go/no-go。
- [x] T030 按已修改/已验证/待确认交付，不把未达门槛表述为完成。
