# Tasks: P04 高精骨架优先 Road Direct V3

**Input**: `spec.md`、`research.md`、`data-model.md`、`plan.md`、`contracts/poc-output-contract.md`

## Phase 1: 基线与规格

- [x] T001 以 `p04_directional_v2_1885118_20260721T154712` 冻结 638 Road V2 基线并记录发布文件 hash。
- [x] T002 同步 `docs/PROJECT_REQUIREMENTS.md`、`current-module-inventory.md`、`module-lifecycle.md` 中过期的 642 组事实。
- [x] T003 建立 V3 SpecKit 的产品/架构/研发/测试/QA 五视角、数据模型、输出契约和跨文档分析。
- [x] T004 在所有源码/测试写入前记录当前字节数，新增文件按 0 bytes 处理并验证不会跨越 100 KB。

## Phase 2: 物理走廊条件拆分（US2）

- [x] T005 [US2] 先在 `tests/modules/p04_road_direct_generation/test_high_precision_corridor.py` 编写双侧可分拆分、单侧证据共享、锚点塌缩共享、单向保持和禁止纯反向重复测试，并确认实现前失败。
- [x] T006 [US2] 在 `high_precision_config.py` 定义隔离 V3 config/result 和 POC 参数审计。
- [x] T007 [US2] 在 `high_precision_corridor.py` 实现方向证据准备、provisional 中心、纵向持续性、宽度相对间距和 `PhysicalCorridorDecision`。
- [x] T008 [US2] 实现 `shared_physical / directional_carriageway / sd_fallback` RoadUnit；共享 Road使用完整相容 Lane 横向中心，不偏向单侧最左 Lane。
- [x] T009 [US2] 运行 corridor 单元测试并复核父语义守恒、拆分理由和重复对象门禁。

## Phase 3: 高精连续骨架（US1）

- [x] T010 [US1] 先在 `test_high_precision_geometry.py` 编写直接观测、双端补间、单端约束延伸、DriveZone 越界回退、开放边界回退、来源声明不膨胀、平滑和长度门禁测试，并确认实现前失败。
- [x] T011 [US1] 在 `high_precision_geometry.py` 实现固定站距 `CenterEvidenceObservation`，支持稳定 Lane、共享 Boundary 和稳健 Lane 中心。
- [x] T012 [US1] 实现内部双端高精补间和端部/长缺口约束延伸；DriveZone、LaneGroup、横向斜率、振荡、长度与开放边界均可审计。
- [x] T013 [US1] 生成覆盖全 Road的三类 `GeometrySourceSegment`，并计算四态、直接观测覆盖、高精控制覆盖和 SWSD fallback 比例。
- [x] T014 [US1] 运行几何单元测试并复核 valid/simple、包络、来源区间与长度守恒。

## Phase 4: RoadGraph 与 LaneTopo（US3）

- [x] T015 [US3] 先在 `test_high_precision_movement.py` 编写 shared/directional Road映射、confirmed/review 守恒、物理共点、复杂路口连接和 review 不协调测试。
- [x] T016 [US3] 在 `high_precision_movement.py` 实现 LaneTopo 到 V3 Road映射、端点协调和切向 Movement fallback。
- [x] T017 [US3] 在 `high_precision_topology.py` 实现 Portal/Arm、父语义 lineage、Road两 Arm和全物理节点审计。
- [x] T018 [US3] 运行拓扑/Movement 测试并验证无 silent fix。

## Phase 5: Pipeline、独立 QA 与输出（US1/US3/US5）

- [x] T019 [US5] 先在 `test_high_precision_pipeline_contract.py` 编写独立 callable、输出文件、M2/V2隔离、CRS、失败终态和冻结 hash 测试。
- [x] T020 [US1] 在 `high_precision_pipeline.py` 编排 M2 只读复用、V3 evidence/geometry/topology、当前 RCSD 对照、冻结 V2 逐 Road对照、manifest、summary、report 和 finalizer。
- [x] T021 [US5] 在模块 `__init__.py` 惰性导出 `HighPrecisionRoadV3Config/Result` 和 `run_high_precision_road_v3`；不新增 CLI/root script。
- [x] T022 [US3] 先在 `test_high_precision_quality.py` 编写发布后 GPKG 来源声明、覆盖率、重复方向对象、几何、物理节点和 Movement 失败测试。
- [x] T023 [US3] 在 `high_precision_quality.py` 实现只读发布包的独立 QA JSON/GPKG，并将其纳入 finalizer 硬门禁。
- [x] T024 [US5] 运行全部 P04 pytest，确认 M1/M2/V2 回归不变。

## Phase 6: QGIS 与真实数据端到端（US4）

- [x] T025 [US4] 在 `high_precision_qgis_project.py` 构建四网显式对比、四态 V3、三类来源、物理走廊、Lane/Boundary/DriveZone、LaneTopo和 QA 图层。
- [x] T026 [US4] 对 1885118 六 Patch执行 V3 core run，保留输入 hash、参数、CRS、阶段耗时和峰值内存。
- [x] T027 [US4] 启动独立 QA、QGIS 构建、PyQGIS 回读和 DriveZone overlay；任一失败继续迭代，不发布 `passed`。
- [x] T028 [US4] 量化验证 SC-004/SC-005；不得调整 `hp_observed` 定义或删除困难 Road满足指标。
- [x] T029 [US4] 人工分层审计主干路、辅路、路口、长缺口、条件拆分和 shared Road，比较 SWSD/RCSD/V2/V3 的平滑、连续和中心位置。

## Phase 7: 源事实与完成审计

- [x] T030 同步 P04 模块 SPEC、INTERFACE_CONTRACT、architecture 01-06、README 和项目级 P04 摘要；V2 保持冻结历史结果。
- [x] T031 新增 1885118 V3 结果文档，明确已验证事实、POC 参数、失败迭代和未确认边界。
- [x] T032 更新 `code-size-audit.md` 的 P04 V3 增量体量事实；入口 registry 保持不变并复核。
- [x] T033 对 FR-001..024、SC-001..012 逐项查验当前文件、测试、真实 run、QGIS和独立 QA证据。

## Dependencies & Gates

- Phase 2 依赖 Phase 1；Phase 3 依赖 RoadUnit；Phase 4 依赖最终几何；Phase 5/6 依赖前三阶段。
- 测试任务必须在对应实现前执行并确认目标行为失败。
- 任何对 directional V2 源码的修改都不在授权范围；若确需修改，必须停机并单独说明。
- SC-004/SC-005 是终态硬门禁，不以单元测试或局部样本替代真实六 Patch验证。
- restriction/Laneinfo、ReferenceLane 补充、RoadSplit 和生产正式化不阻断本轮，但不得被宣称完成。
