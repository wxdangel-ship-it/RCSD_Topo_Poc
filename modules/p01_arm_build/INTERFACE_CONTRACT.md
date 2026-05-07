# P01 Arm Build 接口契约

## 1. 模块定位

`p01_arm_build` 是 P01 POC 验证模块，当前只覆盖 `P01-A / Arm 构建`。模块目标是在 SWSD / RCSD / F-RCSD 三套数据中分别构建当前语义路口的 Arm，并输出自动检查与人工目视审查产物。

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

当前还提供单路口文本证据包 dev helper，用于外部复现与内网 case 取证，不登记为正式 CLI：

```python
from rcsd_topo_poc.modules.p01_arm_build.text_bundle import (
    run_p01_decode_text_bundle_from_args,
    run_p01_export_text_bundle_from_args,
)
```

打包和解包均可通过 `python -c` 单命令调用。helper 使用 `zip + base85 + checksum` 文本包装，默认上限 `250 KiB`；上下文选择基于当前语义路口 Road 拓扑 BFS，不做简单空间裁剪。打包支持 `--auto-fit --max-bfs-depth N`，用于逐圈估算并选择不超过上限的最大 BFS 范围。

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
- `--right-turn-formway-value`：可选，可重复传入；仅用于声明本轮已确认能表达右转专用道 / 渠化右转的 `formway` 字段值。未传入时不因 `formway` 示例值或几何形态排除 Road。

### 3.4 最小字段

Node 最少字段：

- `id`
- `mainnodeid`
- `geometry`

可选字段：

- `kind`

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
- `--junction-group <swsd_junction_id>,<rcsd_junction_id>,<frcsd_junction_id>`
- `--out-txt`
- `--bfs-depth`：默认 `2`
- `--auto-fit`：可选；启用后从 `--bfs-depth` 起逐圈尝试到 `--max-bfs-depth`
- `--max-bfs-depth`：默认 `8`
- `--max-text-size-bytes`：默认 `256000`

解包 helper 参数：

- `--bundle-txt`
- `--out-dir`

解包输出：

- `manifest.json`
- `size_report.json`
- `SWSD/nodes.gpkg`
- `SWSD/roads.gpkg`
- `RCSD/nodes.gpkg`
- `RCSD/roads.gpkg`
- `FRCSD/nodes.gpkg`
- `FRCSD/roads.gpkg`

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

### 4.3 FinalArm

当前阶段 `FinalArm = InitialArm`，并保留：

- `final_arm_id`
- `source_initial_arm_ids`
- `merge_status = not_applied`
- `merge_reason = reserved_for_future_case_based_rules`

### 4.4 ArmTrace

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

### 4.5 ThroughDecisionAudit

允许状态：

- `simple_through`
- `t_mainline_through`
- `t_side_terminal`
- `semantic_boundary`
- `ambiguous_boundary`
- `dead_end`
- `patch_boundary`
- `loop_to_current_junction`

### 4.6 IssueReport

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
- `cases/<group_id>/<dataset>/arm_traces.json`
- `cases/<group_id>/<dataset>/through_decisions.json`
- `cases/<group_id>/<dataset>/issue_report.json`
- `cases/<group_id>/<dataset>/review_layers.gpkg`
- `cases/<group_id>/<dataset>/p01_arm_review.png`
- `cases/<group_id>/compare/p01_arm_compare.png`
- `cases/<group_id>/compare/p01_arm_compare_summary.json`
- `cases/<group_id>/compare/p01_arm_compare_layers.gpkg`
- `cases/<group_id>/trace_review/<trace_id>.png`

## 6. Review Priority

- `P0`：必须人工看。
- `P1`：建议人工看。
- `P2`：抽样看。
- `P3`：可跳过。

P0 至少由 stable arm 为 0、arm 数小于 2、ambiguous、loop、seed unassigned、SWSD/FRCSD Arm 数量明显差异等触发。

P1 至少由 patch boundary、dead end、右转排除异常高、T 判断异常、RCSD partial 等触发。
