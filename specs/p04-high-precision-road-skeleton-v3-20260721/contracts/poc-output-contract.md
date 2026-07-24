# P04 Road Direct V3 POC Output Contract

## 1. 稳定边界

本契约只适用于隔离的模块内研究 callable `run_high_precision_road_v3(HighPrecisionRoadV3Config)`。它不是 repo CLI、root script 或正式生产接口；V2、M2、T00-T12 V1 均保持不变。

## 2. 输出包

| 文件 | 图层 / 内容 |
|---|---|
| `p04_hp_v3_input_manifest.json` | 输入路径、hash、CRS、参数、运行环境和冻结 V2 lineage。 |
| `p04_hp_v3_corridors.gpkg` | `physical_corridor_decisions`、`road_units`、`center_observations`、`center_anchors`、`drivezone_constraints`。 |
| `p04_hp_v3_geometry_sources.gpkg` | `control_spans`、`geometry_segments`、`fit_stations`。 |
| `p04_hp_v3_roads.gpkg` | `high_precision_roads` 完整 V3 Road。 |
| `p04_hp_v3_road_graph.gpkg` | `roads`、`portals`、`arms`、`movements` 和 lineage。 |
| `p04_hp_v3_movements.gpkg` | confirmed/review LaneTopo、端点协调和 Movement 几何审计。 |
| `p04_hp_v3_current_rcsd_comparison.gpkg` | V3 与原始 RCSD 的只读走廊比较。 |
| `p04_hp_v3_frozen_v2_comparison.gpkg` | 每条 V3 Road 与同父语义、优先同 travel side 的冻结 V2 Road 只读形态差异。 |
| `p04_hp_v3_independent_quality.json` | 只读取发布 GPKG 的独立质量总结。 |
| `p04_hp_v3_independent_quality.gpkg` | 逐 Road、物理 Node、Movement、方向拆分、来源声明明细。 |
| `p04_hp_v3_summary.json` | core/QGIS/overlay/independent QA、覆盖、数量、性能和终态。 |
| `p04_hp_v3_report.md` | 面向业务的结果解释。 |
| `p04_hp_v3_four_network_comparison.qgz` | 四网显式对比和审计工程。 |

## 3. `high_precision_roads` 最小字段

- `v3_road_id`
- `parent_swsd_unit_id`
- `road_representation`
- `travel_side`
- `direction`
- `split_decision`
- `split_reason_codes`
- `support_state`
- `high_precision_claim_scope`
- `observed_length_m`
- `constrained_length_m`
- `swsd_fallback_length_m`
- `high_precision_control_ratio`
- `swsd_fallback_ratio`
- `anchor_strategy`
- `anchor_source_ids`
- `geometry_fit_state`
- `geometry_reason_codes`
- `geometry_valid`
- `geometry_simple`
- `source_patch_ids`
- `input_manifest_ref`
- `geometry`

## 4. 几何来源契约

- `hp_observed` 只能由可独立复算的 `usable` Lane/Boundary 直接观测产生。
- `hp_constrained_interpolation` 必须说明锚点、DriveZone、平滑、开放边界和拓扑门禁。
- `swsd_fallback` 必须说明无证据或哪个约束失败。
- 三类片段必须无重叠覆盖完整 Road，不允许空洞或重复高精声明。

## 5. QGIS 工程固定结构

首组 `00_四网显式对比` 默认显示：

1. 原始 SWSD Road；
2. 原始 RCSD Road；
3. 冻结 Directional Road V2；
4. 新生成 Road Direct V3。

其余分组至少包含：

- `01_V3高精来源`：observed、constrained interpolation、SWSD fallback；
- `02_物理走廊决策`：shared/split/fallback、中心锚点；
- `03_Lane与Boundary证据`；
- `04_DriveZone约束`；
- `05_LaneTopo与Movement`；
- `09_几何与拓扑QA`。

V3 主 Road按 `support_state` 分类，不以 `travel_side` 作为主图例。

## 6. 终态契约

`terminal_status=passed` 必须同时满足：

- core gates；
- `SC-004` 高精控制覆盖；
- `SC-005` SWSD fallback 比例；
- 几何 valid/simple/包络；
- 父语义、Portal/Arm、LaneTopo 和物理节点拓扑；
- QGIS 构建与独立 PyQGIS 回读；
- DriveZone overlay；
- 发布后独立 QA；
- 冻结 V2 hash 未变化。

任一门禁缺失、不可读或失败时不得发布 `passed`。
