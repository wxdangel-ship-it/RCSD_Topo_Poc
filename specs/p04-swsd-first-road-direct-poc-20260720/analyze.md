# P04 Cross-document Analyze

## 1. Source-of-truth 一致性

| 检查 | 结论 |
|---|---|
| 与项目正式主链是否冲突 | 不冲突。P04 登记为并行 Active POC，不改变 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。 |
| 是否修改现有模块接口 | 否。P04 已有第一、第二里程碑及 Directional Road V2 研究 callable，但没有 CLI、root script 或正式入口；M2/T00-T12 V1 只读不变，不兼容语义由隔离 V2 承载。 |
| 是否基于样本固化未确认字段 | 否。枚举和 RoadSplit 仍为开放问题；`*_fix` 来源、FlowNum 弱证据边界、Boundary 几何宽度和 `sd_only` 完整发布来自用户确认与 T00 当前契约。 |
| 是否覆盖 GIS 五项质量 | 是。CRS、拓扑、几何语义、审计、性能均进入 spec/plan/tasks。 |
| 产品/架构/研发/测试/QA 是否齐全 | 是，见 `spec.md` Responsibility Views。 |

## 2. 需求到任务覆盖

- 表与字段理解：FR-002/FR-005/FR-007 -> T003、T007-T009。
- SWSD-first 骨架：FR-003/FR-004 -> T010-T013。
- evidence fitting：FR-005/FR-006 -> T014-T018。
- LaneTopo 一致性：FR-008-FR-011 -> T019-T023。
- QA/审计/性能：FR-012-FR-014 -> T024-T027。
- 入口边界：FR-015 -> 当前无入口，后续需单独授权。
- 既有模块保护与 V2：FR-017/SC-008 -> T028。
- Road 四态、区间和几何：FR-011/FR-019 -> T029、T031-T035、T037-T039。
- 输入质检解耦：FR-018/SC-009 -> T030、T036-T039。
- 第二里程碑排除项：FR-020 -> T017/T022 后移，不阻断 T031-T040。
- Directional Road V2：FR-021-FR-028/SC-012-SC-016 -> T041-T050；连续性修订 FR-029-FR-032/SC-017-SC-020 -> T051-T056；独立几何/拓扑验收 FR-033-FR-036/SC-021-SC-024 -> T057-T062，均已完成。

## 3. 当前可实施与受阻边界

当前已完成：模块登记、文档面、数据基线、SWSD 骨架、Lane evidence assignment、Boundary 宽度、道路面覆盖、旧 Road 差异、LaneTopo 准备度，第二里程碑的 Lane 局部分段、Road 区间、四态混合几何、完整 RoadGraph，以及 Directional Road V2 的方向拆分、稳定中心锚点、统一站距平滑、无证据 gap/端点保留、全物理节点协调、切向 LaneTopo movement、输入 RCSD 多段走廊对照、独立发布后 QA 和 QGIS/overlay 自动门禁。

当前可固化：T00 `*_fix` 与对应 raw 层业务语义等价，分别表示道路面和路面导流带，默认消费修正版、保留 raw lineage 且不重复计权；FlowNum 作为轨迹聚合弱证据；LaneBoundary 垂直投影宽度；Road 层 `hp_supported/partial_hp_supported/sd_only/conflict_retained` 四态；输入质量异常与 Road 冲突解耦。

当前不可固化：依赖未知枚举的 Lane/Boundary 强过滤、RoadSplit 强分割、FlowNum 到精确流量的换算、restriction/Laneinfo movement 合法性，以及未经多 Case 验证的 Road 覆盖/间隙/拟合阈值。

## 4. 结论

第二里程碑已由 1885118 权威 run `p04_m2_1885118_20260721T030000` 验证通过；Directional Road V2 当前权威 run 为 `p04_directional_v2_1885118_20260721T154712`。10,919 个无证据站点和 1,185 个无证据端点均为 0 横移；50 个双向证据父 Road中 4 个塌缩候选已回退为 SWSD 父表达，42 条部分高精 Road进入长 SD gap 复核。767 条跨 owner LaneTopo 守恒为 724 confirmed + 43 review，并聚合为 278 个 DirectionalMovement。独立发布后 QA 复核 393 个多端物理节点、339 条支持 Road、278 个 Movement 和 50 对双向证据，违规均为 0；QGIS/独立回读/overlay 与第三轮人工审计全部通过。旧 `T121556/T145722` 均降级为历史基线。RoadSplit、restriction/Laneinfo、ReferenceLane 补充、完整 movement 合法性、枚举型强过滤和生产正式化明确留待后续。
