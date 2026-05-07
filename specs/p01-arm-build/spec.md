# P01-A Arm 构建 Spec

## 1. Scope

本 SpecKit 任务只覆盖 `P01-A / Arm 构建`。P01-A 的目标是在已知 SWSD / RCSD / F-RCSD 三套数据对应路口 ID 的前提下，分别在三套数据中构建当前语义路口的 Arm，并产出可自动检查与人工目视审查的结果包。

本轮业务需求主源为用户提供的本地需求文档：

```text
/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/RCSD_Topo_Poc__P01_ArmBuild__REQUIREMENT.md
```

本轮仓库落地采用 `p01_arm_build` 模块 ID；`P01` 表示 POC 验证模块，目录结构与现有 `T0X` 正式模块保持一致。

## 2. In Scope

- 读取 SWSD / RCSD / F-RCSD 三套 Node 与 Road 基础数据。
- 支持重复传入多个三段式 `--junction-group <swsd>,<rcsd>,<frcsd>`。
- 按输入顺序生成 `group_0001`、`group_0002` 等稳定组 ID。
- 按 `mainnodeid` 组装语义路口：有效 `mainnodeid` 聚合，`null / "" / 0` 作为无效值并退化为单节点语义路口。
- 识别当前路口 internal roads、inbound / outbound / bidirectional seed roads。
- 仅在字段明确可识别时排除右转专用道 / 渠化右转，并把排除结果写入审计输出。
- 从当前路口 seed road 出发按拓扑追溯，输出 InitialArm。
- 当前阶段 `FinalArm = InitialArm`，仅保留合并占位字段。
- 输出 `JunctionContext / InitialArm / FinalArm / LocalArmCandidate / ArmTrace / ThroughDecisionAudit / ArmBuildIssueReport`。
- 输出 `LocalArmCandidate` 审计候选：仅基于当前语义路口 seed roads 的局部出入口趋势分组，用于人工判断 trace 过度切碎，不替代 FinalArm。
- 输出 review PNG、compare PNG、review GPKG、summary、review index 与 P0/P1 trace review PNG。
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

### 4.3 Right-Turn Exclusion

当前版本先排除右转专用道 / 渠化右转：

- 只有字段明确可识别时才排除。
- 字段缺失时不通过几何形态反推。
- 被排除 Road 不进入 seed、connector、through 判断或 T 型判断。
- 被排除 Road 必须写入 `excluded_right_turn_road_ids` 与 issue/audit 输出。

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

T 型判断必须结合当前追溯方向、拓扑结构与可用辅助提示。`kind` 只能作为提示，不能单独裁决；`grade / grade_2` 禁止进入主规则。

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
`--right-turn-formway-value` 可重复传入，用于声明本轮已确认能表达右转专用道 / 渠化右转的 `formway` 字段值；未传入时不得仅凭几何或示例值排除 Road。

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
cases/group_0001/trace_review/<trace_id>.png
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

### FinalArm

当前版本 `FinalArm = InitialArm`，并额外保留：

- `final_arm_id`
- `source_initial_arm_ids`
- `merge_status = not_applied`
- `merge_reason = reserved_for_future_case_based_rules`

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
- `rcsd_structure_incomplete`
- `frcsd_structure_incomplete`

## 8. Acceptance Criteria

- 能读取三套 Node / Road 基础数据。
- 能处理多个 `--junction-group`。
- 每组分别输出 SWSD / RCSD / FRCSD Arm 构建结果。
- 每条 seed road 有归属或明确 issue。
- 每个 through 判断有可审计状态。
- 输出 JSON / PNG / GPKG / summary / review index。
- 自动检查能发现关键异常。
- 代码中不使用 `grade / grade_2` 参与 Arm 构建主规则。
- 完成 py_compile、单元测试、synthetic case、多 junction-group、输出结构、PNG/GPKG 存在性与审计检查。
