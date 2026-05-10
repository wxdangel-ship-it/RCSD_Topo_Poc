# P01 Arm Build 接口契约

## 1. 模块定位

`p01_arm_build` 是 P01 POC 验证模块，当前覆盖 `P01-A1 / Arm 构建`、`P01-A2 / Arm 配准与 LogicalArmGroup 构建` 与 `P01-Final / F-RCSD RoadNextRoad 还原`。A1 在 SWSD / RCSD / F-RCSD 三套数据中分别构建当前语义路口 Arm；A2 读取 A1 run root，以 F-RCSD FinalArm 为目标承载体建立跨三源 LogicalArmGroup；P01-Final 在 A1 RoadNextRoad-aware 输出基础上生成最终 F-RCSD RoadNextRoad。

## 2. 当前入口状态

本轮不新增仓库正式 CLI、`scripts/` 常驻脚本、模块 `__main__.py` 或模块 `run.py`。

当前可调用 runner：

```python
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args

exit_code = run_p01_arm_build_from_args([
    "--swsd-nodes", "...",
    "--swsd-roads", "...",
    "--rcsd-nodes", "...",
    "--rcsd-roads", "...",
    "--frcsd-nodes", "...",
    "--frcsd-roads", "...",
    "--junction-group", "724067,R724067,F724067",
    "--out-root", "outputs/_work/p01_arm_build",
    "--right-turn-formway-value", "128",
])
```

该调用面不登记为当前仓库正式执行入口；后续如需正式 CLI，必须同步更新入口注册表、CLI、README 与本契约。

当前还提供 A2 Arm 配准 callable runner：

```python
from rcsd_topo_poc.modules.p01_arm_build.alignment_runner import run_p01_arm_alignment_from_args

exit_code = run_p01_arm_alignment_from_args([
    "--arm-build-run-root", "outputs/_work/p01_arm_build/<run-id>",
    "--out-root", "outputs/_work/p01_arm_alignment",
])
```

该调用面同样不登记为当前仓库正式执行入口；它只能消费 A1 run root，不重新要求用户传入六类 Node / Road 基础路径。

当前还提供单路口文本证据包 dev helper，用于外部复现与内网 case 取证，不登记为正式 CLI：

```python
from rcsd_topo_poc.modules.p01_arm_build.text_bundle import (
    run_p01_decode_text_bundle_from_args,
    run_p01_export_text_bundle_from_args,
)
```

打包和解包均可通过 `python -c` 单命令调用。helper 使用 `zip + base85 + checksum` 文本包装，默认单文件上限 `250 KiB`；上下文选择基于当前语义路口 Road 拓扑 BFS，不做简单空间裁剪。打包支持 `--auto-fit --max-bfs-depth N`。若选定范围无法放入单个 250 KiB 文本文件，helper 会自动拆分为多个文本分片；分片合并后仍包含 SWSD / RCSD / F-RCSD 三套数据。helper 可选带入 SWSD `RoadNodeRoad` / `RoadNextRoad` 与 RCSD `RoadNextRoad`，按已选 BFS road 集合筛选关联记录后随包输出。

当前还提供单 Case 全量执行 dev helper，不登记为正式 CLI：

```bash
bash modules/p01_arm_build/dev_helpers/run_p01_case_full.sh
```

该脚本支持 `CASE_ROOT=<decoded-case-dir>` 直接执行，也支持 `BUNDLE_TXT=<bundle.txt>` 先解包后执行；脚本自动识别已解包目录中的 `SWSD/RoadNodeRoad.json`、`SWSD/RoadNextRoad.json`、`RCSD/RoadNextRoad.geojson` 与 `FRCSD/RoadNextRoad.geojson` 并传入 A1 runner。

## 3. 输入契约

### 3.1 数据路径

- `--swsd-nodes`
- `--swsd-roads`
- `--rcsd-nodes`
- `--rcsd-roads`
- `--frcsd-nodes`
- `--frcsd-roads`

输入使用 WSL 路径。支持 Fiona 可读取的矢量格式。

### 3.2 Junction Group

参数形式：

```text
--junction-group <swsd_junction_id>,<rcsd_junction_id>,<frcsd_junction_id>
```

可重复传入多组。系统按输入顺序生成 `group_0001`、`group_0002` 等内部 ID，并在输出中保留原始三套路口 ID。

### 3.3 输出路径

- `--out-root`
- `--run-id`：可选，缺失时自动生成。
- `--right-turn-formway-value`：可选，可重复传入；仅作为 legacy 兼容排除口径，用于声明已确认能表达右转专用道 / 渠化右转的 `formway` 字段值。P01-A1 正式特殊转向识别优先使用 bit 运算：`bit7 = 128` 为提前右转，`bit8 = 256` 为提前左转。bit7 road 不按 legacy 参数静默进入 `excluded_right_turn_road_ids`，必须进入 `AdvanceRightTurnRelation` 或 issue。
- `--swsd-road-next-road`：可选；SWSD RoadNextRoad JSON / GeoJSON。
- `--rcsd-road-next-road`：可选；RCSD RoadNextRoad GeoJSON / JSON。
- `--frcsd-road-next-road`：可选；F-RCSD RoadNextRoad GeoJSON / JSON，仅用于 A1 同源 ArmMovement evidence 审计；最终 F-RCSD RoadNextRoad 仍由 P01-Final 生成。

### 3.4 最小字段

Node 最少字段：

- `id`
- `mainnodeid`
- `geometry`

可选字段：

- `kind`

`kind` 参与 P01-A 追溯停止主口径：非 `4` 类型原则上继续追溯；`2048` 作为明确 T 型路口按当前追溯方向裁决横向主通道 through 与竖向侧支 terminal；`4` 需要先评估实际拓扑是否符合 T 型特征，不符合时作为语义边界停止。

Road 最少字段：

- `id`
- `snodeid`
- `enodeid`
- `direction`
- `geometry`

可选字段：

- `formway`

`grade / grade_2` 禁止进入 Arm 构建主规则。

### 3.5 文本证据包 helper 参数

打包 helper 参数：

- `--swsd-nodes`
- `--swsd-roads`
- `--rcsd-nodes`
- `--rcsd-roads`
- `--frcsd-nodes`
- `--frcsd-roads`
- `--swsd-road-node-road`：可选；SWSD `RoadNodeRoad.json`，按已选 SWSD BFS road 过滤后写入 `SWSD/RoadNodeRoad.json`
- `--swsd-road-next-road`：可选；SWSD `RoadNextRoad.json` / GeoJSON，按已选 SWSD BFS road 过滤后写入 `SWSD/RoadNextRoad.json`
- `--rcsd-road-next-road`：可选；RCSD `RoadNextRoad.geojson` / JSON，按已选 RCSD BFS road 过滤后写入 `RCSD/RoadNextRoad.geojson`
- `--junction-group <swsd_junction_id>,<rcsd_junction_id>,<frcsd_junction_id>`
- `--out-txt`
- `--bfs-depth`：默认 `2`
- `--auto-fit`：可选；启用后从 `--bfs-depth` 起逐圈尝试到 `--max-bfs-depth`
- `--max-bfs-depth`：默认 `8`
- `--max-text-size-bytes`：默认 `256000`

`--junction-group` 输出中保留原始输入 ID。解析时先按原始 ID 精确匹配；若 RCSD 精确匹配失败且 ID 以 `R` 开头，再尝试去掉首字母 `R`；若 F-RCSD 精确匹配失败且 ID 以 `F` 开头，再尝试去掉首字母 `F`。该兜底只用于参数前缀兼容，不改变数据集内 Node / Road ID。

解包 helper 参数：

- `--bundle-txt`
- `--out-dir`

`--bundle-txt` 可指向单文件 bundle，也可指向任一 split 分片。split 分片必须保留在同一目录下，解包时会按分片元数据自动合并。

解包输出：

- `manifest.json`
- `size_report.json`
- `SWSD/nodes.gpkg`
- `SWSD/roads.gpkg`
- `SWSD/RoadNodeRoad.json`：仅当打包时提供 `--swsd-road-node-road`
- `SWSD/RoadNextRoad.json`：仅当打包时提供 `--swsd-road-next-road`
- `RCSD/nodes.gpkg`
- `RCSD/roads.gpkg`
- `RCSD/RoadNextRoad.geojson`：仅当打包时提供 `--rcsd-road-next-road`
- `FRCSD/nodes.gpkg`
- `FRCSD/roads.gpkg`

单 Case 全量执行 helper 环境变量：

- `CASE_ROOT`：已解包 case 目录；若传入 `BUNDLE_TXT` 可省略。
- `BUNDLE_TXT`：可选；文本证据包或任一 split 分片，脚本会先解包到 `CASE_ROOT` 或同目录默认目录。
- `JUNCTION_GROUP` / `JUNCTION_GROUPS`：可选；缺省时从 `manifest.json` 的 `junction_group` 读取。`JUNCTION_GROUPS` 多组用分号或换行分隔。
- `OUT_ROOT` / `RUN_ID`：输出目录与 run id。
- `SWSD_ROAD_NODE_ROAD`、`SWSD_ROAD_NEXT_ROAD`、`RCSD_ROAD_NEXT_ROAD`、`FRCSD_ROAD_NEXT_ROAD`：可选覆盖自动识别的 RoadNextRoad 输入。
- `RIGHT_TURN_FORMWAY_VALUE`：可选 legacy 兼容值，多值用逗号分隔。

## 4. 业务对象契约

### 4.1 JunctionContext

字段：

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

### 4.2 InitialArm

字段：

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

### 4.3 FinalArm

`InitialArm` 始终保留原始 trace 终端归并事实。`FinalArm` 默认与 `InitialArm` 一一对应；当 `InitialArm` 被局部 trace boundary 过度切碎，且 `LocalArmCandidate` 完整覆盖全部 `InitialArm` 时，`FinalArm` 可采用局部趋势兜底聚合。

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

当前允许的 `merge_status`：

- `not_applied`
- `local_candidate_fallback`

`FinalArm` 的特殊转向、trunk 与提前右转关系字段必须由来源 `InitialArm` 聚合；local fallback 合并不得丢失来源 Arm 的这些审计字段。

### 4.3.1 AdvanceRightTurnRelation

`AdvanceRightTurnRelation` 表达某个 Arm 的进入方向经 bit7 提前右转道路关联到同一路口另一个 Arm 的退出方向。当前路口 bit7 候选包括直接连接 current member nodes 的 bit7 road，以及 Arm 非特殊 inbound / bidirectional seed 外侧节点相邻的 bit7 road。连续 bit7 road 链归并为一条 Arm 级 relation，链内所有 bit7 road 写入同一个 `advance_right_turn_road_ids`；每条当前路口 bit7 road 必须进入一条 relation 或明确 issue。

`JunctionContext.advance_left_turn_road_ids` 只记录已经进入 Arm member 的 bit8 road；seed 外侧节点相邻但未进入 Arm 的 bit8 road 不计为当前路口提前左转。

字段：

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

允许 `trace_status`：

- `resolved`
- `partial`
- `ambiguous`
- `target_arm_not_found`
- `loop`
- `patch_boundary`

### 4.4 LocalArmCandidate

`LocalArmCandidate` 是局部趋势审计候选，不是正式 Arm 合并结果。它只从当前语义路口的 seed roads 出发，把从 member node 指向外侧 node 的局部趋势相近的进入 / 退出 / 双向 seed 归为一组，并保留少量方向一致的外侧 stub road 作为目视参考。

字段：

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

该对象用于定位 `InitialArm` 可能被 trace boundary 过度切碎的 case；当其完整覆盖全部 `InitialArm` 时，可作为 `FinalArm` 的兜底聚合依据。

### 4.5 ArmTrace

字段：

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
- `advance_left_turn_road_ids_in_trace`
- `advance_right_turn_road_ids_adjacent`
- `trunk_candidate_road_ids`

### 4.6 ThroughDecisionAudit

允许状态：

- `simple_through`
- `t_mainline_through`
- `t_side_terminal`
- `semantic_boundary`
- `ambiguous_boundary`
- `dead_end`
- `patch_boundary`
- `loop_to_current_junction`

through 裁决必须记录业务状态，不得只输出 true / false。当前口径为：

- `kind != 4`：原则继续追溯；拓扑不可继续、缺失或回到当前路口时仍硬停。
- `kind = 2048`：T 型路口，横向主通道 `t_mainline_through`，竖向侧支 `t_side_terminal`。
- `kind = 4`：先判断是否具备 T 型特征；具备时按 T 型规则，不具备时 `semantic_boundary`。
- T 型判断必须结合当前 incoming road 与候选 outgoing road 的方向关系，不能稳定确认时输出 `ambiguous_boundary` 并审计。

### 4.7 IssueReport

典型 issue：

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

## 5. 输出契约

输出目录：

```text
<out-root>/<run-id>/
```

核心文件：

- `preflight.json`
- `p01_arm_build_summary.json`
- `p01_arm_build_review_index.csv`
- `cases/<group_id>/case_input.json`
- `cases/<group_id>/case_summary.json`
- `cases/<group_id>/<dataset>/junction_context.json`
- `cases/<group_id>/<dataset>/initial_arms.json`
- `cases/<group_id>/<dataset>/final_arms.json`
- `cases/<group_id>/<dataset>/advance_right_turn_relations.json`
- `cases/<group_id>/<dataset>/local_arm_candidates.json`
- `cases/<group_id>/<dataset>/arm_traces.json`
- `cases/<group_id>/<dataset>/through_decisions.json`
- `cases/<group_id>/<dataset>/issue_report.json`
- `cases/<group_id>/<dataset>/review_layers.gpkg`
- `cases/<group_id>/<dataset>/p01_arm_review.png`
- `cases/<group_id>/compare/p01_arm_compare.png`
- `cases/<group_id>/compare/p01_arm_compare_summary.json`
- `cases/<group_id>/compare/p01_arm_compare_layers.gpkg`

`review_layers.gpkg` 至少包含以下 A1 审查图层：

- `current_junction_nodes`
- `current_junction_internal_roads`
- `arm_roads`
- `arm_trunk_roads`
- `local_arm_candidate_roads`
- `arm_traces`
- `terminal_nodes`
- `through_decision_nodes`
- `excluded_right_turn_roads`
- `advance_left_turn_roads`
- `advance_right_turn_roads`
- `advance_right_turn_relations`
- `special_formway_issue_points`
- `issue_points`

`p01_arm_build_review_index.csv` 与 summary 必须统计提前左转、提前右转 relation、trunk 状态、formway 缺失和不可解析数量。

trunk 识别优先寻找进入 / 退出最小闭环；无法形成闭环时，退回到 Arm 的非特殊 seed 局部主干并输出 `trunk_status = partial`，不得把 bit7 提前右转或 bit8 提前左转写入 trunk。

## 9. P01-A1 / P01-Final v0.5.0 RoadNextRoad-aware ArmMovement 与 F-RCSD RoadNextRoad 还原

本轮属于 P01-A1 修订与 P01-Final 还原，不新增正式 CLI，不实现 A2 新业务扩展、A3 或 P01-B。

### 9.1 新增可选输入

runner 继续保持既有 Node / Road / junction-group 输入，并新增可选参数：

- `--swsd-road-next-road`
- `--rcsd-road-next-road`
- `--frcsd-road-next-road`

输入可为 SWSD `RoadNextRoad.json` / `RoadNodeRoad.json`、RCSD / F-RCSD `RoadNextRoad.geojson` 或同类 JSON / GeoJSON 结构。未提供某源 RoadNextRoad 时，该源 A1 movement evidence 输出为空，trunk correction 输出 `not_evaluated_no_road_next_road_input`。P01-Final 最终产物不复制输入 F-RCSD RoadNextRoad，而是输出新生成的 `frcsd_road_next_road.geojson`。

### 9.2 RoadMovementEvidence

RoadNextRoad 只表达 `road_id -> next_road_id` 的 allowed evidence；缺失不得解释为禁止。归一化字段：

- `evidence_id`
- `dataset`
- `current_junction_id`
- `raw_id`
- `road_id`
- `next_road_id`
- `raw_type`
- `raw_turn_type`
- `source`
- `raw_properties`
- `from_arm_id`
- `to_arm_id`
- `from_road_role`
- `to_road_role`
- `mapping_status`
- `issue_flags`

`turnType / turntype` 只写入 `raw_turn_type` 和 movement 的 `turn_type_summary`，不得用于 `movement_type` 判定。

### 9.3 ArmMovement

每个同源路口生成 `from_final_arm x to_final_arm` 全量候选，输出 `arm_movements.json`。`permission_evidence_status` 至少支持：

- `allowed_supported`
- `no_allowed_evidence`
- `mapping_unresolved`
- `role_conflict`
- `out_of_scope`

`movement_type` 至少支持 `straight / left / right / uturn / unknown`，按 same-arm、主交通流 / trunk / local candidate 连续性、相对左右侧和 evidence 充足度判定；不得使用 RoadNextRoad 原始转向编码判定。

ArmMovement 还输出：

- `post_shape_label`
- `straight_target_status`
- `straight_target_evidence`

`post_shape_label` 只能作为后验审计解释，不能作为 movement_type 判定输入。trunk correction 中的 straight receiving evidence 只来自 `movement_type = straight`、`straight_target_status = unique_straight_target` 且 `movement_type_confidence = high / stable` 的 stable straight movement。

### 9.4 Receiving Role 与 Corrected Trunk

输出：

- `road_movement_evidence.json`
- `arm_receiving_road_roles.json`
- `trunk_corrections.json`
- `corrected_final_arms.json`

只有当某 target Arm road 被 advance-left left movement 接入、该 target Arm 存在非空 straight receiving evidence、且该 road 不在 straight receiving 集合中时，才允许从 corrected trunk candidate 排除。无 straight receiving evidence 时不得排除，只输出 `straight_evidence_missing`。

review GPKG 新增或增强图层：

- `arm_movements`
- `road_movement_evidence`
- `straight_receiving_roads`
- `advance_left_receiving_roads`
- `trunk_excluded_by_movement_roads`
- `corrected_trunk_roads`

### 9.5 P01-Final F-RCSD RoadNextRoad 输出

每个 case 的 FRCSD 目录新增：

- `frcsd_road_next_road.geojson`
- `frcsd_source_road_map.json`
- `source_movement_policy_swsd.json`
- `source_movement_policy_rcsd.json`
- `frcsd_road_next_road_audit.json`
- `frcsd_road_next_road_issue_report.json`
- `frcsd_road_next_road_review_layers.gpkg`
- `frcsd_road_next_road_review.png`

F-RCSD source road mapping 规则：

- `F-RCSD:Road.Source = 1` 只在 RCSD:Road 中做几何完全一致匹配。
- `F-RCSD:Road.Source = 2` 只在 SWSD:Road 中做几何完全一致匹配。
- Source 缺失、非法、几何匹配缺失或多匹配不得静默生成 RoadNextRoad，必须写入 issue。
- 不允许仅凭空间接近、方向相似或名称相似做强匹配。

最终生成规则：

- 同源 F-RCSD road pair 直接继承源 RoadNextRoad；源侧 RoadNextRoad 缺失则不生成。
- 不同源 road pair 以进入 road 的 `Source` 为 primary source，并使用 primary source 的 role-level `SourceMovementPolicy` 判断是否生成。
- 当前唯一 fallback 是 `from_road.Source = 1`、`to_road.Source = 2`、RCSD 无对应 policy 且 SWSD 有对应 policy；执行前必须检查 entering arm road count，一致才允许使用 SWSD policy。
- 最终生成阶段中源 RoadNextRoad 缺失表示不生成 F-RCSD RoadNextRoad；这不改变 A1 ArmMovement 阶段 `no_allowed_evidence != prohibited` 的语义。

`frcsd_road_next_road.geojson` 为 FeatureCollection，Feature `geometry = null`，properties 至少包含：

- `id`
- `road_id`
- `next_road_id`
- `type`
- `source`
- `turntype`
- `city_code`

当前模块冻结内部输出映射：`unknown -> 0`、`straight -> 1`、`left -> 2`、`right -> 3`、`uturn -> 4`。该映射只用于最终 GeoJSON `turntype` 输出，不得用于 movement_type 反向判断。

### 5.2 A2 Arm 配准输出

A2 输出目录：

```text
<out-root>/<run-id>/
```

核心文件：

- `preflight.json`
- `p01_arm_alignment_summary.json`
- `p01_arm_alignment_review_index.csv`
- `cases/<group_id>/arm_profiles.json`
- `cases/<group_id>/alignment_summary.json`
- `cases/<group_id>/logical_arm_groups.json`
- `cases/<group_id>/arm_build_feedback.json`
- `cases/<group_id>/source_extra_arms.json`
- `cases/<group_id>/arm_alignment_candidates.json`
- `cases/<group_id>/SWSD/raw_arm_alignment.json`
- `cases/<group_id>/SWSD/arm_alignment_issue_report.json`
- `cases/<group_id>/SWSD/arm_alignment_review_layers.gpkg`
- `cases/<group_id>/SWSD/p01_arm_alignment_review.png`
- `cases/<group_id>/RCSD/raw_arm_alignment.json`
- `cases/<group_id>/RCSD/arm_alignment_issue_report.json`
- `cases/<group_id>/RCSD/arm_alignment_review_layers.gpkg`
- `cases/<group_id>/RCSD/p01_arm_alignment_review.png`
- `cases/<group_id>/compare/p01_arm_alignment_compare.png`
- `cases/<group_id>/compare/p01_arm_alignment_compare_layers.gpkg`
- `cases/<group_id>/compare/p01_arm_alignment_compare_summary.json`

## 6. A2 业务对象契约

### 6.1 ArmProfile

ArmProfile 从 A1 `FinalArm` 归一化得到，A2 配准主对象仍是 FinalArm，InitialArm / LocalArmCandidate / ArmTrace / ThroughDecisionAudit 是证据来源。

字段：

- `dataset`
- `junction_group_id`
- `current_junction_id`
- `arm_id`
- `source_final_arm_id`
- `source_initial_arm_ids`
- `member_road_ids`
- `seed_road_ids`
- `connector_road_ids`
- `inbound_seed_road_ids`
- `outbound_seed_road_ids`
- `bidirectional_seed_road_ids`
- `terminal_type`
- `terminal_junction_id`
- `terminal_member_node_ids`
- `build_status`
- `risk_flags`
- `merge_status`
- `merge_reason`
- `local_candidate_ids`
- `local_trend_angle_deg`
- `local_stub_road_ids`
- `trace_ids`
- `trace_stop_types`
- `through_decision_summary`
- `geometry_summary`
- `lineage_summary`

### 6.2 ArmAlignmentCandidate

A2 必须保存全部候选边，而不是只保存最终选择。

字段：

- `candidate_id`
- `junction_group_id`
- `left_dataset`
- `right_dataset`
- `left_arm_id`
- `right_arm_id`
- `score`
- `confidence`
- `seed_role_score`
- `local_candidate_score`
- `trace_terminal_score`
- `road_coverage_score`
- `geometry_score`
- `evidence_flags`
- `conflict_flags`
- `rank_for_left_arm`
- `rank_for_right_arm`
- `selected`
- `selection_reason`

### 6.3 LogicalArmGroup

字段：

- `logical_arm_group_id`
- `junction_group_id`
- `frcsd_arm_ids`
- `swsd_arm_ids`
- `rcsd_arm_ids`
- `group_status`
- `acceptable_for_downstream`
- `missing_datasets`
- `partial_datasets`
- `over_split_datasets`
- `over_merged_datasets`
- `evidence_summary`
- `risk_flags`
- `review_priority`

`group_status` 当前支持：

- `stable`
- `source_missing`
- `source_partial`
- `source_over_split_resolved`
- `source_over_split_unresolved`
- `source_over_merged_unresolved`
- `conflict`
- `uncertain`

后续 Movement 只能消费 `acceptable_for_downstream = true` 的 LogicalArmGroup。本模块不实现 Movement。

### 6.4 RawArmAlignment

字段：

- `alignment_id`
- `junction_group_id`
- `source_dataset`
- `target_dataset`
- `f_arm_id`
- `source_arm_ids`
- `match_type`
- `coverage_status`
- `confidence`
- `candidate_score`
- `source_initial_arm_ids`
- `f_source_initial_arm_ids`
- `evidence_summary`
- `reason_codes`
- `conflict_flags`
- `review_priority`
- `logical_arm_group_id`

`match_type` 当前支持 `1:1 / 1:N / N:1 / N:M / missing / uncertain / conflict`。

### 6.5 ArmBuildFeedback

字段：

- `feedback_id`
- `junction_group_id`
- `dataset`
- `feedback_type`
- `source_arm_ids`
- `supporting_datasets`
- `supporting_logical_arm_group_ids`
- `reason`
- `confidence`
- `review_priority`
- `evidence_summary`

`feedback_type` 当前支持：

- `recommended_merge`
- `recommended_split`
- `through_rule_suspect`
- `dead_end_tie_break_suspect`
- `local_candidate_fallback_insufficient`
- `semantic_boundary_suspect`
- `right_turn_exclusion_suspect`
- `source_missing_confirmed`

### 6.6 SourceExtraArm

字段：

- `dataset`
- `source_arm_id`
- `reason`
- `nearest_f_arm_candidates`
- `review_priority`

source_extra 不得静默忽略。

## 7. Review Priority

- `P0`：必须人工看。
- `P1`：建议人工看。
- `P2`：抽样看。
- `P3`：可跳过。

P0 至少由 stable arm 为 0、arm 数小于 2、ambiguous、loop、seed unassigned、SWSD/FRCSD Arm 数量明显差异等触发。

P1 至少由 patch boundary、dead end、右转排除异常高、T 判断异常、RCSD partial 等触发。

A2 P0 至少由 SWSD missing、conflict、uncertain、N:M、source_over_split_unresolved、source_over_merged_unresolved、F Arm 无 source candidate、source_extra 异常、`acceptable_for_downstream = false` 触发。

A2 P1 至少由 RCSD missing、partial、1:N、N:1、score medium、F FinalArm 依赖 local_candidate_fallback、source_over_split_resolved、ArmBuildFeedback 非空触发。
