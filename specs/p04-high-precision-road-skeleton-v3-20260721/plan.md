# Implementation Plan: P04 高精骨架优先 Road Direct V3

**Branch**: `codex/p04-road-direct-poc-20260720` | **Date**: 2026-07-21 | **Spec**: `spec.md`

## Summary

在不修改冻结 V2、M2 和 T00-T12 V1 的前提下，新建 P04 V3 研究 callable。V3 先基于方向 Lane 证据决定是否存在两个物理方向走廊；未通过时使用共享物理 Road。随后在 SWSD 固定纵向站距上建立 Lane/Boundary 直接中心观测，用高精锚点、DriveZone、平滑和拓扑约束扩展为连续高精骨架，并按 `hp_observed / hp_constrained_interpolation / swsd_fallback` 发布来源分段。

## Technical Context

**Language/Version**: Python 3.10.x（repo `.venv`）
**Primary Dependencies**: 现有 GeoPandas/Fiona/Shapely/NumPy/Pandas/QGIS；不新增依赖
**Storage**: GPKG/CSV/JSON/QGZ
**Testing**: pytest、真实 1885118 端到端、独立 GPKG QA、PyQGIS 回读、DriveZone overlay、人工分层审计
**Target Platform**: 当前 Windows PowerShell；后续内网路径通过 config 传入
**Project Type**: Python 单仓库 Active POC 模块
**Performance Goals**: 六 Patch 端到端耗时和峰值内存可定位；不劣于 V2 同量级的可接受运行
**Constraints**: 100 KB 硬阈值、写前体量检查、no silent fix、显式 CRS、未知枚举不进强规则、无正式入口变更
**Scale/Scope**: 1885118 六 Patch，571 个父 SWSD Road；后续需多 Case 冻结阈值

## Constitution Check

- [x] 变更工件独立位于新 `specs/` 目录，V2 SpecKit 保留历史。
- [x] 用户已明确授权修订“自动方向拆分”业务口径和同步源事实。
- [x] 已完成 V2 实际发布包和源事实冲突审计。
- [x] 产品、架构、研发、测试、QA 五视角完整。
- [x] 不修改 T00-T12 V1、M2、冻结 V2、repo CLI 或 root script。
- [x] 未确认枚举、RoadSplit、restriction/Laneinfo 不进入强规则。
- [x] CRS、拓扑、几何语义、审计、性能均有门禁。
- [x] 新增源码按职责拆分，预计均远低于 100 KB。

## Technical Design

### Phase 1：物理走廊实例化

1. 读取 M2 的 LaneEvidenceSegment、M1 Lane 决策/Boundary/DriveZone 和 SWSD skeleton。
2. 沿父 SWSD 将 Lane 分为 forward/reverse 证据，但方向分组只用于物理走廊审计。
3. 为每侧形成 provisional 稳定中心和纵向覆盖。
4. 只有双侧 usable、间距和持续性均通过时生成两个 `directional_carriageway`；其余生成 `shared_physical` 或 `sd_fallback`。
5. 对 shared Road使用全部相容 Lane 的稳健横向中心，避免偏向最左 Lane或单侧方向组。

### Phase 2：高精骨架拟合

1. 用统一 5 m POC 站距建立父 SWSD 局部坐标。
2. 在站点附近对稳定 Lane/共享 Boundary/多 Lane 中心生成直接观测。
3. 稳健平滑直接观测；不改变 `hp_observed` 范围。
4. 对内部缺口做双端约束补间；对端部/长缺口做单端趋势加 DriveZone/拓扑约束延伸。
5. 任何包络、开放边界、斜率、振荡、长度或拓扑门禁失败的区间回退 SWSD。
6. 生成完整 Road和来源分段，计算四态与覆盖率。

### Phase 3：拓扑与 Movement

1. 为 V3 Road构建 Portal/Arm。
2. 将 LaneTopo 映射到 shared/directional V3 Road。
3. confirmed 同物理 Node 端点共点；复杂语义路口输出切向 Movement；review 不参与协调。
4. 对所有共享物理 Node 做全量闭合审计。

### Phase 4：独立 QA 与 QGIS

1. 发布后独立读取 GPKG，复算来源声明、覆盖率、重复方向对象、几何、节点和 Movement。
2. 构建 SWSD/RCSD/V2/V3 四网对比 QGIS。
3. 执行 PyQGIS 回读、DriveZone overlay、性能和人工审计。

## Project Structure

```text
src/rcsd_topo_poc/modules/p04_road_direct_generation/
├── high_precision_config.py
├── high_precision_corridor.py
├── high_precision_geometry.py
├── high_precision_comparison.py
├── high_precision_movement.py
├── high_precision_topology.py
├── high_precision_quality.py
├── high_precision_qgis_project.py
└── high_precision_pipeline.py

tests/modules/p04_road_direct_generation/
├── test_high_precision_corridor.py
├── test_high_precision_geometry.py
├── test_high_precision_comparison.py
├── test_high_precision_movement.py
├── test_high_precision_quality.py
└── test_high_precision_pipeline_contract.py
```

`__init__.py` 只增加模块内惰性 callable 导出。现有 directional 文件不修改，避免 V2 漂移。

## Data Flow

```text
SWSD semantic skeleton + M2 LaneEvidenceSegment + Lane/Boundary/DriveZone
            ↓
PhysicalCorridorDecision
            ↓
HighPrecisionRoadUnit + CenterEvidenceObservation
            ↓
HighPrecisionControlSpan
            ↓
GeometrySourceSegment + HighPrecisionRoadCandidate
            ↓
Portal/Arm + LaneTopo Movement
            ↓
V3 RoadGraph + independent QA + QGIS
```

冻结 V2 逐 Road 形态对照由 `high_precision_comparison.py` 在发布阶段单独生成；它不参与几何选择或通过判定，只满足差异可解释与可追溯要求。

## Complexity Tracking

无宪章例外。V3 采用独立文件而不是向 `directional_*.py` 添加条件分支，以保持 V2 冻结和文件体量安全。
