# T10 - INTERFACE_CONTRACT

## 定位

本文件是 `t10_e2e_orchestration` 的稳定接口契约。

T10 面向 RCSD_Topo 端到端业务流程编排与 Case 级证据组织。项目级主业务链仍保持 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`；T10 v1 的局部编排范围为 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T09`，T08 作为独立前置预处理、质检与修复模块，不由 T10 v1 callable 或 Case runner 调用。内网全量总控脚本可把 T08 作为独立前置阶段纳入全量执行链路。T07 Step3 是可选兼容 relation 补锚阶段，不属于 T10 v1 默认编排。

## 1. 目标与范围

### 1.1 当前正式支持

- 固化 T10 v1 编排链路：
  - `T01`
  - `T07 Step1/2`
  - `T03`
  - `T04`
  - `T05`
  - `T06`
  - `T09`
- 为全链路建立显式文件级 handoff slot。
- 拒绝目录型 handoff，例如只传 `t05_phase2_root` 而不指明 `intersection_match_all.geojson / rcsdroad_out.gpkg / rcsdnode_out.gpkg`。
- 输出 T10 workflow plan、handoff audit 与 summary。
- 支持从 T10 Case package 启动 Case 级端到端执行：`T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T09`。
- 支持输出 T10 Case run manifest、stage audit 与 T06 数据漏斗。
- 以 SWSD 语义路口 ID 和半径声明 Case 证据包范围。
- 支持 Case 候选建议：从 SWSD nodes 建立语义路口 inventory，再用可选 selector evidence 映射出问题候选。
- 支持多个 CaseID 一次打包，解包后按 `cases/<case_id>/` 重组。
- 支持文本 bundle 自动分片与解包。
- Case 证据包 v1 只纳入外部输入，排除模块间中间产物。
- `include_files=true` 时，正式默认物化模式为 `spatial_slice`：按 SWSD 语义路口 ID 与 `radius_m` 对外部输入生成局部 GPKG 切片。
- `spatial_slice` 必须补齐道路端点节点依赖，并保留被选中道路的完整几何，避免局部 Case replay 因窗口裁剪丢失 `snodeid/enodeid` 端点。

### 1.2 当前非目标

- 不改变项目级主业务链。
- T10 v1 callable 与 Case runner 不调用 T08。
- 不修改 T01-T09 模块算法。
- 不新增 repo CLI、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。
- root `scripts/t10_pack_innernet_cases.sh` 是当前正式内网 Case 证据包打包入口。
- root `scripts/t10_run_e2e_cases.sh` 是当前正式 T10 Case 级端到端执行入口。
- root `scripts/t10_run_innernet_full_pipeline.sh` 是当前正式 T10 内网全量端到端总控入口。
- 不补充或改写 T09 业务实现；T09 模块文档面已由独立文档治理补齐。

## 2. Inputs

### 2.1 Workflow manifest

T10 v1 callable 接受一个结构化 manifest，至少包含：

```json
{
  "external_inputs": {
    "prepared_swsd_nodes": "...",
    "prepared_swsd_roads": "...",
    "drivezone": "...",
    "divstripzone": "...",
    "rcsd_intersection": "...",
    "rcsdroad": "...",
    "rcsdnode": "...",
    "sw_restriction_tool7": "...",
    "sw_arrow_tool8": "..."
  },
  "handoffs": {
    "t01_segment": "...",
    "t01_nodes": "...",
    "t01_roads": "...",
    "t07_nodes": "...",
    "t07_relation_evidence": "...",
    "t07_surface": "...",
    "t03_nodes": "...",
    "t03_surface": "...",
    "t03_relation_evidence": "...",
    "t03_intersection_match": "...",
    "t04_nodes": "...",
    "final_swsd_nodes": "...",
    "t04_surface": "...",
    "t04_relation_evidence": "...",
    "t04_intersection_match": "...",
    "t05_junction_surface": "...",
    "t05_intersection_match_all": "...",
    "t05_rcsdroad_out": "...",
    "t05_rcsdnode_out": "...",
    "t06_frcsd_road": "...",
    "t06_frcsd_node": "...",
    "t06_swsd_frcsd_segment_relation": "...",
    "t09_restored_field_rules": "..."
  }
}
```

### 2.2 Case package request

Case 证据包 v1 输入：

- `semantic_junction_id` / `semantic_junction_ids`：SWSD 语义路口 ID。CaseID 的正式含义是 SWSD semantic junction id，不是坐标。
- `radius_m`：Case 范围半径，单位米，当前切片 CRS 为 `EPSG:3857`。
- `include_files`：是否物化外部输入文件；`true` 时默认生成空间切片，`false` 时只生成 manifest。
- `materialization_mode`：可选，允许值：
  - `spatial_slice`：正式默认；生成局部 GPKG 切片。
  - `manifest_only`：只写 manifest，不扫描或复制全量输入内容。
  - `copy_full`：兼容诊断模式；复制全量外部输入，不作为正式内网 Case 包默认模式。

### 2.3 Case suggest request

`suggest` 的输入分两类：

- `prepared_swsd_nodes`：必选，用于建立 SWSD 语义路口 inventory。
- `selector_evidence`：可选，用于从 T08/T05/T06/T09 等审计或错误文件中筛出问题候选。

语义路口 inventory 规则：

- 若 node 有有效 `mainnodeid`，CaseID 使用 canonical `mainnodeid`。
- 若 `mainnodeid` 为空、`0`、`0.0`、`none`、`null`、`nan` 或 `-1`，CaseID 退化为 node `id`。
- 坐标只从 CaseID 对应 member node geometry 派生为 `center_x / center_y`，不作为 CaseID。

selector evidence 映射规则：

- 优先读取 `case_id / swsd_semantic_junction_id / semantic_junction_id / target_id / mainnodeid / junction_id / main_node_id`。
- 若上述字段不能直接命中 CaseID，再读取 `node_id / id` 并映射到该 node 所属 SWSD 语义路口。
- 命中 selector evidence 的 Case 输出 `candidate_status = problem_candidate`。
- 没有 selector evidence 时，可输出 `candidate_status = inventory_only` 的可打包语义路口清单，但不得表述为问题 Case。

### 2.4 Case runner request

T10 Case runner 输入：

- `package_dir`：已解包或直接生成的 T10 Case package 目录。支持 `cases/<case_id>/` 多 Case package 根目录、根目录直接包含多个 `<case_id>/t10_case_evidence_manifest.json` 的扁平多 Case 目录，也支持单 Case 目录。
- `case_id`：可选，可重复指定。未指定时执行 package 内全部 Case。
- `out_root`：T10 E2E run 输出根目录。
- `run_id`：可选。未指定时自动生成。
- `stop_after`：可选阶段名，用于受控截断执行。允许值为 `t01 / t07 / t03 / t04 / t05 / t06_step12 / t06_step3 / t09_step12 / t09_step3`。
- `continue_on_error`：是否在某个 Case 阶段失败后继续记录后续 Case 或后续阶段阻断状态。

Case runner 必须优先消费 Case package 中 `external_inputs/<slot>/<slot>_slice.gpkg`。当 package 仅为 manifest-only 时，才回退到 manifest 记录的 source path。

Case runner 不改变 T01-T09 算法，只负责：

- 把 T10 外部输入与模块间 handoff 显式绑定到文件路径。
- 调用已存在的模块脚本或模块 callable。
- 记录每个阶段的 command、env override、输入、输出、stdout log、耗时与状态。
- 在 T06 可执行时生成 T06 数据漏斗。

T10 的 nodes handoff 规则：

- `t07` 阶段输出的 `t07_nodes` 是 T07 Step2 anchor recognition 后的 nodes，只作为 T03 输入和 T07 审计事实。
- `t03` 阶段必须输出 `t03_nodes`，T04 必须消费该节点层，确保 T03 已确认的虚拟锚定状态继续传递。
- `t04` 阶段必须输出 `t04_nodes`，并同步登记为 `final_swsd_nodes`；T05 / T06 / T09 必须消费 `final_swsd_nodes`，不得回退到 T07 Step2 nodes。
- T07 Step3 是可选兼容 relation 补锚；Case runner 默认不调用它，也不把 T05 Phase2 `intersection_match_all` 作为默认回灌源。
- innernet full pipeline 只有在显式配置 `RUN_T07_STEP3` 与 `T07_STEP3_INTERSECTION_MATCH_ALL_PATH` 时才运行 Step3；运行后可把 Step3 输出的 `nodes.gpkg` 登记为 `t07_final_nodes`，但它不得覆盖 `final_swsd_nodes` 的正式 handoff。

## 3. Outputs

### 3.1 Workflow planning outputs

目录：

```text
<out_root>/<run_id>/
```

文件：

- `t10_workflow_plan.json`
- `t10_handoff_audit.json`
- `t10_summary.json`

`t10_handoff_audit.json` 至少记录：

- 是否通过。
- 缺失 slot。
- 目录型 handoff。
- 严格存在性检查下的缺失文件。

### 3.2 Case evidence package outputs

单 Case 目录：

```text
<out_root>/<package_id>/
```

文件：

- `t10_case_evidence_manifest.json`
- `t10_case_evidence_summary.json`
- 可选：`external_inputs/<slot>/<source_file>`

Case package manifest 必须记录：

- SWSD 语义路口 ID。
- 半径、切片 CRS、中心点与 bounds。
- 所有外部输入 slot。
- 被排除的模块间 handoff slot。
- `selection_status`。`spatial_slice` 成功时为 `spatial_slice_completed`；manifest-only 时为 `manifest_scope_declared`。

`spatial_slice` 模式输出：

```text
external_inputs/<slot>/<slot>_slice.gpkg
```

每个 slot 的审计至少包含：

- source path、source exists、source size、source mtime。
- source feature count、selected feature count、output feature count。
- output path、output size、output sha256、output bounds。
- source CRS、CRS source、output CRS。
- invalid geometry count、empty-after-clip count。

多 Case 目录：

```text
<out_root>/<package_id>/
  t10_multi_case_evidence_manifest.json
  t10_multi_case_evidence_summary.json
  cases/
    <case_id>/
      t10_case_evidence_manifest.json
      t10_case_evidence_summary.json
      external_inputs/
```

直接从测试数据根目录运行时，也允许根目录下直接放置多个 Case 子目录：

```text
<package_dir>/
  <case_id>/
    t10_case_evidence_manifest.json
    t10_case_evidence_summary.json
    external_inputs/
```

文本 bundle 分片：

```text
t10_case_bundle.txt
t10_case_bundle.part_0002_of_000N.txt
...
```

解包时必须自动读取同目录其它分片，校验 checksum，并恢复 `cases/<case_id>/` 目录结构。

### 3.3 Case suggestion outputs

目录：

```text
<out_root>/<run_id>/
```

文件：

- `t10_case_suggestions.json`
- `t10_case_suggestions.csv`
- `t10_case_suggestions_summary.json`

### 3.4 Case runner outputs

目录：

```text
<out_root>/<run_id>/
```

文件：

- `t10_e2e_run_manifest.json`
- `t10_e2e_run_summary.json`
- `t10_upstream_feedback_segments.csv/json`
- `t10_upstream_feedback_summary.csv/json`
- `t10_upstream_side_group_candidates.csv/json`
- `t10_upstream_side_group_endpoint_candidates.csv/json`
- `t10_upstream_pair_anchor_endpoint_clusters.csv/json`
- `t10_upstream_feedback_relations.csv/json`
- `t10_upstream_feedback_relation_summary.csv/json`
- `t10_t06_visual_check_summary.csv/json`
- `cases/<case_id>/t10_e2e_case_run_manifest.json`
- `cases/<case_id>/t10_e2e_case_run_summary.json`
- `cases/<case_id>/t10_t06_funnel.json`
- `cases/<case_id>/t10_t06_funnel.csv`
- `cases/<case_id>/t10_t06_funnel.md`
- `cases/<case_id>/<stage>/stdout.log`
- `cases/<case_id>/<stage>/<stage>_stage.json`

顶层 `t10_e2e_run_summary.json` 必须输出机器可读完成口径：`status / passed / started_at_utc / ended_at_utc / duration_seconds / completed_case_count`。`status` 的取值与 Case 汇总状态一致：全部 Case 通过时为 `passed`；存在 `failed` Case 时为 `failed`；不存在失败但存在 `blocked` Case 时为 `blocked`；其它截断或未完整执行口径为 `skipped`。每个 `cases/<case_id>/t10_e2e_case_run_summary.json` 同步输出 `status`，取值等于该 Case 的 `overall_status`。

当 `feedback_iterations > 0` 或脚本环境变量 `T10_FEEDBACK_ITERATIONS > 0` 时，顶层 `<out_root>/<run_id>/` 作为反馈迭代汇总目录；每个 pass 写入：

- `iterations/iteration_00_baseline/`
- `iterations/iteration_<NN>_feedback_<NN>/`

顶层 `t10_e2e_run_manifest.json` 与 `t10_e2e_run_summary.json` 记录 `feedback_iteration_mode / iterations / final_iteration / feedback_comparison / feedback_regression_guard_passed`。`feedback_comparison` 必须至少包含 baseline 与最终 pass 的 `added_replaced_segment_ids / removed_replaced_segment_ids / added_replacement_plan_segment_ids / removed_replacement_plan_segment_ids`。replacement plan 对比必须使用 plan 覆盖 Segment 集合：普通 plan 行读取 `swsd_segment_id`，组级 plan 行还必须展开 `group_segment_ids`，以允许已成功单段从 `standard_segment` 升级为 `path_corridor_group` 成员而不被误判为回退。若任一已有 replaced Segment 或 replacement plan 覆盖 Segment 在最终 pass 被移除，`feedback_regression_guard_passed = false`，本次 run 不通过。多轮 feedback pass 必须把 side-group endpoint candidate 与 `auto_consumable_by_t05=true` 的 pair-anchor endpoint cluster 按业务字段去重累积，并分别在 `<run_root>/feedback_candidates/iteration_<NN>_cumulative_side_group_endpoint_candidates.csv`、`<run_root>/feedback_candidates/iteration_<NN>_cumulative_pair_anchor_endpoint_clusters.csv` 发布累积候选供下一 pass 消费，不允许用后一轮新产物覆盖前一轮已生效候选。当本轮产出的 feedback candidate 与本轮输入候选在业务字段上完全一致时，`final_iteration.feedback_stop_reason = feedback_candidates_converged`，runner 不再继续后续 feedback pass；收敛判断忽略 `problem_registry_path` 等来源路径字段。

阶段状态：

- `passed`：阶段命令返回 0，且 T10 已记录该阶段可发现输出。
- `failed`：阶段命令返回非 0 或发生未捕获异常。
- `blocked`：阶段所需显式输入缺失，或同一 Case 的前置阶段未通过。
- `skipped`：执行策略导致阶段未运行。

同一 Case 内任一阶段 `failed/blocked` 后，T10 不提升该阶段的部分输出为正式 handoff，后续阶段只写 blocked 审计。`CONTINUE_ON_ERROR` 只控制多 Case 批处理是否继续执行下一个 Case。

T06 数据漏斗至少记录：

- Step1：`input_segment_count / evd_candidate_count / swsd_candidate_count / final_fusion_unit_count / swsd_final_fusion_unit_count`。
- Step2：`input_fusion_unit_count / rcsd_candidate_count / replaceable_count / replacement_plan_count / replacement_plan_ready_count / problem_registry_count / rejected_count / buffer_segment_count / buffer_rejected_count`。
- Step3：`input_replaceable_count / input_replacement_plan_count / input_standard_replacement_plan_count / replacement_unit_success_count / replacement_unit_failure_count / removed_swsd_road_count / removed_swsd_node_count / added_rcsd_road_count / added_rcsd_node_count / frcsd_road_count / frcsd_node_count / segment_relation_count`。
- 质量：Step1/Step2 reject reason、Step2 buffer reject reason、replacement plan scope、problem registry status、Step3 collision 与 segment relation 状态计数。

T10 Case runner 在 run root 额外发布 T06 目视检查索引：

- `t10_t06_visual_check_summary.csv/json`：每个 Case 一行，列出目视叠加所需的 T01/T03/T04/T05/T06/T07 GPKG 路径，包括 `t01/segment.gpkg`、`t01/roads.gpkg`、默认 T07 Step2 `nodes.gpkg` 与 `t07_rcsdintersection_anchor_surface.gpkg`、T03 `virtual_intersection_polygons.gpkg`、T04 `divmerge_virtual_anchor_surface.gpkg` 与 `divmerge_virtual_anchor_surface_audit.gpkg`、T05 `junction_anchor_surface.gpkg`、T06 Step2 `t06_rcsd_segment_replaceable.gpkg`、`t06_segment_replacement_plan.gpkg`、`t06_segment_replacement_problem_registry.gpkg`，以及 T06 Step3 `t06_frcsd_road.gpkg`、`t06_frcsd_node.gpkg`、`t06_step3_swsd_frcsd_segment_relation.gpkg`、`t06_step3_topology_connectivity_audit.gpkg`、`t06_step3_surface_topology_audit.gpkg`。显式运行 T07 Step3 时，可额外索引 Step3 补锚输出。
- 该索引同步记录 Step2/Step3 关键计数、已存在图层 CRS 状态、缺失图层清单、提右道路总数、RCSD/SWSD 提右数量、SWSD 提右与 RCSD 提右几何重叠超过 20% 的疑似重复数量、提右道路端点缺节点数量、全量道路端点缺节点数量。
- 该索引为 audit-only 产物，只读取既有 GPKG 并生成 CSV/JSON，不改写 road/node/relation，不执行几何修复，不作为 T06 Step3 替换白名单。

T10 Case runner 在 run root 额外发布 T06 上游反馈包：

- `t10_upstream_feedback_segments.csv/json`：逐条收集各 Case `t06_segment_replacement_problem_registry.csv` 中 `problem_status` 以 `requires_upstream` 开头的 Segment，保留 `problem_status / recommended_module / upstream_issue_owner / failure_business_category / reject_reason / root_cause_category / feedback_action / evidence_artifacts`、pair-anchor endpoint 诊断字段与来源 registry 路径；其中 `requires_upstream_side_group_or_rcsd_directionality_review` 表示应先评估 T03/T04/T05 双幅端点侧聚合，聚合不成立时再进入 RCSD 方向性或源资料复核。
- `t10_upstream_feedback_summary.csv/json`：按 `recommended_module + upstream_issue_owner + failure_business_category + reject_reason + root_cause_category` 聚合计数，并保留样例 Case 与 Segment。
- `t10_upstream_side_group_candidates.csv/json`：从 `requires_upstream_side_group_or_rcsd_directionality_review` Segment 中提取 `swsd_endpoint_node_ids / rcsd_primary_pair_node_ids / candidate_rcsd_pair_node_sets / candidate_group_rcsdnode_ids`，形成 T03/T04/T05 二次迭代可消费的候选聚合单元；该产物只表达“需要评估虚拟路口聚合”的候选范围，不宣布聚合成立，也不修正 RCSD 道路方向性。候选集合必须引入 `rcsd_primary_pair_node_ids` 之外的新 RCSDNode；无新增节点的 no-op 候选只保留在 segment feedback 中。
- `t10_upstream_side_group_endpoint_candidates.csv/json`：将满足新增 RCSDNode 条件的 `requires_upstream_side_group_or_rcsd_directionality_review` segment 级候选按 `swsd_endpoint_node_ids` 拆成 endpoint 级候选，每行包含一个 SWSD endpoint `target_id`、该端点对应的 `rcsd_primary_node_id` 与 `candidate_rcsdnode_ids`。该产物是 T05 Phase2 的可选补充输入，只能补充同 target 已存在的 T07/T03/T04/T02 成功 relation 以执行 RCSDNode grouping，不得单独创建 SWSD-RCSD relation。拆分 endpoint candidate 时，若某个候选 RCSDNode 等于同一 SWSD Segment 另一端的 primary pair node，必须从当前 endpoint 候选中剔除；剔除后无新增 RCSDNode 的 endpoint 行不得发布给 T05，避免把双端锚点压入同一虚拟聚合关系。对于 `directionality_mismatch_fixable + rcsd_not_bidirectional_for_swsd_dual` 且 T06 `t06_rcsd_buffer_only_probe.csv` 已找到单连通候选走廊的 Segment，T10 允许基于 T05 `relation_graph_consumability_audit.csv`、`rcsd_junctionization_audit.csv` 与 `rcsdroad_out.gpkg` 生成 `side_group_action=supplement_existing_relation_with_relation_graph_bridge` 的 endpoint candidate；该候选只能补充已由 `T10_SIDE_GROUP` 形成的多基准 relation，新增 RCSDNode 必须同时是 T05 已消费 relation 的 `base_id`、不属于当前 Segment 两端 primary pair node、在 RCSD road graph 中 1 hop 内连接当前 Segment primary pair node，且 3 hop 内连接该 `T10_SIDE_GROUP` relation graph 上下文。其它 `requires_upstream_iteration` 即使携带 `candidate_rcsd_pair_node_sets`，在没有明确端点下标语义前也不得转成 endpoint candidate。
- `t10_upstream_pair_anchor_endpoint_clusters.csv/json`：将 T06 problem registry 中稳定的 `pair_anchor_endpoint_cluster_nodes` 按 endpoint 拆成审计行，保留 `pair_anchor_bridge_road_ids / pair_anchor_bridge_length_m / pair_anchor_diagnostic_source / pair_anchor_diagnostic_reason` 与来源 registry 路径。该产物默认 `auto_consumable_by_t05=false`；只有 `problem_status` 以 `requires_upstream` 开头、`failure_business_category=pair_anchor_mismatch`、`reject_reason=rcsd_pair_nodes_not_distinct`、`pair_anchor_diagnostic_source=buffer_only_endpoint_cluster`、`pair_anchor_diagnostic_reason=short_connected_endpoint_cluster`，且该 endpoint cluster 至少包含 `rcsd_primary_node_id` 之外的新增 RCSDNode 时，才允许标记 `auto_consumable_by_t05=true`。即使标记为 true，也只能作为 T05 Phase2 的可选补充输入，不得单独创建 SWSD-RCSD relation，不作为 T06 Step3 替换白名单。
- `t10_upstream_feedback_relations.csv/json`：逐条收集各 Case T05 `relation_graph_consumability_audit.csv` 中 `status = 0` 但 `graph_consumable != 1` 的 SWSD-RCSD relation，保留 `target_id / base_id / graph_consumability_status / source_modules / scenes / reasons / affected_problem_segment_ids` 与来源审计路径。
- `t10_upstream_feedback_relation_summary.csv/json`：按 `recommended_module + upstream_issue_owner + failure_business_category + graph_consumability_status + source_modules + reasons` 聚合计数，并保留样例 Case 与 SWSD 语义路口。

Relation 级反馈只用于把 T05/T07/T03/T04 的 relation handoff 或 junctionization 消费问题前置暴露，不改写 `intersection_match_all.geojson`，不影响 T06 当前已成功替换的 Segment。
- side-group candidate 级反馈只用于把 T06 识别出的双向 Segment 侧聚合需求结构化交付给下一轮 T03/T04/T05，不作为 T06 Step3 替换计划，不参与 T09 restriction 生成。
- side-group endpoint candidate 级反馈只在端点层面补充候选 RCSDNode 集合，避免把同一 Segment 两端错误聚合成同一个 RCSD 语义路口。
- pair-anchor endpoint cluster 级反馈默认只发布 T06 已诊断出的端点簇证据；满足 `auto_consumable_by_t05=true` 的行只能补充同 target 已有成功 relation 或 road-only split 的 RCSDNode grouping，不能创建 relation 或虚拟路口面。
- feedback iteration 只把前序 pass 累积后的 endpoint 级候选和可消费 endpoint cluster 回灌到 T05 Phase2；它不把 T06 problem registry 直接转成 Step3 替换白名单，也不绕过 T03/T04/T05 的 relation/junctionization 审计。
- 该反馈包只用于驱动 T01/T03/T04/T05/T08/T06 的后续根因迭代，不是 Step3 替换白名单，不改变 T06/T09 产出。
- 该反馈包为 attribute-only 审计产物，不进行几何变换、拓扑修复或字段语义反推。

### 3.5 Innernet full pipeline outputs

`scripts/t10_run_innernet_full_pipeline.sh` 输出目录：

```text
<out_root>/<run_id>/
```

默认 `<out_root>` 为 `outputs/_work/t10_innernet_full_pipeline`。

根目录文件：

- `t10_innernet_full_pipeline_manifest.json`
- `t10_innernet_full_pipeline_summary.json`
- `logs/<stage>.log`
- `t08_preprocess/`
- `t01_full_data/`
- `t07_semantic_junction_anchor/`
- `t03_internal_full_input/`
- `t04_internal_full_input/`
- `t05_innernet_experiment/`
- `t07_step3_intersection_match/`（仅在显式运行可选 T07 Step3 时存在）
- `t06_segment_fusion_precheck/`
- `t09_swsd_field_rule_restoration/`

`t10_innernet_full_pipeline_manifest.json` 保留兼容的 flat `inputs / outputs`，同时必须提供阶段级 `stage_order / stages`。每个 `stages.<stage_id>` 至少包含 `stage_id / module_id / status / stdout_log / inputs / outputs / params / execution_context`，用于统一表达 T08、T01、T07 Step1/2、T03、T04、T05、T06 Step1/2、T06 Step3、T09 的显式 handoff；显式启用 T07 Step3 时，manifest 才登记 `t07_step3` 阶段。下游审计应优先消费 `stages`，仅在兼容旧产物时读取 flat `outputs`。

全量 runner 在创建 manifest 时必须先写入 `status=running / passed=false`；进程退出时必须写入 `status / passed / exit_code / finished_at_utc / duration_seconds`。T09 阶段完成且最终 `frcsd_restriction.gpkg` 存在时，`status=passed`；任一阶段命令失败或必要输出缺失时，退出 trap 必须把顶层状态写为 `failed`。`t10_innernet_full_pipeline_summary.json` 是 manifest 的轻量完成判定文件，至少记录 `run_id / run_root / status / passed / exit_code / stage_statuses / missing_final_outputs / t06_frcsd_road / t06_frcsd_node / t09_frcsd_restriction / manifest`。

若既有全量 run 已完成 T09 但缺少 T10 顶层完成状态，可使用同一入口的只收尾模式补写 summary：

```bash
FINALIZE_EXISTING=1 RESUME_RUN_ROOT=<existing_run_root> bash scripts/t10_run_innernet_full_pipeline.sh
```

该模式只读取既有 `t10_innernet_full_pipeline_manifest.json`、T06 Step3 F-RCSD Road/Node 和 T09 `frcsd_restriction.gpkg`，不重跑 T01-T09，不修改中间阶段产物。最终三类产物缺任一项时，summary 写为 `status=failed` 并列出 `missing_final_outputs`。

若既有全量 run 已完成前序阶段，但只需从某个模块阶段继续执行，可使用同一入口的阶段续跑模式：

```bash
RESUME_RUN_ROOT=<existing_run_root> RESUME_FROM_STAGE=t06_step3 bash scripts/t10_run_innernet_full_pipeline.sh
```

`RESUME_FROM_STAGE` 会从指定阶段开始按正式顺序继续执行到 `t09`；`RUN_STAGES` 可进一步指定精确阶段集合，例如：

```bash
RESUME_RUN_ROOT=<existing_run_root> RUN_STAGES=t06_step3,t09 bash scripts/t10_run_innernet_full_pipeline.sh
```

阶段续跑模式不创建新 run root，不重跑未列入 `RUN_STAGES` 的前序阶段；它优先读取既有 manifest 中的 `inputs / outputs` 作为 handoff，缺失时才回退到该全量 runner 的固定目录结构。支持阶段名：`t08_preprocess / t01 / t07_step12 / t03 / t04 / t05 / t06_step12 / t06_step3 / t09`；`t07_step3` 只作为显式兼容补锚阶段支持，续跑它时必须额外提供 `T07_STEP3_INTERSECTION_MATCH_ALL_PATH`。最终完整 T10 通过仍以 T06 F-RCSD Road/Node 和 T09 `frcsd_restriction.gpkg` 存在为准。

manifest 至少记录：

- run id、repo path、创建时间、执行阶段顺序。
- 原始全量输入路径。
- 每个阶段被正式提升为 handoff 的输出路径。
- 最终 `t06_frcsd_road`、`t06_frcsd_node` 与 `t09_frcsd_restriction` 路径。

该 runner 不生成 Case 级 `t10_t06_funnel.*`；全量替换率和质量审计应消费 T06/T09 阶段正式输出或另行运行全量审计脚本。

## 4. EntryPoints

当前 repo 官方入口：

```bash
bash scripts/t10_pack_innernet_cases.sh <case_id> [case_id ...]
bash scripts/t10_run_e2e_cases.sh --package-dir <decoded_or_generated_package_dir> [--case-id <case_id> ...]
bash scripts/t10_run_innernet_full_pipeline.sh
```

该入口的 CaseID 含义固定为 SWSD semantic junction id。脚本读取 T10 v1 外部输入 slot，生成多 Case package，并导出可自动分片的文本 bundle。解包后目录结构按 `cases/<case_id>/` 恢复。

脚本支持的位置参数与环境变量：

- `CASE_IDS`：未提供位置参数时使用，支持逗号分隔。
- `RADIUS_M`：Case 范围半径，默认 `250`。
- `INCLUDE_FILES`：是否物化外部输入文件，默认 `1`。
- `MATERIALIZATION_MODE`：物化模式，默认按 `INCLUDE_FILES` 自动选择；`INCLUDE_FILES=1` 时默认 `spatial_slice`。
- `OUT_ROOT`：package 输出根目录，默认 `outputs/_work/t10_case_evidence`。
- `BUNDLE_ROOT`：文本 bundle 输出根目录，默认 `outputs/_work/t10_case_evidence_bundles`。
- `MAX_TEXT_SIZE_BYTES`：文本 bundle 分片阈值，默认 `256000`。
- `DECODE_AFTER_EXPORT`：是否导出后立即解包校验，默认 `0`。
- `TESTDATA_ROOT`：内网测试数据根目录，默认 `/mnt/d/TestData/POC_Data`。
- T10 v1 外部输入 slot 环境变量：`PREPARED_SWSD_NODES`、`PREPARED_SWSD_ROADS`、`DRIVEZONE`、`DIVSTRIPZONE`、`RCSD_INTERSECTION`、`RCSDROAD`、`RCSDNODE`、`SW_RESTRICTION_TOOL7`、`SW_ARROW_TOOL8`。

`scripts/t10_run_e2e_cases.sh` 支持的位置参数与环境变量：

- `--package-dir` / `PACKAGE_DIR`：T10 package 目录。
- `--case-id`：可重复指定。未指定时执行 package 内全部 Case。
- `OUT_ROOT`：T10 E2E 输出根目录，默认 `outputs/_work/t10_e2e_case_runs`。
- `RUN_ID`：可选输出 run id。
- `STOP_AFTER`：可选截断阶段。
- `CONTINUE_ON_ERROR`：默认 `1`；仅控制当前 Case 失败后是否继续下一个 Case，不允许同一 Case 下游消费失败阶段的部分输出。
- `EXIT_ZERO`：默认 `0`；置 `1` 时即使存在 blocked/failed Case 也返回 0，便于诊断批处理继续。
- `T10_T03_WORKERS`、`T10_T04_WORKERS`、`T10_T05_READONLY_WORKERS`：默认均为 `1`，用于 Case 级局部 replay。
- `T10_FEEDBACK_ITERATIONS`：默认 `0`；大于 0 时执行 T06 upstream feedback 回灌迭代，并启用 baseline 到 final 的 replaced / replacement plan 不回退检查。
- `T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS`：可选 pair-anchor endpoint cluster CSV；仅在已按 T10 契约标记 `auto_consumable_by_t05=true` 且 T05 存在基础 relation / road-only split 时作为补充输入。

`scripts/t10_run_innernet_full_pipeline.sh` 支持的环境变量：

- `TESTDATA_ROOT`：内网测试数据根目录，默认 `/mnt/d/TestData/POC_Data`。
- `RUN_ID`：全量执行 run id，未指定时自动生成。
- `OUT_ROOT`：全量执行输出根目录，默认 `outputs/_work/t10_innernet_full_pipeline`。
- `FINALIZE_EXISTING`：`1` 时只对既有 `RUN_ID` 补写顶层完成状态，不重跑全量链路。
- `RESUME_RUN_ROOT`：既有 T10 全量 run root；设置后从该目录读取 manifest 与前序 handoff。
- `RESUME_FROM_STAGE`：阶段续跑的起始阶段；未设置 `RUN_STAGES` 时，从该阶段顺序执行到 `t09`。
- `RUN_STAGES`：可选，逗号分隔的精确执行阶段集合；设置后只执行列出的阶段。
- `RUN_T08`：是否运行 T08 前置阶段，默认 `1`。
- `RUN_T08_TOOL7` / `RUN_T08_TOOL8`：可选值 `1 / 0 / auto`，默认 `auto`，仅当原始 SW 输入齐全时自动生成 Tool7/Tool8 输出。
- `RUN_T08_TOOL9`：可选值 `1 / 0 / auto`，默认 `0`，用于显式启用 RCSD 清理前置输出。
- `T03_WORKERS` / `T04_WORKERS` / `T05_READONLY_WORKERS`：全量执行 worker 参数，默认分别为 `8 / 8 / 4`。
- 全量输入覆盖变量：`SWSD_INPUT_NODES`、`SWSD_INPUT_ROADS`、`DRIVEZONE_PATH`、`DIVSTRIPZONE_PATH`、`RCSD_INTERSECTION_PATH`、`RCSDROAD_PATH`、`RCSDNODE_PATH`。
- T08 Tool7/Tool8 原始输入覆盖变量：`SW_CONDITION_GPKG`、`SW_LANE_GPKG`、`SW_NODE_GPKG`、`SW_ROAD_GPKG`。
- 复用既有 Tool7/Tool8 结果覆盖变量：`SW_RESTRICTION_TOOL7`、`SW_ARROW_TOOL8`。
- T08 Tool9 输入覆盖变量：`ROAD_SURFACE_GPKG`。

该全量 runner 只消费并串联既有模块脚本或 callable，不新增 T01-T09 的算法接口。

当前仍无 repo CLI、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。

可在测试或上层调用中使用模块内 callable：

```python
from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    build_multi_case_evidence_package,
    build_case_evidence_package,
    build_t10_t06_funnel_summary,
    decode_t10_case_evidence_text_bundle,
    export_t10_case_evidence_text_bundle,
    run_t10_e2e_cases_from_package,
    suggest_t10_cases,
    write_t10_planning_outputs,
)
```

后续新增其它稳定入口必须另行授权并同步 `docs/repository-metadata/entrypoint-registry.md`。

## 5. Params

- `strict_exists`：是否要求 manifest 中配置的路径在本机存在。
- `run_id`：workflow planning 输出 run id；缺省自动生成。
- `package_id`：Case package id；缺省自动生成。
- `include_files`：是否物化外部输入文件。
- `materialization_mode`：`spatial_slice / manifest_only / copy_full`。
- `target_epsg`：空间切片目标 CRS，默认 `3857`。
- `selector_evidence`：用于 suggest 的候选证据文件映射。
- `max_text_size_bytes`：文本 bundle 自动分片阈值，默认 `250KB`。
- `stop_after`：T10 E2E Case runner 截断阶段。
- `continue_on_error`：T10 E2E Case runner 是否继续记录后续 Case 或阻断阶段。

## 6. Acceptance

1. T10 v1 workflow plan 中链路不包含 T08。
2. 项目级主业务链仍保留 T08。
3. 目录型 handoff 被审计为错误。
4. Case evidence package manifest 包含所有外部输入 slot。
5. Case evidence package manifest 排除 T01-T09 模块间中间产物。
6. `suggest` 只能把 selector evidence 映射为候选 Case，不把 inventory-only 清单表述为问题。
7. 多 Case bundle 解包后按 `cases/<case_id>/` 恢复目录。
8. 不新增未登记执行入口。
9. GIS / 拓扑 QA 五项在 summary 或模块质量文档中有明确状态。
10. `spatial_slice` 模式不得复制全量外部输入；每个 Case 目录只能物化半径窗口内的局部 GPKG。
11. `spatial_slice` 必须审计道路端点节点依赖完整性，不允许 silent fix。
12. Case runner 必须输出每阶段显式输入、输出、命令、状态与日志路径。
13. T06 已运行时必须输出 `t10_t06_funnel.json/csv/md`。
14. T05 之后不得默认强制执行 `t07_step3`；T06/T09 默认消费 T04 输出的 `final_swsd_nodes`，显式运行可选 T07 Step3 时也只能额外审计 Step3 `nodes.gpkg`，不得覆盖正式节点 handoff。
15. Case runner 必须输出 `t10_t06_visual_check_summary.csv/json`，用于固定 T06 目视叠加图层索引和提右快速审计指标。
