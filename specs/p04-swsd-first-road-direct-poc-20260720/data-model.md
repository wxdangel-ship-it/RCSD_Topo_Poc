# P04 Data Model

## 1. 身份与来源原则

Patch Vector 对象当前没有可与 SWSD/现有 RCSD 直接连接的对象级 ID。P04 使用两类身份：

- 目标语义身份：来自 SWSD Road/Node 及 T01 语义构段。
- 源证据身份：`patch_id + object_type + source_id`。

任何空间匹配、合并或淘汰都不得覆盖源证据身份。

## 2. 核心对象

### 2.1 SWSDRoadSemanticUnit

回答“目标道路语义上是什么”。

| 字段 | 含义 |
|---|---|
| `swsd_road_id` | SWSD Road canonical ID，读取时需避免浮点字符串污染。 |
| `snode_id / enode_id` | 原始方向端点。 |
| `direction` | SWSD 方向语义；值域沿用上游契约。 |
| `segment_identity` | T01 构段后的语义身份；不能读取当前全空 `segment_id` 假定已存在。 |
| `patch_memberships` | `patch_id` 解析后的有序去重集合。 |
| `geometry` | SWSD 语义参考几何，不等同于最终高精 Road 几何。 |

### 2.2 SWSDJunctionUnit

回答“哪些 Road arm 在哪个语义路口发生连接”。

关键关系：代表 node、子 node、进入 arm、退出 arm、允许/限制 movement。SWSD restriction 和 Laneinfo 只在其正式契约内解释。

### 2.3 VectorEvidence

回答“某个 Patch 原始对象提供了什么证据”。

| 字段 | 含义 |
|---|---|
| `patch_id` | 证据所在 Patch。 |
| `object_type` | 原始 Vector 表名。 |
| `source_id` | 原始对象 ID；无 ID 的派生 Patch 面使用稳定行身份。 |
| `geometry` | 保留源三维几何和显式 CRS。 |
| `properties` | 原始字段，不就地改写。 |
| `semantic_status` | `confirmed_structure / observed_only / needs_dictionary`。 |
| `input_hash` | 输入文件追溯。 |

### 2.4 EvidenceAssignment

回答“证据可能属于哪个 SWSD 语义单元，以及依据是什么”。

| 字段 | 含义 |
|---|---|
| `evidence_identity` | VectorEvidence 复合身份。 |
| `target_unit_id` | SWSD Road/Junction/Arm 候选。 |
| `candidate_role` | lane、boundary、surface、separator、movement、facility、diagnostic。 |
| `fit_metrics` | 方向、距离、覆盖、连续、拓扑、Patch ownership 等可复算指标。 |
| `decision` | `accepted / rejected / review_required / insufficient_evidence`。 |
| `reason_codes` | 结构化原因，不以自由文本替代。 |

### 2.5 LaneHypothesis

回答“原始 Lane 是否进入目标机动车道路及归属哪里”。

关键证据包括：几何方向、LaneTopo 连续性、ReferenceLane 支持、道路面覆盖、空间推导宽度、Boundary/硬隔离关系、与邻 Lane 的排序。当前 `Width=3.5` 只能作为原始观测值。

空间宽度字段包括：`left_boundary_id/right_boundary_id`、`inferred_lane_width_m`、`width_sample_coverage`、`width_p10_m/width_median_m/width_p90_m` 和 `width_variation_m`。宽度由 Lane 局部垂线与左右方向/走廊相容 Boundary 的最近投影距离之和得到；双侧覆盖不足时状态为 `insufficient_evidence`。

### 2.6 RoadCandidate

回答“一个 SWSDRoadSemanticUnit 在高精证据层如何实例化”。

| 字段 | 含义 |
|---|---|
| `road_candidate_id` | POC 稳定身份，派生自目标语义单元和必要局部分段。 |
| `swsd_unit_id` | 唯一目标语义 owner。 |
| `member_lane_ids` | 提供 LaneEvidenceSegment 的原始 Lane 复合身份集合。 |
| `evidence_patch_ids` | 实际使用证据的 Patch 集合。 |
| `geometry` | 由支持区间的高精拟合片段和缺口区间的 SWSD 保留片段共同形成的候选几何。 |
| `support_state` | `hp_supported / partial_hp_supported / sd_only / conflict_retained`；最终图完整保留 SWSD Road 语义。 |
| `fit_audit` | 走廊、覆盖、隔离、宽度和冲突摘要。 |

### 2.7 LaneEvidenceSegment

回答“一条原始 Lane 的哪个连续片段支持哪个 SWSD Road”。原始 Lane 不被切写或改 ID；分段只是 P04 证据映射。

| 字段 | 含义 |
|---|---|
| `lane_id` | 原始 Lane 身份。 |
| `source_start_m/source_end_m` | 片段在原始 Lane 上的里程范围。 |
| `swsd_unit_id` | 该片段唯一 SWSD Road owner。 |
| `road_start_m/road_end_m` | 片段投影到 SWSD Road 的参考里程范围。 |
| `assignment_method` | 当前 POC 为 `local_swsd_viterbi`，参数必须进入 manifest。 |
| `evidence_quality_state` | 片段独立质检状态；不等于 Road `support_state`。 |

第一里程碑 LaneHypothesis 的唯一 primary owner 继续作为整 Lane 诊断事实；第二里程碑不要求整条源 Lane 只能支持一个 Road，但要求每个连续证据片段只有一个 owner。

### 2.8 RoadSupportInterval

回答“一个 SWSD Road 的哪些里程由高精证据支持，哪些仍保留 SD”。

| 字段 | 含义 |
|---|---|
| `swsd_unit_id` | 唯一 SWSD Road owner。 |
| `start_fraction/end_fraction` | SWSD Road 归一化里程区间，闭合范围 `[0, 1]`。 |
| `interval_state` | `hp_supported / sd_gap / conflict_retained`。 |
| `source_lane_ids/source_patch_ids` | 形成该区间的可信证据来源；SD 缺口允许为空。 |
| `coverage_length_m` | 区间对应的 Road 参考长度。 |
| `geometry_source` | `hp_fitted / swsd_retained / conflict_retained`。 |
| `reason_codes` | 区间合并、缺口或冲突原因。 |

每条 Road 的区间必须排序、不重叠并完整覆盖 `[0, 1]`；区间总长度与 Road 参考长度在浮点容差内守恒。

### 2.9 EvidenceQualityFlag

回答“原始 Lane/LaneTopo/LaneBoundary 有什么质量风险”。至少包含证据身份、质量类别、严重度、指标、原因码和来源。它不含 Road 发布 `support_state`，也不得被直接映射为 `conflict_retained`。

当前已知类别包括 `narrow_lane`、`wide_or_boundary_gap`、`width_unstable`、`boundary_insufficient`、`direction_review` 和 `cross_road_semantic_node_anomaly`。

### 2.10 完整 MovementProjection 与合法性（后续里程碑）

回答“Lane movement 怎样形成目标 RoadGraph movement”。

| 字段 | 含义 |
|---|---|
| `from_lane / to_lane` | 源 Lane 复合身份。 |
| `source_kind` | `lane_next_lane / reference_lane / both`。 |
| `from_road / to_road` | 投影后的 RoadCandidate。 |
| `projection_kind` | `internal_continuity / road_movement / conflict`。 |
| `flow_num_observed` | ReferenceLane 原始 FlowNum；作为轨迹聚合强度弱证据，不解释为精确车流量或合法通行。 |
| `swsd_movement_check` | 与 SWSD arm/restriction 的一致、冲突或资料不足状态。 |

当前 V2 不实现本实体的 restriction/ReferenceLane 完整合法性，只实现 2.14 的 LaneTopo 方向投影。

### 2.11 DirectionalRoadCandidate（V2）

回答“一个 SWSD 父 Road 在单一行驶方向上如何发布”。

| 字段 | 含义 |
|---|---|
| `directional_road_id` | `parent_swsd_unit_id + travel_side` 派生的稳定 V2 身份。 |
| `parent_swsd_unit_id` | 保持 SWSD 语义 lineage，不因方向展开改变。 |
| `travel_side` | `forward / reverse / sd_parent`。 |
| `direction` | 发布编码；有高精方向子 Road按几何行驶方向统一为单方向，reverse 子 Road交换起终点并反转几何。 |
| `directional_support_state` | 方向层 `hp_supported / partial_hp_supported / sd_only / conflict_retained`。 |
| `high_precision_claim_scope` | `full_road / supported_intervals_only / none`；把 Road 语义存在与高精声明范围分开。 |
| `sd_gap_risk_state` | `no_sd_gap / bounded_sd_gap / long_sd_gap_review / all_sd`；100 m 是当前 POC 复核阈值。 |
| `cross_direction_*` | 正反向锚点中位/P95 间距、较窄侧 Lane 宽度、要求间距与 gate；没有双向证据时为空。 |
| `anchor_kind / anchor_source_id` | 唯一稳定中心 Lane 或共享 LaneBoundary；纯 SD/缺证据方向为空。 |
| `geometry` | 中心锚点提供形态、平滑和包络约束后的方向几何；不是源 Lane/Boundary 的绝对复制。 |

### 2.12 DirectionalLaneGroup（V2）

回答“哪些同向 LaneEvidenceSegment 共同定义一个方向 Road 的横向包络和中心”。每条记录保留 Lane、方向、覆盖率、横向排序、中心性、曲率稳定性、质量状态和 `member/anchor/soft_review/topology_only_review` 角色。`topology_only_review` 只为塌缩降级父 Road保留 LaneTopo lineage，不能拉动几何。源 `RoadId/LaneGroup` 只作 comparison，不决定该分组。

### 2.13 DirectionalPortal / DirectionalArm（V2）

DirectionalPortal 是方向 Road 自身首尾点的高精拓扑端口，携带父 SWSD semantic junction lineage；DirectionalArm 从方向 Road首尾向内形成可审计短段。V2 的强闭合不变量是 DirectionalRoad—DirectionalPortal/Arm 坐标一致，不是方向 Road回到父 SWSD 中心门户。

### 2.14 DirectionalMovementProjection（V2）

回答“跨 owner LaneTopo 如何约束方向 Road 端点与路口连接”。至少保留源/目标 Lane、源/目标 DirectionalRoad、输入 `lane_topo_state`、`projection_state/reason_codes`、语义/物理节点关系和源 LaneTopo 几何。

- `same_physical_node` confirmed movement：来源 Road 的 `e` 与目标 Road 的 `s` 共享协调后的 Portal；若组件内任一端点无高精支持，协调目标使用 SWSD 物理 Node，否则使用组件高精端点的稳健中心。
- `same_semantic_junction` confirmed movement：保留两侧 DirectionalPortal，以 LaneTopo 对齐几何或可解释切线连接形成 movement。
- `review`：方向待复核、语义不连通、方向 Road 语义端点冲突或映射不唯一；不得参与端点协调。
- 该实体表达 LaneTopo 一致性，不等于 restriction/Laneinfo 意义上的合法通行结论。

### 2.15 CrossDirectionQualityAudit（V2）

回答“同一双向父 Road 的正反向证据是否足以实例化为两个物理分离的方向 Road”。每个方向各保留一条 provisional 中心锚点几何，并共享 `anchor_median_separation_m / anchor_p95_separation_m / reference_lane_width_m / required_min_separation_m / anchor_gate_pass`。要求间距为 `max(0.5 m, 0.5 × 较窄侧 Lane 宽度)`；失败只降级方向几何资格，不反写原始 Lane QA。

### 2.8 DecisionAudit

回答“为什么接受、拒绝、保留或交人工”。至少包含输入版本、参数、CRS、候选、指标、规则版本、决定、原因和运行环境。

## 3. 关系与不变量

```text
SWSDRoadSemanticUnit 1 --- N PatchMembership
SWSDRoadSemanticUnit 1 --- N EvidenceAssignment
VectorEvidence       1 --- N EvidenceAssignment
SWSDRoadSemanticUnit 1 --- N RoadCandidate
LaneHypothesis       1 --- N LaneEvidenceSegment
LaneEvidenceSegment N --- 1 SWSDRoadSemanticUnit
RoadCandidate        N --- N LaneHypothesis (通过 LaneEvidenceSegment 追溯)
RoadCandidate        N --- N MovementProjection
DirectionalRoadCandidate N --- N DirectionalMovementProjection
```

必须验证：

1. 第一里程碑 accepted Lane 只有一个 primary Road owner；第二里程碑每个 accepted LaneEvidenceSegment 只有一个 Road owner，原始 Lane 可以跨多个相邻 Road。
2. accepted LaneNextLane 恰好解释为内部连续、Road movement 或冲突之一。
3. 每个 `hp_supported` Road movement 至少有一条 accepted Lane movement 证据。
4. Patch membership 只是候选空间边界，不能替代对象级空间/拓扑判断。
5. 旧 Road/RoadNextRoad 不能反向覆盖目标语义对象。
6. 范围内 SWSD Road 总量必须等于 `hp_supported + partial_hp_supported + sd_only + conflict_retained`，未发布数为 0。
7. 每条 Road 的 RoadSupportInterval 必须完整覆盖 `[0, 1]`、互不重叠且长度守恒。
8. EvidenceQualityFlag 只能描述输入质量，不能仅凭质量异常产生 Road `conflict_retained`。
9. 第二里程碑不消费 SWSD restriction/Laneinfo 或 RoadSplit，不发布 movement 合法性结论。
10. V2 中存在 `usable` 高精证据且通过 CrossDirectionQualityAudit 的双向 SWSD 父 Road必须发布 forward/reverse 两个方向子对象；正反锚点塌缩时必须回退为单个 SWSD 父表达，纯 `sd_only` 父 Road同样可保持单个 SWSD 表达。
11. 一个 DirectionalRoad 只能消费同一 `travel_side` 的 LaneEvidenceSegment；硬锚点只能来自 `usable` Lane 或由中间可用 Lane共同确认的共享 Boundary。
12. 每个高精 DirectionalRoad 的稳定中心锚点唯一，未解释锚点切换数为 0；有证据站点的拟合横移必须位于 DirectionalLaneGroup 包络内。
13. 每个 DirectionalRoad 恰有两个自身 Portal/Arm，Road 端点与 Portal/Arm 在容差内重合；reverse 子 Road的几何、起终点和语义 lineage 必须同步反转。
14. 无高精证据站点和端点的横移为 0；高精拟合不得跨越无证据 gap 外推。
15. confirmed 同物理 Node DirectionalMovement 的两侧 Road 端点共点；复杂语义路口 movement 几何必须触及两侧 DirectionalPortal。
16. 跨 owner LaneTopo 输入必须满足 `confirmed + review = input`；confirmed link 聚合到 Road movement 后数量守恒，review 不得丢失。
17. `partial_hp_supported` 的高精声明范围只能是 `supported_intervals_only`；长 SD gap 只触发复核，不改变语义 Road 完整性。
18. 独立 QA 必须覆盖双向锚点与发布高精片段间距；塌缩候选不得残留两个方向发布对象。

## 4. 证据可信分层

- **结构确认层**：ID、外键关系、几何、CRS、记录数、Patch membership、集合投影事实。
- **高价值候选层**：Lane、LaneTopo、Boundary、ReferenceLane、DriveZone、硬隔离和路口设施。
- **旧成果诊断层**：Road、RoadNextRoad、Road-level relation。
- **待字典层**：枚举值和 `RawEvent.Type` 等未确认业务含义。

该分层只控制 POC 使用姿态，不等同于生产置信度模型。
