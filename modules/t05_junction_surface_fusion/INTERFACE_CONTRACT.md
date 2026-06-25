# T05 - INTERFACE_CONTRACT

## 定位

本文件是 `t05_junction_surface_fusion` 的稳定接口契约。T05 分为两个阶段：

- Phase 1：路口面融合发布。
- Phase 2：消费 Phase 1 成果，执行 RCSD junctionization 与 SWSD-RCSD 关系生产。

Phase 1 不生产关系表，不输出 `intersection_match_all.geojson`，不打断 `RCSDRoad`，不新增 `RCSDNode`，不消费 relation evidence 作为主输入。

Phase 2 不重新融合路口面，不修改 Phase 1 的 `junction_anchor_surface.gpkg`，只基于 Phase 1 主图层、fusion audit、final nodes、原始 RCSDRoad/RCSDNode 与 T07/T03/T04 relation evidence 做 copy-on-write 拓扑预处理和最终关系发布。旧 T02 relation evidence 仅作为兼容输入保留。

Phase 2 直接消费 T07/T03/T04 当前已有 relation evidence，不要求前序模块新增字段或回改逻辑。若发现前序 evidence 缺失、矛盾或无法支撑场景分流，必须停机回报，不得在 T05 中反推并固化新业务规则。

## 1. Scope

### 1.1 当前正式支持

- 消费已锚定到 SWSD 语义路口的 T02_INPUT / T03 / T04 三类路口面来源。
- 对输入面做 CRS 归一、字段归一、formal accepted 过滤、按 `mainnodeid` 分组、去重、多源融合与发布。
- 输出统一路口面 `junction_anchor_surface.gpkg`。
- 输出 fusion audit 与 `summary.json`。
- Phase 2 消费 `junction_anchor_surface.gpkg` 与 relation evidence。
- Phase 2 输出 `intersection_match_all.geojson`、copy-on-write RCSDRoad/RCSDNode 与 junctionization audit。
- Phase 2 保证 `intersection_match_all.geojson` 中 `target_id` 唯一，一个 SWSD 语义路口只输出一条 relation。

### 1.2 当前非目标

- Phase 1 不建立 SWSD-RCSD 最终关系表。
- Phase 1 不输出 `intersection_match_all.geojson`。
- Phase 1 不执行 RCSDRoad split / cut / break。
- Phase 1 不新增 RCSDNode。
- 不修改 T02/T03/T04 主链算法。
- 不新增 repo CLI、`scripts/`、`tools/`、`Makefile` 或模块独立启动入口。
- Phase 2 不回改 Phase 1 融合结果，不修改 T02/T03/T04 主链算法，不原地修改输入文件。

## 2. Inputs

### 2.1 Runner

```python
run_t05_junction_surface_fusion(
    *,
    t02_rcsdintersection_path,
    t03_surface_path,
    t04_surface_path,
    nodes_path,
    out_root,
    run_id=None,
    t02_layer=None,
    t03_layer=None,
    t04_layer=None,
    nodes_layer=None,
    t02_crs=None,
    t03_crs=None,
    t04_crs=None,
    nodes_crs=None,
)
```

### 2.2 来源

- `T02_INPUT`：`RCSDIntersection` 既有面；必须可解析到 `mainnodeid` 后才可单源发布。
- `T03`：`virtual_intersection_polygons.gpkg`，只消费 formal accepted surface candidate。
- `T04`：`divmerge_virtual_anchor_surface.gpkg`，只消费 `final_state = accepted` 的 feature。
- `nodes.gpkg`：可选，只用于反查 `mainnodeid / kind_2 / patch_id`，不得被修改。若来源面与 `nodes.gpkg` 均无法提供 `mainnodeid`，该面必须跳过。

### 2.3 CRS

所有输入在空间处理前统一到 `EPSG:3857`。GeoJSON / Shapefile 若缺失 CRS，应通过 runner 的 `*_crs` 参数显式传入。

## 3. Normalized Fields

每个输入面归一为：

- `source`
- `source_feature_id`
- `source_case_id`
- `geometry`
- `mainnodeid`
- `patch_id`
- `kind_2`
- `junction_type`

`mainnodeid` 是 Phase 1 主图层准入条件。无法锚定到 SWSD 语义路口的来源面不进入融合组，只进入 skipped 审计。

`junction_type` 映射：

- `T02_INPUT -> rcsd_intersection`
- `T03 kind_2 = 4 -> center_junction`
- `T03 kind_2 = 2048 -> single_sided_t_mouth`
- `T04 kind_2 = 8 -> merge`
- `T04 kind_2 = 16 -> diverge`
- `T04 kind_2 = 128 -> complex_divmerge`
- 无法映射时写 `unknown` 并进入 audit。

## 4. Fusion Rules

主分组键为 `mainnodeid`：

- `mainnodeid` 相同可进入同一融合组。
- `mainnodeid` 为空时不进入主融合流程。
- 不同 `mainnodeid` 即使几何相交，也不得仅凭几何合并。

多源 union 条件：

- `mainnodeid` 一致。
- 来源几何相交、接触或距离不超过 `2.0m`。
- 无不可解决冲突。

不能安全 union 时选择 primary：

- T03/T04 generated accepted surface 优先于 T02_INPUT。
- T03 与 T04 同时出现时按 `kind_2` 域选择 primary，并写 `conflict_reason = t03_t04_same_mainnodeid`。
- 无法判定时不发布冲突融合结果，只写 audit / conflicts。

## 5. Outputs

### 5.1 `junction_anchor_surface.gpkg`

CRS：`EPSG:3857`

字段固定为：

| 字段 | 说明 |
|---|---|
| `surface_id` | 最终路口面唯一 ID。 |
| `mainnodeid` | SWSD 语义路口 ID；主图层中必须非空。 |
| `patch_id` | PatchID；无法反查时为空。 |
| `junction_type` | 最终发布路口类型。 |
| `kind_2` | 原始 SWSD `nodes.kind_2`；无法反查时为空。 |
| `surface_sources` | 最终几何实际使用的来源集合。 |
| `is_multi_source_merged` | 是否多源几何合并，`0 / 1`。 |

`surface_id` 规则：

- `JAS:{mainnodeid}`

### 5.2 Fusion Audit

输出：

- `junction_anchor_surface_fusion_audit.csv`
- `junction_anchor_surface_fusion_audit.json`

审计至少记录：

- `surface_id`
- `fusion_group_id`
- `mainnodeid`
- `patch_id`
- `kind_2`
- `junction_type`
- `surface_sources`
- `is_multi_source_merged`
- `source_count`
- `source_feature_ids`
- `source_case_ids`
- `source_modules`
- `source_patch_ids`
- `geometry_action`
- `fusion_action`
- `conflict_state`
- `conflict_reason`
- `selected_primary_source`
- `dropped_source_ids`
- `geometry_cleaned`
- `notes`

### 5.3 Summary

`summary.json` 至少记录：

- run 与输入输出路径。
- 三类输入面计数。
- 发布、单源、多源、冲突、跳过计数。
- `missing_mainnodeid / missing_patch_id / missing_kind_2` 计数；其中主图层 `missing_mainnodeid_count` 应为 `0`，未锚定面应进入 skipped。
- CRS 与 consistency section。

## 6. Phase 2 Handoff

Phase 2 消费：

- `junction_anchor_surface.gpkg`
- `junction_anchor_surface_fusion_audit.csv/json`
- `summary.json`

Phase 2 可以基于这些成果识别 residual、执行 RCSD junctionization 和关系表生产，但这些工作不属于 Phase 1。

## 7. Phase 2 Runner

```python
run_t05_phase2_rcsd_junctionization_and_relation(
    *,
    junction_surface_path,
    fusion_audit_path,
    nodes_path,
    rcsdroad_path,
    rcsdnode_path,
    t02_relation_evidence_path,
    t03_relation_evidence_path,
    t04_relation_evidence_path,
    out_root,
    run_id=None,
    junction_surface_layer=None,
    nodes_layer=None,
    rcsdroad_layer=None,
    rcsdnode_layer=None,
    t04_surface_path=None,
    t04_summary_path=None,
    t04_audit_path=None,
    t04_case_root=None,
    crs_override=None,
    min_split_gap_m=2.0,
    min_endpoint_gap_m=2.0,
    progress=False,
    progress_interval=1000,
    readonly_workers=1,
    t07_relation_evidence_path=None,
    next_road_id_start=None,
    next_node_id_start=None,
)
```

Phase 2 输出：

- `intersection_match_all.geojson`，CRS 为 CRS84 / WGS84 lon-lat，字段固定为 `target_id / base_id / status / level / is_highway`。
- `rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。
- `rcsdroad_split.gpkg`、`rcsdnode_generated.gpkg`、`rcsdnode_grouped.gpkg`。
- `rcsd_junctionization_audit.csv/json`、`intersection_match_all_audit.csv/json`、`blocking_errors.csv/json`、`relation_cardinality_errors.csv/json`、`summary.json`。
- `module_relation_audit_summary.csv/json`：按 T07/T02/T03/T04 输入与场景统计最终关系生产效果。
- `t05_junction_anchor_funnel_summary.json`：路口级锚定漏斗，覆盖顶层漏斗、T07/T03/T04 来源模块漏斗、T05 失败分类。
- `t05_junction_anchor_source_funnel.csv`：T07/T03/T04 来源模块漏斗，供 PPT / Excel 汇总。
- `t05_junction_anchor_failure_reasons.csv`：T05 发布失败的一级分类、scene、reason 和数量。

Phase 2 失败统一 `status = 1`、`base_id = 0`。成功关系的 `base_id` 必须是 RCSD 语义路口主 node id，不得写普通 RCSDRoad id。T03-A 多 RCSDNode 与 T04 complex 多 RCSDNode 先归组再建关系；T03 road-only 与 T04 fallback road-only 才进入 RCSDRoad split。被 split 的原始 RCSDRoad 不进入 active `rcsdroad_out.gpkg`。

Phase 2 在入口统一对 SWSD 语义路口主键做 canonical normalization：evidence `target_id`、surface `mainnodeid`、nodes `id/mainnodeid` 中的整数 ID 字符串 / 浮点字符串表达差异必须归一，例如 `622700016` 与 `622700016.0` 视为同一 target。`intersection_match_all.geojson`、junctionization audit、relation audit 与 blocking/cardinality 输出中的 `target_id` 必须使用 canonical 值。

路口级锚定漏斗的语义路口范围固定为 `kind_2 in {4,8,16,64,128,2048}`。统计时按 `mainnodeid` 优先、否则 `id` 的 canonical junction id 去重；单 node 路口不得因缺少多 node group 被过滤。T07/T03/T04 来源模块漏斗只统计该语义路口范围内的 target，并复用 Phase 2 evidence classifier 分为成功 evidence、无 RCSD、失败 evidence、T05 handoff、T05 采用、T05 成功/失败等指标。来源模块漏斗是贡献统计，不保证 T07/T03/T04 互斥；顶层漏斗按最终 relation target 去重。

Phase 2 不改写 final SWSD `nodes.gpkg`，也不再输出 SWSD node copy-on-write 标记层。若某个 SWSD 语义路口在 Phase 2 审计中确认 `no_related_rcsd`，仅通过 relation failure、junctionization audit 与 module relation audit 表达，不额外改写 `has_evd / is_anchor`。

Road-only 投影点落在 RCSDRoad 起终点 `min_endpoint_gap_m` 范围内时，不打断 road，不新增 RCSDNode；Phase 2 复用最近端点的 `snodeid / enodeid` 对应 RCSDNode 作为语义路口候选。若命中多个端点 RCSDNode，则按主 RCSDNode 选择规则归组后输出唯一 relation；若端点 RCSDNode 缺失，则保持失败并写 audit。

`kind_2 = 64` 的 SWSD 环岛语义路口由 Phase 2 专门处理：以该 SWSD 语义路口下所有 node 点查询覆盖这些点的 Phase 1 路口面；只有每个 node 都被至少一个路口面覆盖时，才将这些路口面与 `RCSDRoad.roadtype = 8` 的环岛 road `10m` buffer 合并成环岛候选面。Phase 2 再用该面筛选 RCSD 语义路口，要求候选 RCSD 语义路口组内所有 node 均被环岛面覆盖，并且这些 RCSD 语义路口之间通过 `roadtype = 8` 的 RCSDRoad 连通。符合条件的 RCSDNode 统一归组，选择距离 SWSD 环岛语义点最近的 node 作为主 RCSD mainnode，组内所有 node 的 `mainnodeid` 均写该主 node id，然后输出唯一 SWSD-RCSD relation。该场景不打断 RCSDRoad，也不新增 RCSDNode。

`intersection_match_all.geojson` 规则：

- `target_id` 必须唯一。
- 一个 SWSD 语义路口只允许输出一条 relation。
- `level = final nodes.gpkg` 中 SWSD representative node `grade - 1`；缺失、为空或非法时为 `-1`。
- `is_highway = final nodes.gpkg` 中 SWSD representative node `closed_con - 1`；缺失、为空或非法时为 `-1`。
- 多个 RCSDNode 可归组时必须先归组，再输出一条 relation。
- 多个 `base_id` 无法合并时写入 `blocking_errors.csv/json`，不写主表 relation，`summary.passed = false`。
- 最终成功关系必须通过 cardinality QC：同一 `target_id` 不得挂接多个 `base_id`，也不得存在重复 success target。若发现 `1:N` 或重复 success target，写入 `relation_cardinality_errors.csv/json`，记录 `introduced_by_module / source_modules / source_case_ids / scenes / reasons`，相关错误 relation 不进入 `intersection_match_all.geojson` 主表，并令 `summary.passed = false`。若发现同一 `base_id` 被多个 `target_id` 挂接，写入 `many_target_to_one_base` 审计，但保留关系，不作为阻断错误；T06 后续按 Segment 端点 distinct、buffer 与方向性继续判定。
- T07/T03/T04 当前已产出的成功 relation evidence 是 Phase 2 的优先输入。只要 `status_suggested = 0` 且 `base_id_candidate` 为有效 RCSD 语义路口主 node id 或 group id，Phase 2 先按 direct relation 消费，不因同一 row 同时存在 `required_rcsdnode_ids` 而重新归组。
- T10 `t10_upstream_side_group_endpoint_candidates.csv/json` 是 Phase 2 的可选补充输入。只有同一 SWSD `target_id` 已存在 T07/T03/T04/T02 成功 relation，或存在 T03/T04 road-only split 决策时，`T10_SIDE_GROUP` endpoint candidate 才能参与 `group_existing_rcsd_nodes`，用于把该 endpoint 侧的多个 RCSDNode copy-on-write 归组为同一个 RCSD 语义路口；若只有 T10 endpoint candidate 而无前置成功 relation / road-only split 决策，Phase 2 必须保持失败 relation，不得单独创建 SWSD-RCSD relation。对 road-only split 场景，Phase 2 必须先执行 road split 或 endpoint reuse，再将新生成 / 复用的 RCSDNode 与 T10 额外候选节点归组；T10 不得覆盖 road-only split。
- T10 `t10_upstream_pair_anchor_endpoint_clusters.csv/json` 是 Phase 2 的可选补充输入。只有 `auto_consumable_by_t05=true` 且同一 SWSD `target_id` 已存在 T07/T03/T04/T02 成功 relation，或存在 T03/T04 road-only split 决策时，`T10_PAIR_ANCHOR_CLUSTER` endpoint cluster 才能参与 `group_existing_rcsd_nodes`，用于吸收 T06 pair-anchor 诊断确认的短连接 endpoint RCSDNode 簇；若只有 T10 pair-anchor cluster 而无前置成功 relation / road-only split 决策，Phase 2 必须保持失败 relation，不得单独创建 SWSD-RCSD relation。
- 例外：T04 `road_surface_fork` partial handoff 可同时提供 `base_id_candidate / required_rcsd_node_ids` 与 `semantic_required_rcsd_node_ids`。当 `status_suggested = 0`、`swsd_relation_type = partial`，且 `semantic_required_rcsd_node_ids` 与 `base_id_candidate` 指向不同 RCSDNode 时，Phase 2 必须将两者按 `group_existing_rcsd_nodes` 归组为同一 RCSD 语义路口，再发布唯一 relation；不得在 T06 通过双向 Segment 兜底修正。
- T04 `fail4_fallback` relation-only target 可以没有 T04 accepted surface；只要 final nodes representative `is_anchor = fail4_fallback`，且 T04 relation evidence 中 `status_suggested = 0 / base_id_candidate = RCSD 语义路口 group id / surface_candidate_present = 0`，Phase 2 必须输出 `status = 0`。
- T07 历史路口锚定 relation-only target 可以没有 Phase 1 surface；只要 T07 relation evidence 中 `status_suggested = 0 / base_id_candidate = RCSD 语义路口主 node id 或 group id`，Phase 2 必须输出 `status = 0`。

T04 fallback 场景可补读 `divmerge_virtual_anchor_surface.gpkg`、summary、audit 或 case-level audit 中的 `surface_scenario_type / rcsd_alignment_type / fallback_rcsdroad_ids / reference_point` 等正式字段；不得从 review PNG 或几何近邻反推。

全量运行性能观测：

- `progress=True` 时，控制台输出 Phase 2 前置阶段进展、输入体量、预分类 plan、只读/可变 target 计数、按 `progress_interval` 稀疏 target 进度和总耗时。前置阶段至少覆盖 `read_vectors / build_indexes / read_evidence_tables / load_t04_supplements / merge_evidence / target_contexts / roundabout_aggregations / direct_nearby_node_index / decision_plan`，避免全量运行长时间停留在 `start` 后无法定位。
- `readonly_workers` 只用于并行处理不修改 RCSDRoad / RCSDNode 的关系构建分支；RCSDRoad split、RCSDNode grouping、新增 id 分配当前保持串行。
- `next_road_id_start / next_node_id_start` 仅用于解包后的小样本本地测试复现全量运行 ID 分配；常规全量运行不传，默认仍使用原始 RCSDRoad / RCSDNode 全局 `max(id)+1`。
- `summary.performance.data_volume` 记录输入 feature / evidence 体量。
- `summary.performance.plan` 记录 direct / grouping / road_split / no_related 等预分类计数，以及 unique split road / group node 候选数。
- `summary.performance.timings_sec` 记录阶段级耗时，不记录 per-target 明细，避免大数据下打点体量失控。
- `summary.performance.output_timings_sec` 与 `summary.performance.output_sizes_bytes` 记录逐输出文件耗时与大小；`progress=True` 时逐文件打印 `writing/done`。
- 大体量 GPKG 输出使用分批 `writerecords` 写出，保持 copy-on-write 完整输出，不跳过 `rcsdroad_out.gpkg / rcsdnode_out.gpkg`。

模块关系审计统计：

- `source_module`：`T07 / T02_INPUT / T03 / T04`。
- `input_count`：该模块 relation evidence 输入行数。
- `classified_input_count / unclassified_input_count`：可进入 T05 场景分类的输入行数与缺少 `target_id` 等无法分类的行数。
- `phase2_target_input_count`：输入 target 已进入 Phase 1 surface 并参与 Phase 2 的行数。
- `scenario = pre_failed_no_relation_overall_failure`：前置失败、无可用 RCSD 关联。
- `scenario = pre_success_rcsd_semantic_relation`：前置成功，存在 RCSD 语义路口或可归组 RCSDNode。
- `scenario = pre_success_rcsdroad_junctionization`：前置成功，只有 RCSDRoad，需要构建 RCSD 路口。
- `scenario = pre_success_no_rcsd_overall_failure`：前置成功，但确认无 RCSD 关联，最终应为失败关系。
- 每个 scenario 输出 `relation_success_count / relation_failure_count / missing_relation_count / blocking_error_count / overall_failure_count`。

路口级锚定漏斗统计：

- `top_level_funnel.semantic_junction_total`：final nodes 中 `kind_2 in {4,8,16,64,128,2048}` 的 SWSD 语义路口总数。
- `top_level_funnel.evidence_junction_total`：T07/T03/T04 任一 relation evidence 覆盖到的语义路口数。
- `top_level_funnel.t05_phase2_target_total / relation_published_total`：进入 T05 Phase2 并发布 relation 的语义路口数。
- `top_level_funnel.relation_success_total / relation_failure_total`：T05 最终 `status=0/1` 的语义路口数。
- `top_level_funnel.graph_consumable_success_total / graph_unconsumable_success_total`：成功 relation 中可被最终 RCSD road graph 消费 / 不可消费的语义路口数。
- `top_level_funnel.non_semantic_phase2_target_total`：进入 T05 Phase2 但不在上述 `kind_2` 范围内的 target 数，正常应为 0，用于发现上游范围泄漏。
- `source_module_funnel.input_junction_total`：该来源模块 evidence 覆盖到的语义路口数，不按 evidence 行数统计。
- `source_module_funnel.success_evidence_junction_total / no_rcsd_junction_total / failure_evidence_junction_total`：复用 T05 Phase2 classifier 对来源 evidence 做路口级归类。
- `source_module_funnel.handoff_to_t05_total / accepted_by_t05_total / success_after_t05_total / failure_after_t05_total`：该来源在 T05 发布链路中的进入、采用和最终结果统计。
- `t05_failure_breakdown.no_related_failure_total / upstream_failure_total / t05_closure_failure_total / missing_evidence_failure_total / other_failure_total`：T05 `status=1` relation 的顶层失败分类。

### 7.1 Relation Graph Consumability Audit

Phase 2 额外输出：
- `relation_graph_consumability_audit.csv`
- `relation_graph_consumability_audit.json`

该审计不改写 `intersection_match_all.geojson`，只检查已发布 relation 是否能被最终 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 的 RCSD road graph 消费：
- `base_node_graph_incident`：`base_id` 本身存在于 `rcsdnode_out`，且作为 `rcsdroad_out` 的端点。
- `base_node_group_graph_incident`：`base_id` 本身存在于 `rcsdnode_out`，并且其 `mainnodeid` group 内至少一个成员是 `rcsdroad_out` 端点。
- `base_mainnodeid_graph_incident`：`base_id` 只作为 `mainnodeid` group id 存在，且 group 内至少一个成员是 `rcsdroad_out` 端点。
- `base_node_not_incident_to_rcsdroad` / `base_mainnodeid_not_incident_to_rcsdroad`：`base_id` 可在 `rcsdnode_out` 或 group 中定位，但无法落到当前 RCSD road graph 的端点。
- `base_id_not_found_in_rcsdnode_out`：`status = 0` relation 的 `base_id` 无法在 `rcsdnode_out` 的 `id/mainnodeid` 中定位。

`summary.json` 记录 `relation_graph_consumability_row_count / relation_graph_consumable_count / relation_graph_unconsumable_success_count / relation_graph_consumability_status_counts / relation_graph_consumability_passed`。该审计是质量追溯信号，不作为本阶段强制阻断项；需要前置修复时，应回到 T03/T04/T07 relation evidence 或 T05 junctionization 关系发布逻辑，不得在 T06/Step3 以最近点或 case 级补丁强行改写。

T07 Step2 `existing_rcsdintersection_matched` 的 `base_id_candidate` 来源是 `RCSDIntersection` 面 ID；T05 Phase2 在发布成功 relation 前必须将其证明为可消费 RCSD 语义节点：
- 若 `base_id_candidate` 已存在于 `rcsdnode_out.id/mainnodeid`，可按 direct relation 消费。
- 若 `base_id_candidate` 不可定位，但对应 `junction_anchor_surface` 内恰好覆盖 1 个 RCSD 语义节点，可将 relation 重绑定到该 RCSD 语义节点，并在 audit 中记录 `existing_rcsdintersection_surface_1v1_rcsdnode_rebased`。
- 若 surface 内覆盖多个 RCSD 语义节点，按既有 `group_existing_rcsd_nodes` 逻辑处理。
- 若 `base_id_candidate` 不可定位且 surface 内无法证明唯一或多个 RCSD 语义节点，必须输出 `status = 1 / base_id = 0` 的失败 relation，并记录 `t07_rcsdintersection_base_not_in_rcsdnode_out`；不得使用最近点、固定距离或 T06 替换结果反推 base。

## 8. Innernet Experiment Entrypoint

T05 提供 repo 级内网联合实验入口：

```bash
.venv/bin/python scripts/t05_innernet_experiment.py \
  --t02-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_internal_step1_step2/stage2/t02_stage2_internal_20260519_115056 \
  --t03-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t03_internal_full_input/t03_internal_full_input_innernet_flat_review_20260519_130230 \
  --t04-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t04_internal_full_input/t04_internal_full_20260520_000716 \
  --rcsdroad /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment \
  --readonly-workers 4 \
  --progress-interval 1000
```

`--t07-dir / --t07-evidence / --t07-input` 用于当前 T07 主流程；默认从 `--t07-dir` 自动发现 `t07_swsd_rcsd_relation_evidence.csv/json` 与 `t07_rcsdintersection_anchor_surface.gpkg`。进入 T07 模式后默认不再自动读取旧 T02 evidence；`--t02-dir / --t02-evidence / --t02-input` 仅作为旧批次兼容路径保留，需要对比旧 T02 时显式传 `--include-legacy-t02-evidence`。

`--t10-side-group-endpoint-candidates` 与 `--t10-pair-anchor-endpoint-clusters` 是可选上游反馈补充输入，只能按本契约的 supplement 规则参与 RCSDNode grouping，不改变 Phase 1 输入，也不得单独创建 relation。

该入口顺序执行：

1. T03 relation evidence handoff 补齐，默认 `--t03-accepted-only`。
2. Phase 1 `junction_anchor_surface.gpkg` 发布。
3. Phase 2 `intersection_match_all.geojson`、copy-on-write RCSD 输出和审计发布。

## 9. T05 Junctionization Evidence Bundle

T05 提供按 SWSD 语义路口 ID 导出的 Phase 2 junctionization 输入证据包工具，用于 RCSDRoad 打断、RCSDNode 归组与新增 RCSDNode 构建问题复现。

模块内 runner：

```python
run_t05_export_junctionization_bundle(
    *,
    target_ids,
    out_dir,
    junction_surface_path,
    nodes_path,
    rcsdroad_path,
    rcsdnode_path,
    fusion_audit_path=None,
    t02_relation_evidence_path=None,
    t07_relation_evidence_path=None,
    t03_relation_evidence_path=None,
    t04_relation_evidence_path=None,
    t04_surface_path=None,
    t04_summary_path=None,
    t04_audit_path=None,
    t04_case_root=None,
    phase2_root=None,
    context_buffer_m=80.0,
    max_text_size_bytes=250 * 1024,
)
```

使用方式示例：

```python
from rcsd_topo_poc.modules.t05_junction_surface_fusion import run_t05_export_junctionization_bundle

artifacts = run_t05_export_junctionization_bundle(
    target_ids=["692772", "1029610"],
    out_dir="/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_junctionization_bundles",
    junction_surface_path="/path/to/junction_anchor_surface.gpkg",
    fusion_audit_path="/path/to/junction_anchor_surface_fusion_audit.csv",
    nodes_path="/path/to/final/nodes.gpkg",
    rcsdroad_path="/path/to/RCSDRoad.gpkg",
    rcsdnode_path="/path/to/RCSDNode.gpkg",
    t07_relation_evidence_path="/path/to/t07_swsd_rcsd_relation_evidence.csv",
    t03_relation_evidence_path="/path/to/t03_swsd_rcsd_relation_evidence.csv",
    t04_relation_evidence_path="/path/to/t04_swsd_rcsd_relation_evidence.csv",
    t04_surface_path="/path/to/divmerge_virtual_anchor_surface.gpkg",
    t04_summary_path="/path/to/divmerge_virtual_anchor_surface_summary.csv",
    t04_audit_path="/path/to/divmerge_virtual_anchor_surface_audit.gpkg",
    t04_case_root="/path/to/t04/cases",
    phase2_root="/path/to/t05_phase2_full",
)
```

该能力仅提供模块内 callable，不新增 repo CLI 或 scripts 入口。

输出规则：

- 默认 `max_text_size_bytes = 250KB`；多 `target_id` 打包超过阈值时自动输出 `t05_junctionization_bundle_partNNN.txt` 分片。
- 单个 target 自身超过阈值时保留为独立 oversized 分片，并在 `t05_junctionization_bundle_index.json` 标记 `oversized = true`。
- 每个 bundle payload 是 zip，外层为可复制 txt；每个 target 在 zip 内按 `<target_id>/` 分目录。
- case 目录包含 `README.md / local_test_config.json / junction_anchor_surface.geojson / nodes.geojson / rcsdroad.geojson / rcsdnode.geojson / relation_evidence.json / fusion_audit.json / phase2_audit.json / manifest.json`。
- relation evidence 额外按模块拆分为 `t02_swsd_rcsd_relation_evidence.json / t07_swsd_rcsd_relation_evidence.json / t03_swsd_rcsd_relation_evidence.json / t04_swsd_rcsd_relation_evidence.json`，可直接传给 Phase 2 runner。
- T04 补读材料输出为 `t04_surface.geojson / t04_summary.json / t04_audit.json / t04_case_root/<case_id>/...`，用于覆盖 fallback 场景的本地复现。
- 若传入 `phase2_root`，case 目录会包含 `expected_intersection_match_all.geojson / expected_rcsdroad_split.geojson / expected_rcsdnode_generated.geojson / expected_rcsdnode_grouped.geojson / expected_rcsdroad_out_slice.geojson / expected_rcsdnode_out_slice.geojson`，用于本地断言。
- `local_test_config.json.runner_kwargs` 会记录从 Phase2 audit 推导的 `next_road_id_start / next_node_id_start`，用于小样本运行时复现全量 ID 分配。
- `rcsdroad.geojson` 优先纳入 relation evidence / Phase2 audit 中显式引用的 `support / selected / fallback / required / original` RCSDRoad，并补充目标 surface / SWSD node 周边 `context_buffer_m` 内的 RCSDRoad。
- `rcsdnode.geojson` 纳入 evidence / audit 显式引用的 RCSDNode、被选 RCSDRoad 的 `snodeid / enodeid`，并补充目标 context 内 RCSDNode。

## 9.1 2026-06-14 补充规则：T07 fail1 多 RCSDIntersection 分组

- Phase2 允许消费 T07 `relation_state = multiple_intersections_for_group` 的 relation evidence，但前提是 `base_id_candidate` 已显式给出两个及以上非零 RCSD base id。
- 满足上述条件时，Phase2 以 `group_existing_rcsd_nodes` 构建一个 RCSD 语义路口关系，审计 reason 为 `t07_multiple_intersections_for_group`，并保持 `multi_base_relation = 1`。
- Phase2 不从 `matched_rcsdintersection_ids` 反推 RCSDNode 语义；若 T07 未提供明确 `base_id_candidate`，该场景仍作为失败 evidence 处理。
- 该规则只处理 T07 已识别的 SWSD 1:N RCSDIntersection 工艺差异，不修改 T03/T04 主链算法，也不放宽 T06 Segment buffer 审计。

## 9.2 2026-06-14 补充规则：T07 direct relation 邻近非主 RCSDNode 归组

- 当 T07 relation evidence 已确认 `existing_rcsdintersection_matched`、`status_suggested = 0`，且只有一个有效 `base_id_candidate` 时，Phase2 默认仍按 direct relation 发布该 SWSD-RCSD 关系。
- 若同一 SWSD target 的 Phase1 surface 外 `5m` 内、且 SWSD 语义路口投影点 `50m` 内存在 `mainnodeid = 0` 或空值的 RCSDNode，Phase2 可将这些邻近非主节点与 direct base id 一起执行 copy-on-write `mainnodeid` 归组，并以 `group_existing_rcsd_nodes` 输出唯一 relation。
- 该归组只用于补齐 T07 已锚定路口面边缘遗漏的 RCSD 拓扑节点，使下游 T06 在同一个 RCSD 语义路口上消费分歧/合流通道；不得基于任意远距离 RCSDRoad 或未知字段反推路口归属。
- 以下节点必须排除在该归组之外：其它成功 relation 的 base id；T03/T04 road-only split、endpoint reuse、support/fallback/required road 证据涉及的原始 RCSDRoad 起终点；以及同一 RCSDNode 同时命中多个 direct base 的冲突候选。
- 成功归组必须写入 `rcsd_junctionization_audit.csv/json`，`reason = existing_rcsdintersection_nearby_nonbase_node_grouping`，并记录 `original_node_ids / grouped_node_ids / selected_main_node_id`。
- 该规则不修改 Phase1 surface，不新增 RCSDRoad/RCSDNode，不放宽 T06 buffer 与方向性检查；若归组后触发 relation cardinality QC，仍按 Phase2 失败输出并要求上游证据继续收敛。

## 10. T03 Relation Evidence Backfill

T05 提供 T03 -> Phase 2 handoff 补齐工具。该能力只作为旧 T03 产物兼容路径；当前 T03 已提供完整 relation evidence 时，Phase 2 应直接消费原始 `t03_swsd_rcsd_relation_evidence.*`，不需要补齐。

```python
backfill_t03_relation_evidence(
    *,
    t03_run_root,
    out_root=None,
    relation_evidence_path=None,
    case_ids=None,
    accepted_only=False,
)
```

该工具只消费 T03 当前已输出的批次 relation evidence 与 `cases/<case_id>/step6_status.json` / `step6_audit.json`，补齐 T05 Phase 2 场景分流所需字段：

- `required_rcsdnode_ids / required_rcsdroad_ids`
- `support_rcsdnode_ids / support_rcsdroad_ids`
- `excluded_rcsdnode_ids / excluded_rcsdroad_ids`
- `base_id_candidate / status_suggested / relation_state / reason`

输出为独立 handoff 文件，不覆盖 T03 原始输出：

- `t03_swsd_rcsd_relation_evidence_backfilled.csv`
- `t03_swsd_rcsd_relation_evidence_backfilled.json`
- `t03_swsd_rcsd_relation_evidence_backfill_audit.csv/json`
- `t03_swsd_rcsd_relation_evidence_backfill_summary.json`

补齐规则：

- `required_rcsdnode_ids` 非空：`relation_state = success_required_rcsd_junction`，`status_suggested = 0`，`base_id_candidate = required_rcsdnode_ids`。
- `support_rcsdroad_ids` 非空且无 required RCSDNode：`relation_state = rcsd_present_not_junction`，`status_suggested = 1`，`base_id_candidate = -1`。
- 若 case 级 step6 文件缺失，不反推字段，只保留原 row 并写 audit。

内网脚本入口：

```bash
.venv/bin/python scripts/t05_backfill_t03_relation_evidence_innernet.py \
  --t03-run-root /path/to/t03/run \
  --relation-evidence-path /path/to/t03_swsd_rcsd_relation_evidence.csv \
  --out-root /path/to/t05_phase2_handoff \
  --accepted-only
```

标准 T03 run root 使用 `cases/<case_id>/step6_status.json`；测试包或聚合目录允许一层嵌套的 `*/cases/<case_id>/step6_status.json`，用于把多个 T03 case run 汇总为同一份 T05 Phase 2 handoff evidence。
