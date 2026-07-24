# Data Model: P04 Segment-first Road 直出

## 1. 身份与分层原则

```text
T01 business identity
  Junction / Segment / JunctionSegmentRelation
             ↓
P04 physical realization
  JunctionUnit / SegmentAccess / RoadCarrierPlan / PhysicalMovementAudit
             ↓
RCSD candidate publication
  Road / Node / RoadNextRoad
```

- `Segment` 与 `Junction` 是业务对象，不等于 Road/Node。
- 正式发布的 Segment必须有独立 Road；业务对象不直接进入 RCSD正式三图层。
- P04不改变 T01 Segment ID和关系。
- P04新 Road不继承 SWSD Road ID；所有 lineage通过关系表保留。
- 对象 ID统一 canonical string参与内存与审计；正式数值/字符串编码遵循输入 RCSD数据规格。

## 2. SegmentBuildUnit

表示一个 T01 Segment在 P04中的唯一顶层工作单元。

| 字段 | 类型 | 语义 |
|---|---|---|
| `segment_id` | string | T01 `segment.gpkg.id/segmentid` canonical ID |
| `sgrade` | string | T01正式 Segment等级/方向类别 |
| `pair_node_ids` | list[string] | 两端语义 Junction ID，按 T01顺序 |
| `junc_node_ids` | list[string] | Segment中部真实 Junction关系 |
| `swsd_road_ids` | list[string] | T01归属 Road lineage |
| `source_patch_ids` | list[string] | 由归属 Road和Patch证据汇总的有序集合 |
| `direction_structure` | enum | `oneway / bidirectional / unresolved_input` |
| `build_state` | enum | `pending / hp_full / hp_partial / swsd_retained / conflict_retained` |
| `segment_publishable` | bool | 最终是否具有可发布完整 carrier集合 |
| `carrier_takeover_ready` | bool | 新/混合 carrier集合是否可接管原 SWSD carrier |
| `replacement_scope` | enum | `all / subset / none` |
| `reason_codes` | list[string] | 决策原因，禁止自由文本替代结构化原因 |

### 不变量

1. `segment_id` 在一次运行内唯一。
2. `build_state != pending` 时必须有 `RoadCarrierPlan`。
3. `segment_publishable=true` 时至少有一条发布 Road。
4. `hp_full -> replacement_scope=all`。
5. `swsd_retained/conflict_retained -> replacement_scope=none`。
6. `hp_partial -> replacement_scope=subset`，且完整 carrier覆盖全部必要方向/access。

### 2.1 TargetDispositionContract

| 字段 | 类型/值域 | 语义 |
|---|---|---|
| `segment_id` | string | 必须属于输入确定的Baseline。 |
| `baseline_target` | bool | 原始闭域成员，不被例外分类改写。 |
| `baseline_target_class` | `core / advance_right` | 原始目标分类。 |
| `direct_build_eligibility` | `direct_build_required / patch_data_insufficient / reality_change` | 默认必建。 |
| `direct_build_required` | bool | 由eligibility确定的硬分母标志。 |
| `direct_build_outcome` | `realized / hard_conflict / partial_evidence_unresolved / not_applicable` | 直出结果。 |
| `publish_disposition` | enum | 完整发布的业务处置。 |
| `classification_reason_codes` | list[string] | 例外分类原因。 |
| `classification_evidence_ids` | list[string] | 可定位证据。 |
| `classification_source/reviewed_by` | string | 来源与确认人/流程。 |
| `classification_manifest_hash` | string | 外部清单hash。 |
| `reality_change_clue_id` | string? | 现实变化线索身份。 |

例外清单不得包含Baseline之外对象、重复对象或空原因/证据；`hard_conflict/partial_evidence_unresolved`不得映射为`not_applicable`。

## 3. JunctionUnitCandidate

表示业务 Junction的物理 Road/Node实现候选。

| 字段 | 类型 | 语义 |
|---|---|---|
| `junction_id` | string | T01/SWSD语义 Junction ID，通常为 mainnode或singleton node |
| `junction_type` | enum | `ordinary / complex_divmerge / roundabout / auxiliary / retained` |
| `source_module` | enum | `T07 / T03 / T04 / T08_T01 / FULL_RCSD / SWSD` |
| `source_object_ids` | list[string] | surface/case/RCSD对象 lineage |
| `surface_state` | enum | `accepted / retained / unavailable / conflict` |
| `surface_geometry` | Polygon/MultiPolygon? | accepted时的物理边界；发布前须满足来源契约 |
| `priority_rank` | int | 业务优先级审计，不作为无条件覆盖 |
| `mainnode_id` | string | 本 JunctionUnit发布 Node共享 mainnode |
| `default_physical_full_connectivity` | bool | 仅普通、正确聚合的平交路口可为 true |
| `review_reasons` | list[string] | T07/T03差异、RCSD fallback等软审计 |

### 来源优先级

```text
ordinary: T07 accepted > T03 accepted > FULL_RCSD verified > SWSD retained
complex_divmerge: T04 accepted > FULL_RCSD verified > SWSD retained
roundabout: T08/T01 > FULL_RCSD verified > SWSD retained
```

T07与 T03冲突时使用 T07；差异必须审计。`review_required` surface不能替代 accepted。

## 4. SegmentAccess

表示 Segment Road与 JunctionUnit之间的业务交接位置。

| 字段 | 类型 | 语义 |
|---|---|---|
| `access_id` | string | 稳定派生 ID |
| `segment_id` | string | 所属 Segment |
| `junction_id` | string | 关联 JunctionUnit |
| `relation_role` | enum | `ENDPOINT / THROUGH` |
| `direction_role` | enum | `ENTER / EXIT / BOTH` |
| `portal_geometry` | Point | Road/Node图中的物理交接点 |
| `source` | enum | `surface_intersection / inherited_node / verified_rcsd / constrained` |
| `handoff_state` | enum | `ready / retained / failed` |
| `mainnode_id` | string | 必须与关联 JunctionUnit一致 |

### 不变量

- `handoff_state=ready` 时必须能连接至少一条 Segment Road和一个 Junction内部/共享 Node。
- 当前阶段只 hard gate Junction组和 mainnode一致性；几何最优属于独立 QA。
- 不建立独立 `SegmentApproachAdapter` 业务对象。

## 5. RoadCarrierPlan

表示一个 Segment最终发布所需的完整 Road集合。

| 字段 | 类型 | 语义 |
|---|---|---|
| `segment_id` | string | owner |
| `required_carrier_roles` | list[string] | 根据 T01方向、主辅路和证据确定的必要角色 |
| `road_candidates` | list[string] | RoadBuildCandidate ID |
| `coverage_complete` | bool | 是否覆盖全部必要方向与 access |
| `direction_overlap_free` | bool | 是否无方向/物理重复 |
| `node_topology_complete` | bool | 是否可编译 Node与RoadNextRoad |
| `lane_topo_explainable` | bool | confirmed LaneTopo是否可解释或显式阻断 |
| `hard_gate_pass` | bool | carrier接管门禁 |
| `failure_reasons` | list[string] | 失败原因 |

### 典型组合

| 场景 | Road组合 |
|---|---|
| 两方向均可观测 | 两条 `built` 单方向 Road |
| 一方向观测、另一方向可推导 | 两条 `built` Road，其中一条含 constrained来源 |
| 上下行不可区分 | 一条 `built` 双向 Road |
| 多主辅物理走廊 | 同 Segment下两条以上 `built/retained` Road |
| 某完整 carrier无证据 | 其它完整 Road `built`，该完整 Road `retained` |
| 原仅双向 Road且只可建一方向 | 不允许新单向+原双向；全部保留或构建两个方向 |

## 6. EvidenceObservation

统一表达进入高精构建的 Patch证据，不改变原对象身份。

| 字段 | 类型 | 语义 |
|---|---|---|
| `evidence_id` | string | `patch_id + object_type + source_id` |
| `patch_id` | string | 来源 Patch |
| `object_type` | enum | `patch_road / lane / lane_topo / boundary / road_surface / divstrip / local_structure` |
| `source_id` | string | 原对象 ID |
| `segment_id` | string? | 唯一/候选 Segment归属 |
| `road_role_candidate` | string? | 方向/主辅/局部 carrier角色 |
| `quality_state` | enum | `usable / review / insufficient / excluded` |
| `quality_reasons` | list[string] | 输入质检原因 |
| `geometry` | Geometry | 原始或显式投影后的几何 |
| `source_crs` | string | 原 CRS |
| `analysis_crs` | string | 分析 CRS |

输入质量状态不能直接变成 Segment `conflict_retained`。

## 7. EvidenceSpan

表示沿一条拟建 Road走廊的连续几何来源区间。

| 字段 | 类型 | 语义 |
|---|---|---|
| `span_id` | string | 稳定 ID |
| `road_candidate_id` | string | 所属 Road |
| `start_measure/end_measure` | float | Road归一或米制里程 |
| `geometry_source` | enum | `hp_observed / hp_constrained_completion` |
| `support_evidence_ids` | list[string] | 支撑对象 |
| `constraint_types` | list[string] | Boundary/Surface/tangent/access等 |
| `review_state` | enum | `none / soft_review` |

### 不变量

- 新建 Road的 EvidenceSpan必须无缝覆盖 `[0, road_length]`。
- `hp_observed` 必须由直接高精中心走廊证据支撑。
- `hp_constrained_completion` 必须至少有可审计边界条件和合法道路域。
- 值域中不存在 `swsd_fallback`。

## 8. RoadBuildCandidate

表示最终可能发布的一条完整 Road。

| 字段 | 类型 | 语义 |
|---|---|---|
| `road_candidate_id` | string | 内部稳定 ID |
| `road_id` | RCSD ID | 正式候选 Road ID |
| `owner_type` | enum | `SEGMENT / JUNCTION_UNIT` |
| `segment_id` | string? | `owner_type=SEGMENT`时必填 |
| `junction_id` | string? | `owner_type=JUNCTION_UNIT`时必填，发布实现可用`junction_group_id`表达 |
| `carrier_role` | string | `main_forward/main_reverse/aux_*/through_part/local_connector/...` |
| `direction` | data-spec enum | 单向/双向，沿用数据规格 |
| `realization` | enum | `built / retained` |
| `source` | data-spec enum | Road数据规格 source |
| `source_patch_ids` | list[string] | lineage |
| `source_swsd_road_ids` | list[string] | lineage |
| `source_patch_road_ids` | list[string] | lineage |
| `snode_id/enode_id` | RCSD ID | 发布 Node |
| `geometry` | LineString | 完整 Road几何 |
| `evidence_span_ids` | list[string] | built Road来源；retained为空 |
| `review_reasons` | list[string] | 软 Review |

### 不变量

- `realization=built` 时只允许 observed/constrained来源。
- `realization=retained` 时整条沿用既有 carrier，不声明高精。
- 每条 Road必须有且只有一个 snode/enode。
- `segment_id` 与 `junction_id` 不得同时作为 owner；connectivity context另行审计。
- ordinary不得为默认全连接补造JunctionUnit Road或中心Node；`owner_type=JUNCTION_UNIT`只用于复杂路口、环岛或有显式原始carrier证据的局部结构。
- Segment Road必须逐Road实现适用Access；不能由同Segment其它Road代替。
- Road可在LaneGroup/Patch Road证据归属、物理Node、`junc_nodes`、分流合流或证据边界处细分；细分原因和Lane/Patch lineage必须可恢复。

### DirectionalTrunkChain

表示一个Segment必要方向的端到端主干实现，不等同于一条Road。

| 字段 | 类型 | 语义 |
|---|---|---|
| `segment_id` | string | owner Segment |
| `direction_role` | enum | `main_forward / main_reverse / main_oneway / shared_bidirectional` |
| `road_ids` | ordered list[RCSD ID] | 按通行方向排列的Road片段 |
| `start_junction_group_id/end_junction_group_id` | string | 两端T01 JunctionAccess |
| `chain_state` | enum | `complete / disconnected / branched / terminal_mismatch / duplicated` |
| `fragmentation_reasons` | list[string] | LaneGroup/Node/junc/movement/evidence等 |

不变量：

- 链内相邻Road共享实际Node；
- 单方向主干只有一个起点和一个终点，且分别属于Segment声明的两端JunctionAccess；
- 主干不得断裂、分叉或形成重复平行链；
- 双向Segment必须同时具有`main_forward`和`main_reverse`完整链；无法区分方向时使用一条`shared_bidirectional`链。

## 9. NodeBuildCandidate

| 字段 | 类型 | 语义 |
|---|---|---|
| `node_id` | RCSD ID | 正式候选 Node ID |
| `mainnode_id` | RCSD ID | JunctionUnit共享语义组；非路口内部 Node按数据规格处理 |
| `source` | enum | `inherited_rcsd / inherited_patch / generated / retained_swsd` |
| `junction_id` | string? | 所属 JunctionUnit |
| `geometry` | Point | 物理 Node位置 |
| `source_object_ids` | list[string] | lineage |
| `id_seed` | string | 稳定 ID生成审计，不一定发布到正式属性 |

### 不变量

- 同一 `junction_id` 的 Node `mainnode_id`唯一。
- 不同 `node_id` 可以共享 `mainnode_id`。
- ID生成与 Patch读取顺序无关。

## 10. RoadNextRoadCandidate

| 字段 | 类型 | 语义 |
|---|---|---|
| `source_road_id` | RCSD ID | 入 Road |
| `target_road_id` | RCSD ID | 出 Road |
| `source_node_id/target_node_id` | RCSD ID | source出口与target入口物理Node |
| `shared_node_id` | RCSD ID? | `actual_shared_node`时必填 |
| `mainnode_id` | RCSD ID? | ordinary语义关系时必填 |
| `junction_id` | string? | 关联 JunctionUnit |
| `movement_source` | enum | `actual_shared_node / ordinary_junction_semantic / complex_junction_swsd_explicit / lane_topo / patch_road / retained_rcsd / complex_junction` |
| `audit_movement_ids` | list[string] | LaneTopo/PhysicalMovement lineage |

### 不变量

- `movement_source=actual_shared_node`时，`shared_node_id`必须同时是source Road出口和target Road入口的实际Node。
- `movement_source=ordinary_junction_semantic`时，source/target Node可以不同，但必须属于同一正确分类ordinary JunctionUnit并共享mainnode；不能只比较mainnode字符串。
- `movement_source=complex_junction_swsd_explicit`时，审计必须同时恢复原始SWSD shared Node、两侧member lineage匹配和source/target portal位于T04 accepted surface三项证据。
- T04复杂路口、环岛和聚合异常不得使用ordinary语义全连接。
- T09限制不在此对象中表达。
- ordinary跨SegmentMovement可直接映射到ordinary语义RoadNextRoad；被拒关系是Movement级排除，不自动回退两侧Segment。

## 11. PhysicalMovementAudit

| 字段 | 类型 | 语义 |
|---|---|---|
| `movement_id` | string | 审计 ID |
| `source_lane_id/target_lane_id` | string? | LaneTopo lineage |
| `source_road_id/target_road_id` | RCSD ID? | 投影结果 |
| `junction_id/segment_id` | string? | 业务上下文 |
| `projection_state` | enum | `mapped / soft_review / excluded / blocked` |
| `projection_kind` | enum | `internal_continuity / road_movement / uturn / local_connector` |
| `reason_codes` | list[string] | 结构化原因 |

PhysicalMovementAudit只表达物理可达证据，不表达 Restriction/Laneinfo合法性。

## 12. 关系审计

### SegmentRoadRelation

`segment_id, road_id, carrier_role, realization, replacement_scope, source_patch_ids`

### RoadLaneRelation

`road_id, patch_id, lane_id, relation_role, direction_compatibility, evidence_quality_state, support_scope`

### JunctionNodeRelation

`junction_id, node_id, mainnode_id, node_role, source`

### SourceLineageRelation

`target_type, target_id, source_type, source_id, patch_id, relation_role`

## 13. RealityChangeClue

| 字段 | 类型 | 语义 |
|---|---|---|
| `clue_id` | string | 稳定 ID |
| `clue_type` | enum | `advance_right / new_segment / changed_junction / other` |
| `related_segment_ids` | list[string] | 当前先验上下文 |
| `evidence_ids` | list[string] | 支撑证据 |
| `materialization_state` | enum | `clue_only / simple_road_ready / temporary_segment_ready / normalized` |
| `simple_road_ids` | list[RCSD ID] | 生成后才可填写 |
| `review_required` | bool | 当前必须 true，除非未来正式流程确认 |

`clue_only` 不能进入正式 Segment集合。

## 14. RunManifest

至少记录：

- `run_id / code_version / started_at / completed_at / terminal_status`；
- 全部输入绝对路径、文件hash、图层、CRS、数量；
- 参数与派生阈值；
- Patch/Segment/Junction范围；
- 输出相对路径与hash；
- 阶段耗时、吞吐、峰值内存（可获得时）；
- core gate、independent QA、QGIS build/readback状态；
- 旧版本保护hash或回归测试结果。

## 15. 状态机

```text
pending
  ├─ complete built carrier set ───────────────> hp_full
  ├─ complete mixed built/retained carrier set > hp_partial
  ├─ no usable takeover ───────────────────────> swsd_retained
  └─ trusted conflict / incomplete carrier ───> conflict_retained

每个终态
  ├─ segment_publishable=true（由 built 或 retained carrier保证）
  └─ hard gate决定新 carrier是否可接管
```

无 Road、错误 Junction组、错误 mainnode、丢失 hard `junc_nodes`、Node/RoadNextRoad不可编译、confirmed主 carrier冲突均不得成为新 carrier passed终态。
