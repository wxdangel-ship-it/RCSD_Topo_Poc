# T05 Junction Surface Fusion

`t05_junction_surface_fusion` 包含 T05 两个独立阶段：Phase 1 负责统一路口面融合发布，Phase 2 消费 Phase 1 成果执行 RCSD junctionization 与 SWSD-RCSD 关系生产。

## 阶段边界

T05 分两个阶段：

- Phase 1：消费已锚定到 SWSD 语义路口的 T02_INPUT / T03 / T04 路口面候选，完成归一化、分组、去重、合并与发布。
- Phase 2：独立消费 Phase 1 成果、final nodes、原始 RCSDRoad/RCSDNode 与 T07/T03/T04 relation evidence，输出 copy-on-write RCSD 成果和 `intersection_match_all.geojson`。旧 T02 evidence 仅作为兼容输入保留。

Phase 1 不输出 `intersection_match_all.geojson`，不建立关系表，不打断 RCSDRoad，不新增 RCSDNode。Phase 2 允许 RCSDRoad split、RCSDNode insert 与 RCSDNode grouping，但不得修改 Phase 1 融合结果，也不得原地修改输入文件。

## Callable Runner

当前没有 repo CLI。Phase 1 / Phase 2 主执行面仍是模块内 callable runner：

```python
from rcsd_topo_poc.modules.t05_junction_surface_fusion import run_t05_junction_surface_fusion

artifacts = run_t05_junction_surface_fusion(
    t02_rcsdintersection_path="RCSDIntersection.gpkg",
    t03_surface_path="virtual_intersection_polygons.gpkg",
    t04_surface_path="divmerge_virtual_anchor_surface.gpkg",
    nodes_path="nodes.gpkg",
    out_root="outputs/_work/t05_junction_surface_fusion",
    run_id="manual_run",
)
```

Phase 2 callable runner：

```python
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner import (
    run_t05_phase2_rcsd_junctionization_and_relation,
)

artifacts = run_t05_phase2_rcsd_junctionization_and_relation(
    junction_surface_path="junction_anchor_surface.gpkg",
    fusion_audit_path="junction_anchor_surface_fusion_audit.csv",
    nodes_path="nodes.gpkg",
    rcsdroad_path="RCSDRoad.gpkg",
    rcsdnode_path="RCSDNode.gpkg",
    t02_relation_evidence_path=None,
    t07_relation_evidence_path="t07_swsd_rcsd_relation_evidence.csv",
    t03_relation_evidence_path="t03_swsd_rcsd_relation_evidence.csv",
    t04_relation_evidence_path="t04_swsd_rcsd_relation_evidence.csv",
    t04_surface_path="divmerge_virtual_anchor_surface.gpkg",
    t04_summary_path="divmerge_virtual_anchor_surface_summary.csv",
    t04_audit_path="divmerge_virtual_anchor_surface_audit.gpkg",
    t04_case_root="cases",
    out_root="outputs/_work/t05_phase2",
    run_id="manual_run",
    progress=True,
    progress_interval=1000,
    readonly_workers=4,
)
```

`next_road_id_start / next_node_id_start` 是证据包解包后的小样本测试专用参数，用于复现全量运行中的新增 ID；常规全量运行不传。

T03 -> T05 Phase 2 handoff 补齐提供一个内网脚本入口。该脚本只读取现有 T03 run root 中的 `t03_swsd_rcsd_relation_evidence.*` 与 `cases/<case_id>/step6_status.json` / `step6_audit.json`，写出补齐后的 T05 可消费 evidence，不修改 T03 主链或原始输出：

```bash
.venv/bin/python scripts/t05_backfill_t03_relation_evidence_innernet.py \
  --t03-run-root /path/to/t03/run \
  --relation-evidence-path /path/to/t03_swsd_rcsd_relation_evidence.csv \
  --out-root /path/to/t05_phase2_handoff \
  --accepted-only
```

T05 Phase 1 + Phase 2 内网联合实验提供 repo 级入口。当前主流程把 T07/T03/T04 成果目录、原始 RCSDRoad/RCSDNode、final nodes 与既有 `RCSDIntersection` handoff surface 作为参数，先按 `--t03-backfill-mode` 判断是否需要兼容旧 T03 evidence，再执行 Phase 1 surface fusion 与 Phase 2 relation 发布；默认 `auto` 在当前 T03 evidence 完整时直接消费原始 T03 evidence：

```bash
.venv/bin/python scripts/t05_innernet_experiment.py \
  --t07-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t07_semantic_junction_anchor/<run> \
  --t03-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t03_internal_full_input/t03_internal_full_input_innernet_flat_review_20260519_130230 \
  --t04-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t04_internal_full_input/t04_internal_full_20260520_000716 \
  --rcsdroad /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment \
  --readonly-workers 4 \
  --progress-interval 1000
```

`--t07-dir` 会自动发现 `t07_swsd_rcsd_relation_evidence.csv/json` 与 `t07_rcsdintersection_anchor_surface.gpkg`；也可通过 `--t07-evidence / --t07-input` 显式传入。进入 T07 模式后默认不再自动读取旧 T02 evidence；`--t02-dir / --t02-evidence / --t02-input` 仅作为旧批次兼容路径保留，需要对比旧 T02 时显式传 `--include-legacy-t02-evidence`。

T05 Phase 2 提供按 SWSD 语义路口 ID 导出的 junctionization 输入证据包 callable。该工具用于 RCSDRoad 打断 / RCSDNode 归组 / 新 RCSDNode 构建问题复现，按 `target_id/` 组织输入切片，默认单个 txt bundle 超过 `250KB` 时自动分片；不新增 repo CLI 或 scripts 入口：

```python
from rcsd_topo_poc.modules.t05_junction_surface_fusion import run_t05_export_junctionization_bundle

artifacts = run_t05_export_junctionization_bundle(
    target_ids=["692772", "1029610"],
    out_dir="/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_junctionization_bundles",
    junction_surface_path="/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_t07/t05_phase1_full/junction_anchor_surface.gpkg",
    fusion_audit_path="/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_t07/t05_phase1_full/junction_anchor_surface_fusion_audit.csv",
    nodes_path="/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg",
    rcsdroad_path="/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg",
    rcsdnode_path="/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg",
    t07_relation_evidence_path="/path/to/t07_swsd_rcsd_relation_evidence.csv",
    t03_relation_evidence_path="/path/to/t03_swsd_rcsd_relation_evidence_backfilled.csv",
    t04_relation_evidence_path="/path/to/t04_swsd_rcsd_relation_evidence.csv",
    t04_surface_path="/path/to/divmerge_virtual_anchor_surface.gpkg",
    t04_summary_path="/path/to/divmerge_virtual_anchor_surface_summary.csv",
    t04_audit_path="/path/to/divmerge_virtual_anchor_surface_audit.gpkg",
    t04_case_root="/path/to/t04/cases",
    phase2_root="/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_t07/t05_phase2_full",
)
```

每个 case 目录包含 `README.md / local_test_config.json / junction_anchor_surface.geojson / nodes.geojson / rcsdroad.geojson / rcsdnode.geojson / relation_evidence.json / fusion_audit.json / phase2_audit.json / manifest.json`。同时按模块拆分 relation evidence，补齐 T04 supplement 片段，并在提供 `phase2_root` 时写入 expected output 切片：`expected_intersection_match_all.geojson / expected_rcsdroad_split.geojson / expected_rcsdnode_generated.geojson / expected_rcsdnode_grouped.geojson / expected_rcsdroad_out_slice.geojson / expected_rcsdnode_out_slice.geojson`。`local_test_config.json.runner_kwargs` 会记录本地小样本复现全量新增 ID 所需的 `next_road_id_start / next_node_id_start`。输出目录同时写 `t05_junctionization_bundle_index.json`，记录每个分片包含的 target、大小与是否单 case 超限。

## 输入

- `T02_INPUT`：外部既有 `RCSDIntersection` 面；必须可解析到 `mainnodeid`。
- `T03`：`virtual_intersection_polygons.gpkg` 中 formal accepted surface candidate。
- `T04`：`divmerge_virtual_anchor_surface.gpkg` 中 `final_state = accepted` 的 surface。
- `nodes.gpkg`：可选，用于补充 `mainnodeid / kind_2 / patch_id`。若缺失且来源面无法提供 `mainnodeid`，该面不会进入主图层。

## 输出

`<out_root>/<run_id>/` 下输出：

- `junction_anchor_surface.gpkg`
- `junction_anchor_surface_fusion_audit.csv`
- `junction_anchor_surface_fusion_audit.json`
- `summary.json`
- 可选 `junction_anchor_surface_skipped.*`
- 可选 `junction_anchor_surface_conflicts.gpkg`

主图层只发布 7 个字段：

- `surface_id`
- `mainnodeid`
- `patch_id`
- `junction_type`
- `kind_2`
- `surface_sources`
- `is_multi_source_merged`

`junction_anchor_surface.gpkg` 是 Phase 2 的核心输入。

未能锚定到 SWSD 语义路口的来源面不会发布到主图层，只写入 `junction_anchor_surface_skipped.*`。

## Phase 2 输出

`<out_root>/<run_id>/` 下输出：

- `intersection_match_all.geojson`
- `rcsdroad_out.gpkg`
- `rcsdnode_out.gpkg`
- `rcsdroad_split.gpkg`
- `rcsdnode_generated.gpkg`
- `rcsdnode_grouped.gpkg`
- `swsdnode_out.gpkg`
- `rcsd_junctionization_audit.csv/json`
- `intersection_match_all_audit.csv/json`
- `blocking_errors.csv/json`
- `module_relation_audit_summary.csv/json`
- `swsdnode_yes_nr_audit.csv/json`
- `relation_cardinality_errors.csv/json`
- `summary.json`

失败关系统一 `base_id = 0`。如果同一 SWSD 路口只生成 1 个 RCSDNode，则 `mainnodeid = null`；如果生成或归组多个 RCSDNode，则组内所有 RCSDNode 包括主节点自己 `mainnodeid` 都填主节点 id。

`intersection_match_all.geojson` 中 `target_id` 必须唯一，一个 SWSD 语义路口只输出一条 relation。多个 RCSD 候选可合并时先归组；无法合并时写 `blocking_errors.*`，不在主表中输出该 `target_id`。`level` 使用 final nodes 的 `grade - 1`，`is_highway` 使用 `closed_con - 1`；缺失或非法时填 `-1`。

Phase 2 内置最终 relation 基数质检。若成功关系中存在同一 `target_id` 对多个 `base_id`、多个 `target_id` 对同一 `base_id`，或重复 success target，模块会输出 `relation_cardinality_errors.csv/json`。错误行包含 `introduced_by_module / source_modules / source_case_ids / scenes / reasons`，用于判断是 T07/T03/T04 evidence 引入，还是 T05 聚合逻辑引入；相关错误关系会从 `intersection_match_all.geojson` 主表剔除，存在错误时 `summary.passed = false`。

Road-only 场景中，若投影点距离 RCSDRoad 起终点小于 `min_endpoint_gap_m`，Phase 2 不生成极短 split 段，改为复用对应 `snodeid / enodeid` 的已有 RCSDNode；多个端点节点命中同一 SWSD 路口时先归组，再输出唯一 relation。

`kind_2 = 64` 的 SWSD 环岛语义路口走独立 Phase 2 分支。模块先检查该语义路口下所有 SWSD node 是否都被 Phase 1 路口面覆盖；再把这些面与 `RCSDRoad.roadtype = 8` 的环岛 road `10m` buffer 合并为环岛候选面；随后筛选完全落在该面内、且彼此通过 `roadtype = 8` RCSDRoad 连通的 RCSD 语义路口。符合条件的 RCSDNode 被归组为一个 RCSD 语义路口，主 node 作为唯一 `base_id` 输出 relation。该分支只更新 copy-on-write `RCSDNode.mainnodeid`，不 split road、不新增 node。

全量运行可设置 `progress=True`。runner 会在控制台输出稀疏进展：输入数据体量、预分类 plan、只读/可变 target 计数、每 `progress_interval` 个 target 的处理进度和总耗时；summary 的 `performance` 字段记录聚合打点，不写 per-target 明细。

`readonly_workers` 仅并行处理不修改 RCSDRoad / RCSDNode 的只读关系分支，包括已有单一 RCSD 语义路口直接关联、无 RCSD 普通失败、缺少 evidence 普通失败等。RCSDNode grouping 与 RCSDRoad split 当前仍串行执行，以保持新增 id 分配和 copy-on-write 拓扑更新稳定。

输出阶段会逐文件打印 `writing/done` 进度，并在 `summary.performance.output_timings_sec` 与 `summary.performance.output_sizes_bytes` 中记录每个输出文件的耗时与大小。大体量 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 使用分批 GPKG 写出，避免逐 feature 写入成为瓶颈。

`module_relation_audit_summary.csv/json` 按 `T07 / T02_INPUT / T03 / T04` 统计输入 evidence 总量与四类结果：前置失败无关联、前置成功且有 RCSD 语义路口、前置成功且有 RCSDRoad、前置成功但无 RCSD 关联。每类记录 relation 成功数、失败数、缺失 relation 数与 blocking error 数，用于验证最终关系生产是否符合预期。

Phase 2 在入口统一归一 SWSD 语义路口主键：evidence `target_id`、surface `mainnodeid`、nodes `id/mainnodeid` 中 `622700016` 与 `622700016.0` 这类整数 ID 表达差异视为同一 target。最终 `intersection_match_all.geojson`、junctionization audit、relation audit 与 blocking/cardinality 输出均写 canonical `target_id`。

`swsdnode_out.gpkg` 是 final SWSD `nodes.gpkg` 的 copy-on-write 标记输出，不原地修改输入。若某个 T03/T04 target 在 relation evidence 中明确是“前置构面成功 / 锚定成功，但 `relation_state = no_related_rcsd` 且没有可用 RCSDNode 或 RCSDRoad 候选”，同时 Phase 2 审计也确认该 target 无 RCSD 关系，且对应 SWSD node 原始 `has_evd = yes / is_anchor = yes`，T05 将这两个字段改写为 `yes_nr`，表示 not RCSD，用于最终成功率统计时排除纯 SWSD 构面但无 RCSD 关联的数据；标记明细写入 `swsdnode_yes_nr_audit.csv/json`。T04 fallback road-only 只要存在 `fallback_rcsdroad_ids / selected_rcsdroad_ids` 并进入 road split，即使原始 `relation_state = no_related_rcsd` 也不得标记 `yes_nr`。summary 同步记录 `swsdnode_audit_no_rcsd_target_count / swsdnode_pre_success_no_rcsd_target_count / swsdnode_no_rcsd_target_count / swsdnode_no_rcsd_node_match_count / swsdnode_yes_nr_candidate_count / swsdnode_no_rcsd_unmatched_target_count`，用于判断 `yes_nr=0` 是无候选、前置成功门槛不满足、节点未匹配，还是候选不满足 `has_evd/is_anchor` 门槛。

T07 历史路口锚定成果与 T03/T04 relation evidence 同构。若 T07/T03/T04 evidence 中某个 target 提供 `status_suggested = 0` 且 `base_id_candidate` 为有效 RCSD 语义路口主 node id 或 group id，Phase 2 优先作为 direct relation 消费，不再用同 row 的 `required_rcsdnode_ids` 重新归组；即使 T07 target 没有 Phase 1 surface，也会进入 `intersection_match_all.geojson`。

## T03 Evidence 补齐

T03 当前主流程已经提供 T05 Phase 2 所需的 relation evidence 时，T05 直接消费原始 `t03_swsd_rcsd_relation_evidence.*`，不再默认执行 backfill。T05 保留 `backfill_t03_relation_evidence(...)` 与 `scripts/t05_backfill_t03_relation_evidence_innernet.py` 作为旧 T03 产物兼容工具；`scripts/t05_innernet_experiment.py --t03-backfill-mode auto` 仅在发现 accepted T03 evidence 缺少 `required_rcsdnode_ids / support_rcsdroad_ids` 等 Phase 2 分流字段时才自动补齐，也可用 `always / never` 显式控制。

- `required_rcsdnode_ids` 非空时，补齐为已有 RCSD 语义核心，Phase 2 将直接关联或归组 RCSDNode。
- `support_rcsdroad_ids` 非空且无 `required_rcsdnode_ids` 时，补齐为 `relation_state = rcsd_present_not_junction`，Phase 2 将进入 T03 road-only split。
- 补齐输出为独立 `t03_swsd_rcsd_relation_evidence_backfilled.csv/json`，并写 `t03_swsd_rcsd_relation_evidence_backfill_audit.*` 与 summary。
- 标准 run root 使用 `cases/<case_id>/step6_status.json`；测试包或聚合目录可使用一层嵌套的 `*/cases/<case_id>/step6_status.json`。
