# Data Model: T12 FRCSD 质量审计

## 1. AuditRun

| 字段 | 类型 | 约束 / 含义 |
|---|---|---|
| `schema_version` | string | 固定契约版本。 |
| `run_id` | string | 输出根内唯一，不包含路径分隔符。 |
| `status` | enum | `passed / blocked / failed`。 |
| `started_at_utc / ended_at_utc` | datetime | UTC ISO-8601。 |
| `elapsed_seconds` | number | 总耗时。 |
| `stage_elapsed_seconds` | object | loading/index/graph/candidate/review/output 分段耗时。 |
| `inputs` | object | 每个输入的路径、SHA-256、size、layer、CRS、feature count。 |
| `parameters` | object | 所有容差与开关。 |
| `runtime` | object | Python、platform、dependency versions。 |
| `silent_fix` | boolean | 固定为 `false`。 |

状态转换：`created -> running -> passed|blocked|failed`。任何 CRS、contract 或 target identity 阻断都不能写成 `passed`。

## 2. TargetManifest

| 字段 | 类型 | 含义 |
|---|---|---|
| `frcsd_roads_sha256 / frcsd_nodes_sha256` | string | 原始 1V1 FRCSD target 身份。 |
| `t06_evidence_root` | path | 兼容 T06 run root。 |
| `t06_input_roads / t06_input_nodes` | path | T06 summary 声明的 T05 copy-on-write 输入。 |
| `evidence_relation` | enum | `derived_copy_on_write / unverified_legacy / wrong_batch`。 |
| `t05_run_identity` | string/object | T05 anchor audit 与 T06 input path 的同批次派生证据。 |

`wrong_batch` 必须阻断；`unverified_legacy` 只允许显式 legacy compatibility 模式并记录风险。禁止用原始 FRCSD 与 T05 copy-on-write 文件指纹不相同作为阻断理由。

## 3. SegmentRequirement

| 字段 | 类型 | 含义 |
|---|---|---|
| `segment_id` | string | T01 Segment ID。 |
| `pair_nodes` | list[string] | 两端 SWSD 语义节点，必须 distinct。 |
| `swsd_road_ids` | list[string] | Segment 内 Road。 |
| `required_directions` | list[enum] | `pair0_to_pair1 / pair1_to_pair0`。 |
| `segment_geometry` | geometry | 处理 CRS 下参考 corridor 中心线。 |
| `is_crop_edge` | boolean | 是否位于显式裁剪边界审计区。 |

## 4. AnchorGroup

| 字段 | 类型 | 含义 |
|---|---|---|
| `swsd_node_id` | string | SWSD 语义路口。 |
| `source_module` | string | T05 audit 的来源模块，T07 表示 RCSDIntersection 真值链。 |
| `base_node_id` | string | selected/main FRCSD node。 |
| `member_node_ids` | list[string] | T05 grouped nodes 与 FRCSD main/subnode 展平集合。 |
| `start_portals / end_portals` | list[Portal] | 按出边/入边资格筛选的 portal。 |

## 5. Portal

| 字段 | 类型 | 含义 |
|---|---|---|
| `raw_node_id` | string | 原始 FRCSD node。 |
| `canonical_node_id` | string | graph canonical ID。 |
| `distance_m` | number | 到 SWSD 方向端点的距离。 |
| `source` | enum | `truth_group / grouped_relation / spatial_portal`。 |
| `direction_role` | enum | `start / end`。 |

## 6. CarrierEvidence

| 字段 | 类型 | 含义 |
|---|---|---|
| `segment_id / direction` | string | 所属 Segment 与必需方向。 |
| `path_kind` | enum | `local_directed / full_directed / local_undirected / full_undirected`。 |
| `exists` | boolean | 是否存在路径。 |
| `start_portal / end_portal` | string | 实际命中的 canonical portal。 |
| `road_ids` | list[string] | 有序 FRCSD Road ID。 |
| `length_m / length_ratio` | number/null | 路径长度及相对 SWSD 长度。 |
| `max_corridor_distance_m` | number/null | 对 SWSD Segment 最大采样偏离。 |
| `accepted_equivalent_carrier` | boolean | 是否满足审计阈值。 |

## 7. QualityCandidate

| 字段 | 类型 | 含义 |
|---|---|---|
| `candidate_id` | string | 默认 `segment_id`；同 Segment 多类型时扩展为稳定复合键。 |
| `candidate_status` | enum | 固定 `candidate_pending_review`。 |
| `suggested_issue_type` | enum | `directed_carrier_missing / required_local_connectivity_missing`。 |
| `required_directions` | list[string] | SWSD 要求方向。 |
| `failed_directions` | list[string] | 缺少等价 carrier 的方向。 |
| `anchor_groups / carrier_evidence` | object/list | 完整复核证据。 |
| `t06_cross_evidence` | object | T06 Step2/Step3 解释，不改变 target 事实。 |
| `review_status` | enum | 初始 `manual_review_required`。 |

禁止字段：`confidence / probability / high / medium`。

## 8. ReviewDecision

| 字段 | 类型 | 约束 / 含义 |
|---|---|---|
| `run_id` | string | 必须匹配候选 AuditRun。 |
| `candidate_id` | string | 必须存在且唯一。 |
| `review_status` | enum | `confirmed_frcsd_quality_issue / excluded_false_positive / manual_review_required`。 |
| `issue_type` | string | confirmed 时必填。 |
| `review_reason` | string | confirmed/excluded 时必填。 |
| `review_source` | string | 人工、任务或外部治理来源。 |
| `reviewed_at_utc` | datetime/null | 可追溯时间。 |

## 9. ConfirmedQualityIssue

由 `QualityCandidate + ReviewDecision` 生成。只允许 `review_status=confirmed_frcsd_quality_issue`。保留全部候选证据和复核信息，不包含概率等级。
