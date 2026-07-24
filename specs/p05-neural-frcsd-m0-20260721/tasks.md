# Tasks: P05 神经网络 F-RCSD 直出 POC M0

## Phase 1 - 产品与架构冻结

- [x] T001 冻结 T06 F-RCSD Road/Node 主目标和 P05 POC 非发布边界。
- [x] T002 冻结 `POC_Data` 范围、`1.0/0.7/0.3` 标签合同和 task mask。
- [x] T003 完成 spec/plan/research/data-model/output-contract/checklist。
- [x] T004 建立 P05 模块 `SPEC/architecture/INTERFACE_CONTRACT`，同步项目生命周期与盘点。

## Phase 2 - 测试先行

- [x] T005 [测试] 写 inventory fixture：T03/T04、T10 Case、T10 Segment、缺失 manifest、范围越界。
- [x] T006 [测试] 写 label fixture：passed run、缺 Road/Node、WSL 路径、wrong source root。
- [x] T007 [测试] 写 split fixture：重复 ID、确定性、五折与零泄漏。
- [x] T008 [测试/QA] 写 RoadGraph Oracle 与缺 Road、方向/source、端点、拓扑破坏测试。

## Phase 3 - M0 实现

- [x] T009 [研发] 实现 models 与稳定 schema/error code。
- [x] T010 [研发] 实现 `POC_Data` inventory 和 manifest/hash 审计。
- [x] T011 [研发] 实现 canonical baseline/run handoff 解析与 label artifact 表。
- [x] T012 [研发] 实现确定性 sample group、fold 和 split。
- [x] T013 [研发] 实现 identity-first、geometry-fallback Road/Node evaluator。
- [x] T014 [研发] 实现不可变 outputs、summary/report 和模块 callable。

## Phase 4 - 本地真实数据验证

- [x] T015 [QA] 对 689 份 T03/T04 manifest 和 52 个 T10 package 做完整清点。
- [x] T016 [QA] 对六案与 52 Case canonical baseline 解析 T01-T06 lineage。
- [x] T017 [测试/QA] 运行真实 T06 truth-vs-truth Oracle，验证 SC-008。
- [x] T018 [测试/QA] 运行破坏测试，验证 SC-009。
- [x] T019 [QA] 检查 usable rate、重复版本、跨 split 泄漏、CRS、拓扑和异常清单。

## Phase 5 - 完成审计

- [x] T020 [研发] 运行 P05 测试及受影响模块最小回归。
- [x] T021 [QA] 检查所有变更源码/测试文件大小和 code-size audit。
- [x] T022 [架构] 核对项目/模块源事实、入口 registry 无变化、依赖无变化。
- [x] T023 [产品/测试/QA] 逐项核对 FR-001~FR-022、SC-001~SC-010，生成 validation summary。
- [x] T024 更新 tasks 勾选，按已修改/已验证/待确认交付。

## Post-acceptance decision

- [x] T025 将用户确认排除 `T10-Error / 1213556_1263661` 参数化写入 manifest，生成 `_06` 冻结 run，并验证全部训练 task mask、Oracle 与 anomaly 分层。
