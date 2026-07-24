# P04 Segment-first POC Output Contract

## 1. 稳定边界

- 本合同仅约束 P04 Segment-first 版本化 POC候选输出。
- 它不修改 RCSD生产数据规格、T01–T12接口、现有 P04 M1/M2/V2/V3输出。
- `Road / Node / RoadNextRoad` 是正式 P04 RCSD候选图层；其它均为内部或审计输出。
- 生成器自检最多把运行标记为`technical_passed`；必须再通过QGIS道路面覆盖、真实PyQGIS回读、确定性和人工审计，并由finalizer晋级`passed`。

## 2. 输出包

建议运行根：

```text
p04_segment_first_<case>_<timestamp>/
├── p04_segment_first_rcsd.gpkg
│   ├── Road
│   ├── Node
│   └── RoadNextRoad
├── p04_segment_first_audit.gpkg
├── p04_segment_first_relations.gpkg
├── p04_segment_first_summary.json
├── p04_segment_first_report.md
├── p04_segment_first_independent_quality.json
├── p04_segment_first_independent_quality.gpkg
├── p04_segment_first_comparison.qgz
└── _inputs/ 或 manifest引用
```

实际文件名可在实现前微调，但正式三图层名称和分层语义不得改变。

## 3. 正式 `Road` 图层

### 3.1 数据规格字段

正式字段必须从当前 RCSD Road数据规格或权威输入 schema复制，不在本 SpecKit中猜测未知枚举。至少需要：

- Road唯一 ID；
- `snodeid/enodeid` 或正式别名；
- 方向字段；
- `source`；
- LineString geometry；
- 数据规格要求的其它必填字段。

### 3.2 P04可追溯字段

如数据规格允许，可附加：

- `segment_id`；
- `owner_type`；
- `junction_group_id`；
- `carrier_role`；
- `realization`；
- `source_patch_ids`（若字段长度不适合，则只放关系表）；
- `review_required`。

详细 Lane/evidence列表默认进入关系表，不塞入 Road属性。

`owner_type=SEGMENT`必须有`segment_id`；`owner_type=JUNCTION_UNIT`必须有`junction_group_id`且`segment_id`为空。若正式RCSD schema不允许这些扩展字段，必须从关系层无损恢复。

### 3.3 几何契约

- `built` Road只含 `hp_observed / hp_constrained_completion`。
- `retained` Road整条保留，不声明高精。
- 禁止一条 Road混合新高精坐标与原 SWSD坐标。
- 每条 Road非空、有效、方向明确，并拥有存在于 Node图层的起终点。

## 4. 正式 `Node` 图层

正式字段必须沿用 RCSD Node数据规格，至少需要：

- Node唯一 ID；
- `mainnodeid`；
- Point geometry；
- 数据规格要求的其它必填字段。

规则：

- 同一 JunctionUnit内所有 Node共享 `mainnodeid`；
- 不把不同物理 Node强制合为同一 `nodeid`；
- 能继承权威 RCSD/Patch身份则继承，否则按 RCSD ID规范稳定生成；
- 上下层误聚合 mainnode属于输入异常，不按普通 Junction全连接。

## 5. 正式 `RoadNextRoad` 图层

正式字段和值域沿用 RCSD RoadNextRoad数据规格。最小语义：

- source Road；
- target Road；
- source出口Node与target入口Node；
- 实际共享Node或ordinary JunctionUnit/mainnode语义证据（若正式规格没有这些字段，必须在审计层可恢复）；
- 必要方向/关系字段。

规则：

- Segment内部和复杂路口从实际共享Node/显式物理关系编译；
- ordinary可从同一正确分类JunctionUnit内方向兼容的进入—离开Road组合编译，必须记录source/target物理Node、`junction_group_id`和`mainnodeid`；
- 不得脱离Junction分类仅按`mainnodeid`字符串生成；
- ordinary不得把空间分离portal压到中值Node，也不得生成中心点或星形JunctionUnit Road；必须通过分布式高精portal Node、统一mainnode和ordinary语义RoadNextRoad表达。
- T04复杂路口按内部物理 carrier和LaneTopo/保留关系生成；
- 原始SWSD用于逐Segment Access方向和逐Junction Movement完整性验收，不作为built几何来源，也不要求输出Road与SWSD Road一一对应；
- T04内部证据暂缺时，仅允许shared Node、两侧member lineage匹配且portal均位于accepted surface的原始SWSD关系以`complex_junction_swsd_explicit`发布；
- Restriction/Laneinfo合法性不进入本层。

## 6. 审计图层

`p04_segment_first_audit.gpkg` 按需包含：

- `segment_build_units`；
- `junction_units`；
- `segment_accesses`；
- `road_carrier_plans`；
- `road_geometry_sources`；
- `junction_internal_carriers`；
- `swsd_topology_contract`；
- `swsd_junction_movement_contract`；
- `lane_topo_connection_exclusions`；
- `physical_movements`；
- `reality_change_clues`；
- `hard_gate_violations`；
- `soft_review_features`；
- `input_quality_flags`。
- `target_coverage_contract`：完整Baseline及DirectBuild资格；
- `target_realization`：Baseline实现、DirectBuild结果和PublishDisposition；
- `target_patch_data_insufficient`、`target_reality_change_clues`及分类证据。

`p04_segment_first_relations.gpkg` 按需包含：

- `segment_road_relation`；
- `road_lane_relation`；
- `junction_node_relation`；
- `source_lineage_relation`。

## 7. 发布状态合同

每个 T01 Segment必须有且只有一个：

- `hp_full`；
- `hp_partial`；
- `swsd_retained`；
- `conflict_retained`。

同时发布：

- `segment_publishable`；
- `carrier_takeover_ready`；
- `replacement_scope=all/subset/none`；
- `reason_codes`。

`hp_partial` 不能解释为“一条 Road内拼 SWSD”；它表示完整 Road级的 built/retained组合，或完整 built Road内部 observed/constrained组合。

## 8. Junction来源合同

| Junction类型 | 首选 | 次选 | fallback |
|---|---|---|---|
| ordinary | T07 accepted | T03 accepted | verified full RCSD → SWSD retained |
| complex_divmerge | T04 accepted | verified full RCSD | SWSD retained |
| roundabout | T08/T01 | verified full RCSD | SWSD retained |
| auxiliary | T01 junc relation + applicable accepted surface | verified Patch/RCSD | SWSD retained |

- T07/T03冲突采用 T07并审计。
- review/rejected surface不得冒充 accepted。
- 不发布 `junction_geometry_unresolved`。

## 9. hard gate

以下任一存在时，新 carrier不得接管：

1. Segment无独立 Road；
2. 必要方向 carrier缺失、方向重复或双向/单向重叠；
3. built Road含 SWSD直接坐标片段；
4. Road无有效 Node或起终点引用不存在；
5. SegmentAccess不属于正确 Junction组或 mainnode不一致；
6. 任一正式Segment Road未实现其适用Access；
7. ordinary Junction portal缺少accepted surface/DriveZone支撑，或出现中心聚合Node/星形内部Road；
8. 真实 `junc_nodes` 静默丢失；
9. actual shared Node型RoadNextRoad无真实共享Node，或ordinary语义型RoadNextRoad的source/target Node不属于同一正确分类JunctionUnit；
10. constrained completion越出合法道路域、穿越硬隔离或无法解释；
11. confirmed LaneTopo证明同Segment主 carrier物理拓扑不成立；
12. CRS未知、转换失败或隐式跨 CRS运算；
13. 独立 QA缺失、不可读或 gate失败。
14. 必要方向主干链断裂、分叉、缺少终端Access，或细分Road缺少Lane/Patch lineage。

跨Segment LaneTopo被物理证据拒绝时必须显式excluded，但该Movement级拒绝不构成两侧Segment回退条件；同Segment内部拒绝按单Segment hard gate处理。

hard gate失败时按单 Segment回退；不得用 Review豁免。

## 10. soft Review

以下可在 carrier hard gate通过时带 Review发布：

- 一方向依赖推导；
- constrained completion跨度或曲率接缝偏高；
- Road中心走廊置信度较低但仍在合法道路域；
- 完整 RCSD与Patch证据存在可解释差异；
- Lane/Boundary宽度或稳定性异常已被隔离；
- 局部 Movement证据不足但不影响主 Segment carrier；
- T07/T03 surface差异但T07 accepted有效。

## 11. 独立质量合同

独立 QA必须从发布文件重新读取，至少复算：

- CRS和schema；
- T01 Segment覆盖、四态唯一性、每 Segment Road数；
- geometry source全覆盖和无 SWSD splice；
- Road有效性、道路面覆盖、平滑/接缝指标；
- Node引用、mainnode一致性；
- RoadNextRoad共享 Node真实性；
- `junc_nodes` 保存；
- LaneTopo三去向与confirmed守恒；
- 跨 Patch断裂和ID稳定性；
- 输入/参数/output hash和性能字段；
- 旧 P04 callable和冻结成果不回归。

## 12. QGIS合同

工程至少包含以下分组：

1. 正式三图层：Road/Node/RoadNextRoad；
2. 原始 SWSD；
3. 完整 RCSD；
4. Patch Road/Lane/LaneBoundary/RoadSurface；
5. 既有 P04冻结成果；
6. Segment/Junction/Access关系；
7. geometry source与carrier状态；
8. LaneTopo/PhysicalMovement；
9. soft Review；
10. hard gate违规。

工程必须使用相对数据源，PyQGIS构建和独立回读都通过；正式三图层及核心比较层默认可见。

## 13. 终态

`terminal_status=passed` 必须同时满足：

- 生成器 core gate通过；
- 正式 GPKG写出并回读通过；
- 独立 QA `gate_pass=true`；
- QGIS构建和独立回读通过；
- 完整真实测试范围机器审计完成；
- 人工审计结论已记录；
- 所有软 Review有逐对象清单；
- 所有输入、参数、环境和结果可追溯。
- Baseline、DirectBuild和完整发布三套指标同时发布；`direct_build_required`实现率为100%。

任一必要证据缺失时不得写成 passed。

实现合同：`run_segment_first_road_direct(...)`只生成`failed/technical_passed`；`finalize_segment_first_run(output_dir, acceptance_manifest_path)`验证全部外部证据及其hash后，才更新summary/report并写`p04_segment_first_acceptance.json`。
