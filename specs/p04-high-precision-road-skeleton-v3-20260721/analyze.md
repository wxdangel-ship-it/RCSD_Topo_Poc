# Cross-document Analyze: P04 高精骨架优先 Road Direct V3

## 1. Source-of-truth 一致性

| 检查 | 结论 |
|---|---|
| V2 唯一基线 | 已由用户授权为 `T154712 / 638 Road`，项目级过期 642 组事实已同步。 |
| 与既有 P04 V2 规格关系 | 新 SpecKit 明确冻结 V2并新增 V3，不改写 V2历史需求和验证记录。 |
| 与正式主链关系 | P04 继续为并行 Active POC，不改变 relation-first 主链。 |
| 入口治理 | 仅新增模块内研究 callable，无 repo CLI、root script 或 registry 变化。 |
| 字段治理 | 未确认枚举、RoadSplit、restriction/Laneinfo 和 ReferenceLane 补充均排除。 |
| GIS 五项质量 | CRS、拓扑、几何语义、审计可追溯、性能均有任务和门禁。 |
| 五类职责视角 | 产品、架构、研发、测试、QA均在 spec 中明确。 |

## 2. 需求—任务覆盖

- 高精骨架和三类来源：FR-008..014、FR-023..024 -> T010..014、T020、T022..023、T028。
- 条件式物理走廊拆分：FR-005..007 -> T005..009、T022..023。
- 完整语义和 LaneTopo：FR-003..004、FR-015..016 -> T015..018、T022..023。
- CRS/审计/独立 QA：FR-017..018 -> T019..024、T026..028。
- QGIS 四网对照：FR-019 -> T025、T027、T029。
- 隔离实现和范围排除：FR-002、FR-020..022 -> T001、T019..021、T024、T032。
- 源事实与最终交付：SC-001..012 -> T026..033。

## 3. 指标语义检查

- `hp_observed` 只表示直接源观测；不能通过插值满足覆盖目标。
- `hp_constrained_interpolation` 包含双端补间和通过道路面/拓扑门禁的单端延伸。
- SC-004 使用两者之和衡量“高精骨架受控”，SC-005 独立约束真实 SWSD fallback。
- 真实数据若无法满足门禁，任务保持失败并输出原因，不重新定义成功。

## 4. 结构和体量检查

计划新增 8 个职责单一源码文件和 5 个测试文件，现有 P04 最大文件为 `directional_evidence.py` 42,766 bytes。V3 不向 directional 文件回填实现；所有写入前仍需执行实时体量检查。

## 5. 就绪结论

产品、架构、研发、测试和 QA 视角齐全；用户已解决唯一源事实冲突；未发现入口、字段或跨模块未授权变更。任务可进入 test-first implement。

## 6. 终态 FR 覆盖复核

| FR | 终态证据 | 结论 |
|---|---|---|
| FR-001..004 | 项目/模块 lifecycle、冻结 V2 hash、571 父语义守恒、SWSD/Vector 职责字段 | 通过 |
| FR-005..007 | `physical_corridor_decisions`：32 split / 265 shared / 274 fallback；split 独立门禁违规 0 | 通过 |
| FR-008..014 | 稳定中心、固定 5 m 站距、三类来源、约束失败局部 fallback、603/603 valid/simple、来源/支撑违规 0 | 通过 |
| FR-015..016 | 767 = 733 confirmed + 34 review；284 Movement；1206 Portal/Arm；394 多端物理节点违规 0 | 通过 |
| FR-017..018 | EPSG:32650、431 输入文件 hash、参数/运行环境/阶段耗时、独立 QA、QGIS/readback/overlay finalizer | 通过 |
| FR-019 | 26 图层四网工程，四 comparison role、四态和三类来源齐全 | 通过 |
| FR-020..022 | 仅模块 callable；CLI/scripts/entrypoint registry 无 P04；排除字段未消费；RCSD 只作对照 | 通过 |
| FR-023..024 | 独立覆盖率、回退原因、直接观测不虚增，以及 603/603 V3→冻结 V2 逐 Road差异工件 | 通过 |

## 7. 终态 SC 实测

| SC | 权威 run 实测 | 结论 |
|---|---|---|
| SC-001 | 571 个 distinct parent，未发布父 Road 0 | 通过 |
| SC-002 | 603 = 571 + 32 | 通过 |
| SC-003 | 32 split；独立物理间距违规 0；反向克隆 0 | 通过 |
| SC-004 | 独立有证据 Road 高精控制率 88.550% >= 80% | 通过 |
| SC-005 | 独立全网 `swsd_fallback` 39.817% < 40% | 通过 |
| SC-006 | 未受源观测支撑的 `hp_observed` 片段 0 | 通过 |
| SC-007 | 603/603 valid/simple；来源覆盖/声明/约束支撑违规 0 | 通过 |
| SC-008 | 1206/1206 Portal/Arm；394 多端物理节点、284 Movement 门户/接头违规 0 | 通过 |
| SC-009 | 733 + 34 = 767；29 direction review + 5 semantic-unconnected review | 通过 |
| SC-010 | 冻结 V2 四文件 hash 与授权值一致；V3 独立 run root | 通过 |
| SC-011 | 26/26 QGIS 图层有效，EPSG:32650、相对路径、四网 role 和基础资料/QA 分组齐全 | 通过 |
| SC-012 | core、独立 QA、QGIS、独立回读、98.364583% overlay、性能 replay、人工分层审计均可定位 | 通过 |

SC-007 的“LaneGroup/DriveZone 硬包络”按证据可用性解释：直接观测可由 Lane/LaneGroup 支撑，约束补间必须有观测锚点和约束记录，失败区间回退；DriveZone 原始覆盖不完备，因此独立 overlay 是 98.364583% 的单独 QA 门禁，不把道路面外但有 Lane 直接观测的片段静默删除或伪装成 `sd_only`。

## 8. 性能与治理终态

- 权威 run 核心耗时 116.065 s；独立性能 replay 核心耗时 110.969 s，lifetime peak working set 219.414 MiB，采样 peak private 904.094 MiB，核心几何/拓扑计数与权威 run 一致。
- P04 `src/`、`tests/` 与 V3 validation 共 56 个 `.py`，`>=61440` 和 `>=100000` bytes 均为 0；最大文件 42,766 bytes。
- P04 未进入 `src/rcsd_topo_poc/cli.py`、`scripts/` 或 `entrypoint-registry.md`；冻结 V2、M2 和 T00-T12 V1 未修改。
