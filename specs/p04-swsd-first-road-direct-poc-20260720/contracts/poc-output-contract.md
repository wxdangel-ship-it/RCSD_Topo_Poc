# P04 POC Output Contract

## 1. 状态

第一、第二里程碑及 Directional Road V2 独立几何/拓扑修订已实现并通过 1885118 验证；V2 使用独立 callable/输出包，M2 产物保持只读对照。权威 V2 run 为 `p04_directional_v2_1885118_20260721T154712`，终态为 `passed`；旧 `T121556` 和 `T145722` 只作历史基线。所有成果仍不是正式生产稳定接口；仓库没有 repo CLI、root script 或正式生产入口。任何候选参数在进入稳定接口前仍需多 Case、人工真值和生产数据验证。

## 2. 目标输出包

| 文件 | 类别 | 业务含义 |
|---|---|---|
| `p04_input_manifest.json` | formal POC evidence | 输入路径、文件 hash、Patch、CRS、参数和环境。 |
| `p04_patch_vector_profile.json` | formal POC evidence | 表、字段、数量、空值、几何、引用和观测值分布。 |
| `p04_swsd_skeleton.gpkg` | POC candidate | SWSD RoadSection/Junction/Arm/Movement 语义骨架。 |
| `p04_evidence_assignment.gpkg` | POC candidate | Vector evidence 到 SWSD 单元的候选与决策。 |
| `p04_lane_decisions.gpkg` | POC candidate | Lane accepted/rejected/review/insufficient 决策。 |
| `p04_lane_evidence_segments.gpkg` | POC candidate | 原始 Lane 在 SWSD 约束下的局部片段 owner、源/目标里程和质量状态。 |
| `p04_input_quality_flags.csv` | review-only | Lane/LaneTopo/LaneBoundary 原始质量问题，独立于 Road 发布状态。 |
| `p04_road_support_intervals.gpkg` | POC candidate | 每条 SWSD Road 的高精支持、SD 缺口或可信冲突区间及来源。 |
| `p04_road_candidates.gpkg` | POC candidate | 571 条 Road 候选、混合几何和四态 `support_state`。 |
| `p04_movement_projection.gpkg` | POC candidate | LaneTopo/ReferenceLane 到 RoadGraph 的投影。 |
| `p04_conflicts.csv` | review-only | SWSD、LaneTopo、ReferenceLane、道路面和分隔证据冲突。 |
| `p04_run_summary.json` | summary | 总量、阶段状态、耗时、内存和主要原因。 |
| `p04_road_graph.gpkg` | POC publish | 范围内完整 SWSD Road/movement 图及高精支持状态。 |
| `p04_milestone2_comparison.qgz` | formal POC QA | 相对路径 QGIS 工程，叠加 SWSD、原始 Vector、旧成果、本轮四态 Road、支持/缺口和 QA。 |
| `p04_directional_lane_groups.gpkg` | POC candidate V2 | 方向 LaneGroup 成员、横向排序、覆盖/稳定性、唯一中心锚点和 CrossDirectionQualityAudit；塌缩 Lane仅以 `topology_only_review` 保留。 |
| `p04_directional_support_intervals.gpkg` | POC candidate V2 | 每个方向子 Road的高精支持/SD 缺口区间、完整 HP/transition/SD 几何来源分段、拟合站点和 LaneGroup 包络。 |
| `p04_directional_roads.gpkg` | POC publish V2 | 方向子 Road、纯 SD 父 Road保留对象、父语义 lineage、四态和稳定中心几何。 |
| `p04_directional_movements.gpkg` | POC publish/review V2 | confirmed DirectionalMovement、逐 LaneTopo 投影明细和端点协调审计；review 关系保留但不参与协调。 |
| `p04_directional_road_graph.gpkg` | POC publish V2 | Directional Road、DirectionalPortal、DirectionalArm、DirectionalMovement、LaneTopo 投影审计和父 SWSD 映射。 |
| `p04_directional_geometry_audit.csv` | formal POC QA | 方向拆分、锚点、跳变、高精片段振荡、长度膨胀、包络、无证据保留、Portal 和端点协调明细。 |
| `p04_directional_independent_quality.json` | formal POC QA gate | 独立进程从发布 GPKG 复算的 CRS、valid/simple、父 lineage、全部多端物理节点、支持 Road 平滑和 Movement 门户/接头总结；`gate_pass=true` 是终态必要条件。 |
| `p04_directional_independent_quality.gpkg` | formal POC QA detail | `road_smoothness_audit / physical_node_audit / movement_join_audit / direction_pair_audit` 逐对象明细及违规几何，供 QGIS 独立定位。 |
| `p04_directional_current_rcsd_comparison.gpkg` | comparison | Directional Road 到多段同向 RCSD 走廊的 5 m 采样距离、2 m/5 m 覆盖率及最佳单条 lineage。 |
| `p04_directional_v2_comparison.qgz` | formal POC QA | 相对路径 QGIS 对比工程；首组必须显式并列原始 SWSD Road只读投影副本、原始 RCSD Road只读投影副本和新生成 Directional Road V2，三层默认可见；另默认显示物理节点 movement、复杂语义路口连接和三类 LaneTopo review，并保留 M2、中心锚点、方向 LaneGroup、旧 Patch Road和拓扑 QA。 |

第二里程碑 `p04_road_graph.gpkg` 必须保留范围内全部 SWSD Road。V2 另外要求父 SWSD 语义对象守恒，并将存在高精证据的双向父 Road展开为两个单方向子 Road；缺证据方向只能显式 `sd_only`，纯 `sd_only` 父 Road允许保留原 SWSD 表达。只有 `hp_supported` Road 可以声明全里程高精支持。V2 发布跨 owner LaneTopo 的 DirectionalMovement 投影，但 restriction/Laneinfo、ReferenceLane 补充与完整 movement 合法性仍留待后续。

## 3. 最小公共字段

所有空间/关系输出至少保留：

- `run_id`
- `source_patch_ids`
- `source_object_type`
- `source_object_ids`
- `swsd_unit_id`
- `decision`
- `reason_codes`
- `evidence_quality_state`（证据层；Road 输出可为汇总）
- `input_manifest_ref`
- `support_state`

Lane decision 还必须携带 `left_boundary_id/right_boundary_id/inferred_lane_width_m/width_sample_coverage` 及宽度分位数/波动审计。

## 4. 状态分层

- `accepted`：当前 POC 规则和不变量均通过。
- `rejected`：存在明确负向证据。
- `review_required`：存在多候选或证据冲突。
- `insufficient_evidence`：SWSD 语义存在，但 Patch 高精资料不足。

这些是 POC 决策状态，不是生产发布状态，也不能自动回写 T05/T06/T09。

最终发布支持状态：

- `hp_supported`：Road 全里程获得可信高精几何支持并通过不变量。
- `partial_hp_supported`：Road 仅部分里程获得可信高精几何支持；必须同时发布支持和缺口区间。
- `sd_only`：高精资料不足，使用 SWSD 几何/拓扑保留完整语义。
- `conflict_retained`：经过独立输入质检后仍可信的高精证据与 SWSD Road 结构冲突，保留 SWSD 语义并发布冲突审计。

`support_state` 只属于 Road 发布层。窄 Lane、宽度/Boundary-gap、宽度不稳定、Boundary 资料不足、方向复核和跨 Road 语义节点异常使用 `evidence_quality_state/reason_codes`，不得直接映射为 `conflict_retained`。

## 5. Directional Road V2 终态拒绝条件

以下任一条件成立时，V2 结果不得发布为 `passed`：

- 独立 QA JSON 缺失、不可读或 `gate_pass != true`；
- 任一发布空间层 CRS 不是 EPSG:32650，或 Road/Movement 存在 invalid/non-simple/父 lineage 缺失；
- 任一多端物理节点端点间距超过 0.05 m；
- 任一支持 Road 按 5 m 站距与方向对齐父 SWSD 比较的局部转角增量超过 12°；
- 任一 Movement 到两侧 Portal 偏差超过 0.05 m，或与两侧 Road 接头夹角超过 10°；
- 任一正反锚点塌缩候选仍发布 forward/reverse 方向子 Road，或已发布双向高精片段中位间距低于该父 Road 的宽度相对要求；
- core、QGIS 构建、独立 PyQGIS 回读或 DriveZone overlay 任一门禁失败。

上述数值是当前 1885118 单 Case POC 验收参数，不是生产稳定接口或全量容差。

## 6. 其它拒绝发布条件

- 输入 CRS 缺失或混算。
- 同一 accepted LaneEvidenceSegment 出现多个 Road owner，或分段覆盖源 Lane 身份且无法追溯；第一里程碑 whole-Lane primary owner 仍须唯一。
- Road 支持/缺口区间没有完整覆盖 `[0, 1]`、发生重叠或长度不守恒。
- Road 混合几何片段缺少 `geometry_source` 或无法追溯到 Lane/SWSD 来源。
- M2 Road 首尾点偏离 SWSD 门户；或 V2 Directional Road首尾点与自身 DirectionalPortal/Arm 不重合、Portal/Arm 缺失/重复、父 semantic junction lineage 无法追溯。
- 使用未确认枚举执行强过滤。
- 输入 hash、参数或版本信息不完整。
- 冲突被静默修复。
- SWSD Road 未进入 `hp_supported / partial_hp_supported / sd_only / conflict_retained` 任一发布状态。
- 将纯输入质量异常直接转换为 Road `conflict_retained`。
- 非纯 `sd_only` 双向父 Road仍以单个 `direction in {0,1}` 对象发布，或正反向 Lane 证据混入同一方向子 Road。
- V2 硬几何锚点来自 `review/insufficient/excluded`，锚点发生未解释切换，或有证据站点越出 DirectionalLaneGroup 包络。
- V2 平滑、长度膨胀或 DirectionalPortal 门禁失败但仍标记为 passed。
- 无证据站点/端点发生非零高精横移，或高精拟合跨 gap 外推。
- confirmed 同物理 Node movement 两侧 Road 端点不共点，movement 几何未触及两侧 Portal，或 confirmed/review LaneTopo 数量不守恒。
- review LaneTopo 被静默吸附、删除或参与端点协调。
- `partial_hp_supported` 缺少 `high_precision_claim_scope=supported_intervals_only`，长 SD gap 声明与独立重算不一致，或将长 gap Road 静默删除/声明为全里程高精。
