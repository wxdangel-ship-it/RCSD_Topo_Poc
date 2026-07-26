# Implementation Plan: P04 Segment-first Road 直出

**Branch**: `codex/p04-road-direct-poc-20260720` | **Date**: 2026-07-22 | **Spec**: `specs/p04-segment-first-road-direct-20260722/spec.md`
**Input**: 已确认 P04统一本体、阶段目标、方案 A治理授权及 feature specification。

## Summary

在既有 P04模块内新增隔离的 Segment-first 版本化 callable。新流程以 T01 Segment为主键，读取 T07/T03/T04/T08正式 surface和完整 RCSD锚定上下文，按 Segment聚合 Patch强证据，生成完整 Road carrier集合，再编译数据规格兼容 Node与RoadNextRoad。新建 Road只含 observed/constrained geometry source；旧 M1/M2/V2/V3和T01–T12不变。

端到端成果在当前完整测试范围运行，发布正式 P04候选 Road/Node/RoadNextRoad、独立 QA、QGIS对比和人工审计报告。

闭域验收使用独立外部清单叠加三层合同：输入先确定不可缩小的`BaselineCohort`；清单只给出`DirectBuildEligibility`例外并纳入输入hash；`PublishDisposition`继续保证全量Segment完整发布。代码不保存Case/Segment白名单，Summary、Report、独立QA和QGIS同时披露Baseline、DirectBuild和完整发布指标。

## Technical Context

**Language/Version**: Python 3.10.x
**Primary Dependencies**: GeoPandas、Shapely、PyProj、Fiona/pyogrio（沿用当前环境）、NumPy/Pandas；QGIS/PyQGIS仅用于工程构建与回读
**Storage**: GeoPackage、CSV、JSON、QGZ
**Testing**: pytest；发布后独立 QA；真实数据 replay；PyQGIS回读
**Target Platform**: Windows PowerShell本地研究环境；空间计算使用显式米制 CRS
**Project Type**: Python GIS library / module callable
**Performance Goals**: 记录完整范围各阶段耗时、吞吐和峰值内存；不劣化到不可重复运行，具体预算由基线 replay确定
**Constraints**: 不新增官方入口；不修改 T01–T12；单源码/脚本 <100KB；无 silent fix；旧版本冻结
**Scale/Scope**: 当前 P04完整真实测试范围及其所有 T01 Segment、相关 Junction、Patch Vector和RCSD上下文

## Constitution Check

### Phase 0 前 gate

| 原则 | 结论 | 证据/动作 |
|---|---|---|
| 分层源事实 | 通过（授权迁移中） | 新 SpecKit独立；随后同步 P04模块源事实与最小项目事实 |
| Brownfield先研究 | 通过 | `research.md`盘点旧V3、上游契约与迁移边界 |
| 非破坏迁移 | 通过 | M1/M2/V2/V3保留；新 callable/状态/输出隔离 |
| arc42模块文档 | 待本任务同步 | 更新 P04 01-06、SPEC、INTERFACE_CONTRACT |
| 中文文档 | 通过 | 文档中文，字段/代码标识英文 |
| 入口治理 | 通过 | 仅模块 callable，不改 CLI/scripts/registry |
| 文件体量 | 通过（持续 gate） | 每次源码写入前检查当前字节数；新文件控制职责与体量 |
| GIS质量 | 计划覆盖 | CRS、拓扑、几何语义、审计、性能均有独立任务 |

### Phase 1 后复核

- spec/data-model/contract已区分业务本体与发布 carrier。
- source-of-truth冲突已有用户方案 A授权。
- 仍不得在 `analyze.md` 就绪前写业务实现。
- RCSD未知枚举和ID数值规则必须通过正式规格/输入证据核对，不能由局部样本反推。

## Project Structure

### Documentation

```text
specs/p04-segment-first-road-direct-20260722/
├── spec.md
├── research.md
├── data-model.md
├── plan.md
├── tasks.md
├── analyze.md
├── quickstart.md
├── contracts/
│   └── poc-output-contract.md
└── validation/
    └── （一次性真实数据/对比分析脚本，按需新增）

modules/p04_road_direct_generation/
├── SPEC.md
├── INTERFACE_CONTRACT.md
└── architecture/01-06
```

### Source Code

```text
src/rcsd_topo_poc/modules/p04_road_direct_generation/
├── segment_first_types.py
├── segment_first_config.py
├── segment_first_inputs.py
├── segment_first_skeleton.py
├── segment_first_junctions.py
├── segment_first_evidence.py
├── segment_first_carriers.py
├── segment_first_geometry.py
├── segment_first_nodes.py
├── segment_first_topology.py
├── segment_first_outputs.py
├── segment_first_quality.py
├── segment_first_qgis.py
└── segment_first_pipeline.py

scripts/
└── p04_run_segment_first_innernet.py

tests/modules/p04_road_direct_generation/
├── test_segment_first_contract.py
├── test_segment_first_skeleton.py
├── test_segment_first_junctions.py
├── test_segment_first_carriers.py
├── test_segment_first_geometry.py
├── test_segment_first_topology.py
├── test_segment_first_quality.py
├── test_segment_first_pipeline.py
├── test_segment_first_legacy_regression.py
└── test_innernet_script.py
```

文件名可在实现中按现有模块结构合并最小重复，但不得把 input/evidence/geometry/topology/quality/QGIS堆入单一大文件。

**Structure Decision**: 在现有P04包内保持`segment_first_*`隔离族并通过`__init__.py`导出callable；唯一正式内网入口`scripts/p04_run_segment_first_innernet.py`只做显式参数解析、前检和callable转调，不新增CLI子命令、模块`__main__.py/run.py`或第二套业务实现。

## Data Flow

```text
Input preflight
  ├─ T01 segment/nodes/roads
  ├─ T07/T03/T04/T08 results
  ├─ full RCSD Road/Node/RoadNextRoad
  └─ Patch Road/Lane/LaneTopo/Boundary/RoadSurface
          ↓
SegmentBuildUnit + JunctionUnitCandidate
          ↓
Patch evidence assignment by Segment
          ↓
RoadCarrierPlan
  ├─ built Road: observed + constrained completion
  └─ retained Road: complete existing carrier
          ↓
SegmentAccess + Junction carrier realization
  ├─ high-precision portal Nodes
  ├─ ordinary distributed portal/mainnode semantics
  └─ complex/roundabout explicit internal carriers
          ↓
NodeBuildCandidate + stable ID/mainnode
          ↓
RoadNextRoad from actual shared Node, ordinary Junction semantics,
or explicit LaneTopo retained/ADVANCE_RIGHT evidence
          ↓
SWSD Access direction + Junction Movement completeness contract
          ↓
LaneTopo projection / physical movement audit
          ↓
Road / Node / RoadNextRoad publication
          ↓
independent QA + QGIS + human audit
```

## Delivery Phases

### Phase 0：输入和旧版本事实冻结

1. 定位当前真实测试范围的 T01/T07/T03/T04/T08/RCSD/Patch输入。
2. 读取 schema、CRS、数量、hash，确认完整 RCSD与Patch版本关系。
3. 核对 RCSD Road/Node/RoadNextRoad数据规格、ID和source字段。
4. 运行旧 P04核心测试并记录冻结结果；不重跑或覆盖历史输出。

输出：preflight研究证据、输入 contract测试、旧版本保护基线。

### Phase 1：Source-of-truth同步

1. 将 P04主对象从 SWSD Road owner改为 T01 Segment owner。
2. 把 T07/T03/T04/T08、完整 RCSD和Patch强证据写入模块输入角色。
3. 固化 Segment四态、Road source规则、正式三图层、Junction优先级和hard/soft gate。
4. 最小同步项目级 P04定位，仍为 Active POC且不改主链。

输出：模块级 source-of-truth与治理索引一致。

### Phase 2：Segment/Junction基础域

1. 建立配置、类型和输入适配器。
2. 从 T01构造 SegmentBuildUnit，保留 pair/junc/roads/sgrade。
3. 从正式上游成果构造 JunctionUnitCandidate并执行优先级。
4. 生成 SegmentAccess，保留 ENDPOINT/THROUGH关系。

输出：不含最终几何的完整业务 skeleton和审计层。

### Phase 3：证据聚合和 carrier计划

1. 按 Segment聚合跨 Patch Road/Lane/LaneTopo/Boundary/Surface。
2. 复用既有输入质检但不继承旧 Road owner。
3. 识别方向/主辅/局部完整 carrier角色。
4. 形成 hp_full/hp_partial/retained/conflict计划；检测方向重复。

输出：每 Segment唯一 RoadCarrierPlan。

### Phase 4：Vector-native Road几何

1. 从 Lane/Boundary/Patch Road/RoadSurface派生方向中心走廊。
2. 生成 observed控制段。
3. 在合法道路域内完成 constrained completion。
4. 禁止 raw SWSD顶点拼接；SWSD仅作语义/access弱约束。
5. 完整保留无法重建的 Road carrier。

输出：完整 RoadBuildCandidate和EvidenceSpan。

### Phase 5：Node、mainnode和RoadNextRoad

1. 继承或稳定生成 Road/Node ID。
2. 普通Junction保留分布式高精portal并统一mainnode，不实例化中心Node或星形JunctionUnit内部Road；T04复杂、环岛和辅助Junction按各自正式物理结构处理。
3. 同 JunctionUnit mainnode一致。
4. Segment内部和复杂路口由实际共享Node/显式物理关系编译RoadNextRoad；ordinary由同一正确分类JunctionUnit内方向兼容的进入—离开Road组合编译语义RoadNextRoad；retained和正式ADVANCE_RIGHT只在原始LaneTopo证据命中时补充显式语义关系。
5. 投影 LaneTopo并分类 mapped/review/excluded/blocked；跨Segment被拒Movement显式排除，同Segment内部拒绝只阻断owner Segment。

输出：正式三图层候选和关系审计。

### Phase 6：发布后 QA与QGIS

1. 写出正式 GPKG、审计 GPKG、summary/report。
2. 独立进程只读发布结果复算全部hard gate。
3. 构建相对路径QGIS工程并独立回读。
4. 生成 SWSD/完整RCSD/Patch/旧P04/新结果分层对比。

输出：可验收运行包。

### Phase 7：完整真实数据和人工审计

1. 全量运行当前测试范围。
2. 按普通路口、T04复杂、环岛、主辅路、部分/无证据、冲突、跨Patch、已有调头口分层审计。
3. 修复算法缺陷，不把输入质量问题调参消失。
4. 复跑确定性、旧版本保护、性能和代码体量审计。

输出：端到端结果、QGIS、人工结论和完成审计。

## Technical Design

### 1. 输入适配

- 所有输入路径显式参数化到 config；不硬编码当前Case路径。
- schema preflight对 required/optional字段分层，未知枚举保持 observed-only。
- 所有空间层统一到配置的 meter CRS；正式发布按RCSD规格输出CRS。
- T07/T03/T04只消费 accepted主层，不从PNG或relation成功反推surface。

### 2. Segment工作图

- `segment_id`是所有 evidence/carrier/decision的一级索引。
- SWSD Road按 T01 `roads`加入 lineage；跨Patch membership只决定证据范围。
- `junc_nodes`形成 THROUGH access和辅助 Junction上下文，不能 optional prune。

### 3. carrier规划

- 先确定必要 carrier角色，再决定 built/retained，避免先造Road后补结构。
- hp_partial允许完整Road级混合，不允许单Road raw SWSD splice。
- 原一条双向 Road时特别检查单向built+双向retained重叠。

### 4. 几何

- 中心走廊证据优先级由方向、覆盖、稳定性和道路域共同决定，不固定某条最左Lane。
- observed保存直接控制点/区间；constrained保存边界条件和支撑证据。
- constrained completion不得跨hard barrier/foreign surface；失败回到完整carrier保留。
- 平滑参数从真实数据复算后进入配置和manifest，不写死为生产真值。

### 5. Node和拓扑

- 每条Segment Road必须实现正确Junction组/mainnode和自身Access交接；内部曲线最优仍作为QA。
- ordinary全连接通过分布式高精portal Node、统一mainnode和ordinary语义RoadNextRoad实体化，不生成中心点或星形内部Road；complex通过明确内部Road/Node。
- Segment内部和complex RoadNextRoad从方向正确的实际Road端点共享关系或显式物理关系生成；ordinary语义关系必须保留source/target物理Node和Junction lineage。
- 原始SWSD只提供完整Access方向和Junction Movement验收合同，不提供built Road坐标；Road按LaneGroup细分后在归一化方向链上复核合同。
- T04 complex缺少Patch内部carrier时，只允许shared Node、member lineage和accepted surface三证俱全的SWSD显式fallback。

### 6. ID与确定性

- 输入ID canonical化；正式ID生成采用排序后的业务seed和数据规格算法。
- Patch顺序、并行顺序不得进入seed。
- 生成记录保留 `id_seed` 与source lineage以便复算。

### 7. QA

- core gate在内存对象上早失败；independent QA只读发布文件。
- soft review不会改变hard gate值。
- `terminal_status=passed`由finalizer汇总core/independent/QGIS/full-run证据。

## Test Strategy

### Unit

- Segment状态机与carrier组合真值表；
- T07/T03/T04优先级；
- pair/junc/access解析；
- observed/constrained覆盖；
- 双向/单向重叠；
- ID稳定；
- actual shared Node、ordinary语义、显式LaneTopo retained和显式LaneTopo ADVANCE_RIGHT四类RoadNextRoad编译；
- 无证据反向/U-turn排除与非Junction主干实际共享Node交接；
- SWSD Access方向合同、ordinary完整Movement合同和T04显式fallback三证门禁；
- hard/soft gate分层。

### Contract

- T01 segment字段；
- T07/T03/T04 accepted主层；
- RCSD三图层schema；
- 正式输出三图层和最小字段。

### Integration

- 小型合成ordinary/complex/roundabout/auxiliary场景；
- hp_full/hp_partial/retained/conflict四态；
- 跨Patch同Segment；
- Patch已有调头短连接；
- 旧callable不变。

### Real-data QA

- 完整当前测试范围；
- 发布后独立复算；
- QGIS回读；
- 分层人工审计；
- 两次重复运行和Patch顺序扰动；
- 性能/体量审计。

## Complexity Tracking

| 复杂度 | 为什么需要 | 更简单方案为何不足 |
|---|---|---|
| 新建独立 Segment-first 文件族 | 旧V3的owner、状态和几何合同不兼容 | 原地修改会破坏冻结V2/V3和历史实证 |
| 正式三图层 + 审计层 | 数据规格发布与业务解释职责不同 | 把所有字段塞进Road会污染正式schema且无法表达多对多 |
| core + independent QA双层 | GIS写出、字段截断、CRS和拓扑可能在发布阶段变化 | 生成器内存自检不能证明发布文件正确 |
| Junction多来源适配 | 已确认必须复用T07/T03/T04/T08和RCSD fallback | 单一surface算法会重做上游并丢失人工审核优先级 |

## Risk Controls

- 当前工作区已有未提交/未跟踪 P04历史成果：只增量修改明确文件，不清理、不重置。
- 项目级 source-of-truth只做P04最小同步，不扩展T01–T12语义。
- 数据规格字段不明确时停止对应写入，先核对正式规格；不得样本反推。
- 任一源码写入前检查字节数；跨100KB立即按AGENTS停机。
- 实数结果未通过人工审计前只称技术候选，不称业务验收完成。
