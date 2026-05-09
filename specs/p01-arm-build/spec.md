# P01-A Arm 构建 Spec

## 1. Scope

本 SpecKit 任务只覆盖 `P01-A / Arm 构建`。P01-A 的目标是在已知 SWSD / RCSD / F-RCSD 三套数据对应路口 ID 的前提下，分别在三套数据中构建当前语义路口的 Arm，并产出可自动检查与人工目视审查的结果包。

本轮业务需求主源为用户提供的本地需求文档：

```text
/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/RCSD_Topo_Poc__P01__REQUIREMENT.md
```

本轮仓库落地采用 `p01_arm_build` 模块 ID；`P01` 表示 POC 验证模块，目录结构与现有 `T0X` 正式模块保持一致。

## 2. In Scope

- 读取 SWSD / RCSD / F-RCSD 三套 Node 与 Road 基础数据。
- 支持重复传入多个三段式 `--junction-group <swsd>,<rcsd>,<frcsd>`。
- 按输入顺序生成 `group_0001`、`group_0002` 等稳定组 ID。
- 按 `mainnodeid` 组装语义路口：有效 `mainnodeid` 聚合，`null / "" / 0` 作为无效值并退化为单节点语义路口。
- 识别当前路口 internal roads、inbound / outbound / bidirectional seed roads。
- 使用 `formway` bit7 / bit8 识别提前右转、提前左转，并把特殊道路索引写入审计输出。
- 仅在字段明确可识别时排除 legacy 右转专用道 / 渠化右转，并把排除结果写入审计输出。
- 从当前路口 seed road 出发按拓扑追溯，输出 InitialArm。
- `InitialArm` 保留原始 trace 终端归并事实；`FinalArm` 默认等同 `InitialArm`，但当 trace 过度切碎且 `LocalArmCandidate` 完整覆盖时，可采用局部趋势兜底聚合。
- 识别 `trunk_road_ids`，提前左转 road 可在 Arm member 中但不得进入 trunk。
- 提前右转 road 不进入 Arm member / seed / connector / trunk，必须输出 `AdvanceRightTurnRelation` 或 issue。
- 输出 `JunctionContext / InitialArm / FinalArm / AdvanceRightTurnRelation / LocalArmCandidate / ArmTrace / ThroughDecisionAudit / ArmBuildIssueReport`。
- 输出 `LocalArmCandidate` 审计候选：仅基于当前语义路口 seed roads 的局部出入口趋势分组，用于人工判断 trace 过度切碎，并可在完整覆盖时作为 FinalArm 兜底依据。
- 输出 review PNG、compare PNG、review GPKG、summary 与 review index。
- 实现自动结构检查、批量统计检查和人工目视优先级分类。

## 3. Out of Scope

- Arm 配准。
- Movement 空间建模。
- SWSD / RCSD 禁行信息提取。
- 禁行证据投影。
- F-RCSD 通行能力裁决。
- P01-B。
- 复杂 Arm 级兜底合并规则。
- 将局部趋势候选直接固化为正式 Arm 合并结果。
- 基于几何形态反推右转专用道。
- 使用 `grade / grade_2` 作为 Arm 构建规则。
- 新增 repo CLI 子命令、`scripts/` 常驻脚本、模块 `__main__.py` 或模块 `run.py`。

## 4. Core Business Rules

### 4.1 Semantic Junction

路口是语义路口而不是单个 Node 点。对每套数据：

- 若目标 Node 或其同组 Node 存在有效 `mainnodeid`，则所有相同 `mainnodeid` 的 Node 构成当前语义路口。
- `mainnodeid = null / "" / 0` 视为无有效 `mainnodeid`。
- 无有效 `mainnodeid` 时，输入 ID 对应 Node 自身构成单节点语义路口。
- Arm 构建基于当前语义路口成员 Node 集合，而不是只基于代表 Node。

### 4.2 Arm

Arm 是从当前语义路口出发，沿进入 / 退出当前路口的 Road 进行拓扑追溯，最终到达同一个终端语义路口或终端边界的一组道路链。

Arm 不是几何方向聚类、Road heading 聚类、Port、Family、Movement 或全局 Segment。

### 4.3 特殊转向与 Right-Turn Exclusion

P01-A1 v0.3.0 将特殊转向直接并入 Arm 构建，不新增独立阶段。

`formway` 必须先尝试解析为整数，正式特殊转向规则为：

- 提前右转：`(formway & 128) != 0`
- 提前左转：`(formway & 256) != 0`

提前右转 road 不属于任何 Arm 的 `member_road_ids / seed_road_ids / connector_road_ids / trunk_road_ids`。bit7 候选范围包括直接连接当前语义路口 member node 的 road，以及 Arm 非特殊 inbound / bidirectional seed 外侧节点相邻的 bit7 road。连续 bit7 road 链按一条 Arm 级 `AdvanceRightTurnRelation` 输出，链内所有 bit7 road 写入同一条 relation 的 `advance_right_turn_road_ids`。每条当前路口 bit7 road 必须形成 relation，或输出 `target_arm_not_found / ambiguous / patch_boundary / loop` 等 issue。

提前左转 road 可以属于 `member_road_ids`，但必须写入 `advance_left_turn_road_ids`，并从 `trunk_road_ids` 中排除。`JunctionContext.advance_left_turn_road_ids` 只统计已进入 Arm member 的 bit8 road，不把 seed 外侧节点相邻但未进入 Arm 的 bit8 road 计入当前路口提前左转。

当前版本先排除右转专用道 / 渠化右转：

- 只有字段明确可识别时才排除。
- 字段缺失时不通过几何形态反推。
- 被排除 Road 不进入 seed、connector、through 判断或 T 型判断。
- 被排除 Road 必须写入 `excluded_right_turn_road_ids` 与 issue/audit 输出。
- `--right-turn-formway-value` 只作为 legacy 兼容排除参数；bit7 优先于 legacy 参数，不作为 legacy 排除静默丢弃。

### 4.4 Through Decision

through 判断发生在语义节点组 / 语义路口层面，不发生在孤立物理 Node 层面。允许状态固定为：

- `simple_through`
- `t_mainline_through`
- `t_side_terminal`
- `semantic_boundary`
- `ambiguous_boundary`
- `dead_end`
- `patch_boundary`
- `loop_to_current_junction`

允许继续追溯的状态只有 `simple_through` 与 `t_mainline_through`。其余状态必须停止并审计。

Kind 参与追溯停止主口径：

- `kind != 4` 的语义节点组原则上需要继续追溯；但 `dead_end / patch_boundary / loop_to_current_junction` 仍为拓扑硬停止。
- `kind = 2048` 视为明确 T 型路口，必须结合当前追溯方向判断横向主通道与竖向侧支：横向主通道输出 `t_mainline_through` 并继续，竖向侧支输出 `t_side_terminal` 并停止。
- `kind = 4` 不立即停止，必须先评估实际拓扑是否符合 T 型路口特征；若符合 T 型则按 T 型规则裁决，若不符合则输出 `semantic_boundary` 并停止。

T 型判断必须结合当前追溯方向、拓扑结构和候选 continuation 的方向关系。`grade / grade_2` 禁止进入主规则。

## 5. Inputs

模块 runner 参数形态：

```text
--swsd-nodes
--swsd-roads
--rcsd-nodes
--rcsd-roads
--frcsd-nodes
--frcsd-roads
--junction-group <swsd_junction_id>,<rcsd_junction_id>,<frcsd_junction_id>
--out-root
--run-id
--right-turn-formway-value
```

`--run-id` 可选；缺失时自动生成并写入 summary。
`--right-turn-formway-value` 可重复传入，用于声明 legacy 右转专用道 / 渠化右转的 `formway` 字段值；未传入时不得仅凭几何或示例值排除 Road。bit7 / bit8 特殊转向不依赖该参数。

输入文件支持 Fiona 可读取的矢量数据源。Node 至少需要 `id / mainnodeid / geometry`，`kind` 可选；Road 至少需要 `id / snodeid / enodeid / direction / geometry`，`formway` 可选。

## 6. Outputs

输出根目录为：

```text
<out-root>/<run-id>/
```

本轮仓库落地使用 `cases/<junction_group_id>/` 作为 case 目录，保留三套原始路口 ID：

```text
preflight.json
p01_arm_build_summary.json
p01_arm_build_review_index.csv
cases/group_0001/case_input.json
cases/group_0001/case_summary.json
cases/group_0001/SWSD/junction_context.json
cases/group_0001/SWSD/initial_arms.json
cases/group_0001/SWSD/final_arms.json
cases/group_0001/SWSD/advance_right_turn_relations.json
cases/group_0001/SWSD/local_arm_candidates.json
cases/group_0001/SWSD/arm_traces.json
cases/group_0001/SWSD/through_decisions.json
cases/group_0001/SWSD/issue_report.json
cases/group_0001/SWSD/review_layers.gpkg
cases/group_0001/SWSD/p01_arm_review.png
cases/group_0001/RCSD/...
cases/group_0001/FRCSD/...
cases/group_0001/compare/p01_arm_compare.png
cases/group_0001/compare/p01_arm_compare_summary.json
cases/group_0001/compare/p01_arm_compare_layers.gpkg
```

## 7. Required Business Objects

### JunctionContext

至少包含：

- `dataset`
- `junction_id`
- `member_node_ids`
- `internal_road_ids`
- `inbound_seed_road_ids`
- `outbound_seed_road_ids`
- `bidirectional_seed_road_ids`
- `excluded_right_turn_road_ids`
- `advance_left_turn_road_ids`
- `advance_right_turn_road_ids`
- `formway_missing_road_ids`
- `formway_unparseable_road_ids`
- `special_formway_issue_flags`
- `input_issue_flags`

### InitialArm

至少包含：

- `dataset`
- `current_junction_id`
- `initial_arm_id`
- `terminal_type`
- `terminal_junction_id`
- `terminal_member_node_ids`
- `member_road_ids`
- `seed_road_ids`
- `connector_road_ids`
- `inbound_member_road_ids`
- `outbound_member_road_ids`
- `bidirectional_member_road_ids`
- `build_status`
- `risk_flags`
- `has_advance_left_turn`
- `advance_left_turn_road_ids`
- `trunk_road_ids`
- `trunk_status`
- `trunk_reason`
- `non_trunk_member_road_ids`
- `has_inbound_advance_right_turn`
- `advance_right_turn_relation_ids`
- `advance_right_turn_target_arm_ids`

### FinalArm

当前版本 `FinalArm` 默认与 `InitialArm` 一一对应；当 `LocalArmCandidate` 完整覆盖全部 `InitialArm` 且存在 trace 碎片化时，允许按局部趋势兜底聚合。

- `final_arm_id`
- `source_initial_arm_ids`
- `merge_status`
- `merge_reason`
- `has_advance_left_turn`
- `advance_left_turn_road_ids`
- `trunk_road_ids`
- `trunk_status`
- `trunk_reason`
- `non_trunk_member_road_ids`
- `has_inbound_advance_right_turn`
- `advance_right_turn_relation_ids`
- `advance_right_turn_target_arm_ids`

当前允许 `merge_status`：

- `not_applied`
- `local_candidate_fallback`

### AdvanceRightTurnRelation

至少包含：

- `relation_id`
- `dataset`
- `current_junction_id`
- `from_arm_id`
- `from_inbound_road_ids`
- `advance_right_turn_road_ids`
- `to_arm_id`
- `to_outbound_road_ids`
- `trace_road_ids`
- `trace_node_ids`
- `trace_status`
- `trace_reason`
- `confidence`
- `risk_flags`

### LocalArmCandidate

`LocalArmCandidate` 是审计候选，不是正式 Arm 输出。它只基于当前语义路口 seed road 从 member node 指向外侧 node 的局部趋势角，把同侧进入 / 退出 / 双向 seed 汇总成参考分组；可额外保留少量方向一致的外侧 stub road 作为趋势证据。

至少包含：

- `dataset`
- `current_junction_id`
- `local_arm_candidate_id`
- `source_seed_road_ids`
- `source_initial_arm_ids`
- `local_stub_road_ids`
- `inbound_seed_road_ids`
- `outbound_seed_road_ids`
- `bidirectional_seed_road_ids`
- `member_node_ids`
- `trend_angle_deg`
- `angular_spread_deg`
- `grouping_reason`
- `build_status`
- `risk_flags`

### ArmTrace

每条 seed road 一条 trace，至少包含：

- `dataset`
- `current_junction_id`
- `trace_id`
- `seed_road_id`
- `seed_role`
- `traced_road_ids`
- `traced_node_ids`
- `through_decisions`
- `stop_type`
- `stop_reason`
- `assigned_initial_arm_id`
- `issue_flags`

### ThroughDecisionAudit

必须输出业务状态，不得只输出 true / false。

### ArmBuildIssueReport

至少覆盖：

- `junction_member_nodes_not_found`
- `seed_road_missing`
- `all_seed_roads_excluded`
- `seed_road_unassigned`
- `road_assigned_to_multiple_arms`
- `ambiguous_boundary`
- `patch_boundary`
- `loop_to_current_junction`
- `t_junction_uncertain`
- `kind_topology_conflict`
- `right_turn_field_missing`
- `formway_missing`
- `formway_unparseable`
- `advance_right_turn_target_arm_not_found`
- `advance_right_turn_ambiguous`
- `advance_right_turn_patch_boundary`
- `advance_right_turn_loop`
- `advance_right_turn_in_arm_member_error`
- `advance_left_turn_in_trunk_error`
- `trunk_min_loop_not_found`
- `trunk_min_loop_ambiguous`
- `rcsd_structure_incomplete`
- `frcsd_structure_incomplete`

## 8. Acceptance Criteria

- 能读取三套 Node / Road 基础数据。
- 能处理多个 `--junction-group`。
- 每组分别输出 SWSD / RCSD / FRCSD Arm 构建结果。
- 每条 seed road 有归属或明确 issue。
- 每个 through 判断有可审计状态。
- 输出 JSON / PNG / GPKG / summary / review index。
- 输出 `advance_right_turn_relations.json`，每条 bit7 road 有 relation 或明确 issue。
- `InitialArm / FinalArm` 输出提前左转、提前右转 relation 与 trunk 字段。
- 自动检查能发现关键异常。
- 代码中不使用 `grade / grade_2` 参与 Arm 构建主规则。
- 完成 py_compile、单元测试、synthetic case、多 junction-group、输出结构、PNG/GPKG 存在性与审计检查。

## 9. P01-A1 v0.4.0 RoadNextRoad-aware ArmMovement 与 Trunk 修正

本节已由 v0.5.0 扩展为 A1 + P01-Final 范围，不新增独立阶段，不实现 A2 新业务扩展 / A3 / P01-B。

- A1 runner 新增可选 `--swsd-road-next-road / --rcsd-road-next-road / --frcsd-road-next-road`。
- RoadNextRoad 归一化为 `RoadMovementEvidence`，只表达 allowed evidence；缺失只表示 `no_allowed_evidence`，不得解释为 prohibited。
- `turnType / turntype` 只保留到 `raw_turn_type` 与审计 summary，禁止用于 `movement_type` 判定。
- 每套数据每个路口输出全量 `from_final_arm x to_final_arm` ArmMovement。
- `movement_type` 支持 `straight / left / right / uturn / unknown`，按 same-arm、唯一 stable straight target、trunk / LocalArmCandidate 主交通流连续性、RoadNextRoad trunk evidence 与相对左右侧判定。
- 输出 `arm_movements.json / road_movement_evidence.json / arm_receiving_road_roles.json / trunk_corrections.json / corrected_final_arms.json`。
- corrected trunk 只允许排除 advance-left-only receiving road；目标 Arm 无 straight receiving evidence 时不得排除，必须输出 `straight_evidence_missing`。
- review GPKG 增加 movement、evidence、receiving road、movement-excluded trunk 和 corrected trunk 图层。

## 10. P01-Final v0.5.0 F-RCSD RoadNextRoad 还原

本轮在 A1 runner 内输出 P01-Final 产物，不新增正式 CLI。

- 读取 F-RCSD:Road `Source` 字段，`1 = RCSD`，`2 = SWSD`。
- 使用 `Source + 几何完全一致` 建立 F-RCSD Road 到源 Road 的映射。
- Source 异常、source geometry missing、ambiguous source geometry match 均进入 issue，不参与静默生成。
- 基于 SWSD / RCSD RoadNextRoad evidence 构建 SourceMovementPolicy。
- 同源 F-RCSD road pair 直接继承源 RoadNextRoad；源侧 RoadNextRoad 缺失则不生成。
- 不同源 road pair 以进入 road 的 Source 为 primary source，使用 primary source role-level policy 生成。
- 当前唯一 fallback：`from Source = 1`、`to Source = 2`、RCSD 无 policy 且 SWSD 有 policy；生成前必须检查 entering arm road count。
- 输出 `frcsd_road_next_road.geojson / frcsd_source_road_map.json / source_movement_policy_swsd.json / source_movement_policy_rcsd.json / frcsd_road_next_road_audit.json / frcsd_road_next_road_issue_report.json`。
- 最终 `turntype` 输出映射为 `unknown=0 / straight=1 / left=2 / right=3 / uturn=4`，该映射不得用于 movement_type 输入判断。
