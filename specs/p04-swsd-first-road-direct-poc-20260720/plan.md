# Implementation Plan: P04 SWSD-first Road 直出 POC

**Branch**: `codex/p04-road-direct-poc-20260720` | **Date**: 2026-07-20 | **Spec**: `spec.md`

## Summary

`p04_road_direct_generation` 已完成 Phase 0、第一、第二里程碑和 Directional Road V2。隔离 V2 已通过方向拆分、单一稳定中心 Lane/共享 Boundary、统一站距与横向斜率平滑、无证据 gap/端点保留 SWSD、全物理节点端点共点和切向 DirectionalMovement，并在 1885118 六 Patch 通过独立发布后 QA 与 QGIS A/B 终验。M2、T00-T12 V1、repo CLI 与 root script保持不变。

## Technical Context

**Language/Version**: Python 3.10.12
**Primary Dependencies**: 仓库现有 GIS 依赖，预期复用 GeoPandas/Fiona/Shapely 与共享字段解析能力，不新增依赖
**Storage**: GeoJSON/GPKG/CSV/JSON 文件证据包
**Testing**: pytest、结构化审计、GIS/QGIS 叠加检查
**Target Platform**: 本地 Windows/WSL 与后续内网 Linux，路径必须参数化
**Project Type**: 现有 Python 单仓库中的 Active POC 模块
**Performance Goals**: 6 Patch 端到端运行记录逐阶段耗时和峰值内存；V2 报告相对 M2 的方向数量、平滑度、长度膨胀和空间覆盖变化
**Constraints**: no silent fix、显式 CRS、100 KB 源码硬阈值、未确认字段不进强规则、不新增正式入口、输入 QA 与 Road conflict 解耦、既有 T00-T12 V1 只读复用且不改变；不兼容能力新建显式 V2/适配层
**Scale/Scope**: 当前 6 Patch、426 文件、约 146.5 MB；后续面向多 Patch 批量

## Constitution Check

- [x] 分层源事实：SpecKit 变更工件与模块 source-of-truth 分开。
- [x] 新模块采用标准 README/SPEC/INTERFACE_CONTRACT/architecture 01-06。
- [x] 先研究现状：1885118 数据结构、CRS、引用与派生关系已实测。
- [x] 不基于局部样本固化枚举强规则。
- [x] 文档使用中文。
- [x] 不新增 repo CLI 或 root script；本轮只新增契约已授权的 P04 Directional Road V2 研究 callable。
- [x] 不修改现有 T01-T12/P01/P02 接口。
- [x] 复用按直接调用、契约消费、只读对照、V2 隔离四类治理；本轮 Directional Road V2 已由用户授权并要求独立测试。
- [x] GIS 质量覆盖 CRS、拓扑、几何语义、审计和性能计划。

## Project Structure

### Documentation

```text
specs/p04-swsd-first-road-direct-poc-20260720/
├── spec.md
├── research.md
├── data-model.md
├── plan.md
├── tasks.md
├── analyze.md
└── contracts/
    └── poc-output-contract.md

modules/p04_road_direct_generation/
├── README.md
├── SPEC.md
├── INTERFACE_CONTRACT.md
├── architecture/
│   ├── 01-introduction-and-goals.md
│   ├── 02-data-and-domain-model.md
│   ├── 03-solution-strategy.md
│   ├── 04-evidence-and-audit.md
│   ├── 05-quality-requirements.md
│   ├── 06-risks-and-technical-debt.md
│   ├── 1885118-patch-vector-baseline.md
│   ├── 1885118-milestone1-results.md
│   ├── 1885118-milestone2-results.md
│   └── 1885118-directional-road-v2-results.md
└── history/
    └── README.md
```

### Current Source Code

```text
src/rcsd_topo_poc/modules/p04_road_direct_generation/
├── __init__.py
├── assignment.py
├── business_analysis.py
├── comparison.py
├── config.py
├── geometry.py
├── io.py
├── pipeline.py
├── qgis_project.py
├── report.py
├── skeleton.py
├── road_config.py
├── road_evidence.py
├── road_geometry.py
├── road_pipeline.py
├── road_qgis_project.py
├── road_report.py
├── directional_config.py
├── directional_evidence.py
├── directional_geometry.py
├── directional_movement.py
├── directional_pipeline.py
├── directional_qgis_project.py
├── directional_quality.py
└── directional_topology.py

tests/modules/p04_road_direct_generation/
├── test_*milestone_one*.py
├── test_road_evidence.py
├── test_road_geometry.py
├── test_road_pipeline_contract.py
├── test_directional_evidence.py
├── test_directional_geometry.py
├── test_directional_movement.py
├── test_directional_quality.py
├── test_directional_comparison.py
├── test_directional_pipeline_contract.py
└── test_directional_topology.py
```

**Structure Decision**: 第一、第二里程碑和 Directional Road V2 均按 evidence/geometry/topology/pipeline/QGIS 职责拆分且小于 100 KB，不登记正式入口。V2 只复用 M2 输出和内部 API，不向 M2 或 T00-T12 V1 增加兼容分支。

## Delivery Phases

1. **Phase 0 - Research and Governance（已完成）**：注册 P04、固化数据理解、输入价值和开放问题。
2. **Milestone 1 - Skeleton and Lane Evidence（已完成）**：生成 SWSD 骨架、Lane owner、Boundary 宽度、道路面、LaneTopo 准备度、旧 Road 差异和 QGIS 工程。
3. **Milestone 2A - Data-first Road Support Analysis（已完成）**：基于真实 M1 逐 Lane 决策分析 owner 可用证据、归一化里程、覆盖间隙和端部缺口分布，形成候选参数而不把单 Case 阈值升级为生产事实。
4. **Milestone 2B - Road Four-state Instantiation（已完成）**：生成 RoadSupportInterval、独立 EvidenceQualityFlag、四态 RoadCandidate 和混合几何，完整发布 571 条 Road。
5. **Milestone 2C - End-to-end QA（已完成）**：自动化测试、真实六 Patch 运行、CRS/拓扑/几何/审计/性能门禁、QGIS 差异工程和旧 Road 只读对照；权威 run 为 `p04_m2_1885118_20260721T030000`。
6. **Directional Road V2（已完成）**：复用 M2 输出但不改变其语义，完成方向拆分、稳定中心锚点、证据范围拟合、无证据保留、方向级 Portal/Arm、LaneTopo DirectionalMovement 和输入 RCSD 多段走廊对照。
7. **Independent Geometry/Topology Acceptance（已完成）**：独立进程只读取发布 GPKG，复核全部多端物理节点、支持 Road 对齐转角、Movement 门户/接头和双向高精间距；新增双向锚点塌缩降级与长 SD gap 高精声明分层后，权威 run `p04_directional_v2_1885118_20260721T154712` 通过 core、独立 QA、QGIS 双重回读、DriveZone overlay 和第三轮分层人工审计。
8. **Later Milestones**：接入 SWSD restriction/Laneinfo、ReferenceLane 补充和 RoadSplit 正式语义，形成完整 movement 合法性，并基于多 Case 决定是否正式化。

## Complexity Tracking

当前无宪章例外。P04 与正式主链并行是用户明确要求的 POC 边界；通过生命周期、无入口和不修改现有接口控制复杂度。
