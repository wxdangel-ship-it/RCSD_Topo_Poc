# T05 - INTERFACE_CONTRACT

## 定位

本文件是 `t05_junction_surface_fusion` 的稳定接口契约。T05 分为两个阶段：

- Phase 1：路口面融合发布。
- Phase 2：消费 Phase 1 成果，执行 RCSD junctionization 与 SWSD-RCSD 关系生产。

Phase 1 不生产关系表，不输出 `intersection_match_all.geojson`，不打断 `RCSDRoad`，不新增 `RCSDNode`，不消费 relation evidence 作为主输入。

Phase 2 不重新融合路口面，不修改 Phase 1 的 `junction_anchor_surface.gpkg`，只基于 Phase 1 主图层、fusion audit、final nodes、原始 RCSDRoad/RCSDNode 与 T02/T03/T04 relation evidence 做 copy-on-write 拓扑预处理和最终关系发布。

Phase 2 直接消费 T02/T03/T04 当前已有 relation evidence，不要求前序模块新增字段或回改逻辑。若发现前序 evidence 缺失、矛盾或无法支撑场景分流，必须停机回报，不得在 T05 中反推并固化新业务规则。

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

- 不建立 SWSD-RCSD 最终关系表。
- 不输出 `intersection_match_all.geojson`。
- 不执行 RCSDRoad split / cut / break。
- 不新增 RCSDNode。
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
)
```

Phase 2 输出：

- `intersection_match_all.geojson`，CRS 为 CRS84 / WGS84 lon-lat，字段固定为 `target_id / base_id / status / level / is_highway`。
- `rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。
- `rcsdroad_split.gpkg`、`rcsdnode_generated.gpkg`、`rcsdnode_grouped.gpkg`。
- `rcsd_junctionization_audit.csv/json`、`intersection_match_all_audit.csv/json`、`blocking_errors.csv/json`、`summary.json`。

Phase 2 失败统一 `status = 1`、`base_id = 0`。成功关系的 `base_id` 必须是 RCSD 语义路口主 node id，不得写普通 RCSDRoad id。T03-A 多 RCSDNode 与 T04 complex 多 RCSDNode 先归组再建关系；T03 road-only 与 T04 fallback road-only 才进入 RCSDRoad split。被 split 的原始 RCSDRoad 不进入 active `rcsdroad_out.gpkg`。

Road-only 投影点落在 RCSDRoad 起终点 `min_endpoint_gap_m` 范围内时，不打断 road，不新增 RCSDNode；Phase 2 复用最近端点的 `snodeid / enodeid` 对应 RCSDNode 作为语义路口候选。若命中多个端点 RCSDNode，则按主 RCSDNode 选择规则归组后输出唯一 relation；若端点 RCSDNode 缺失，则保持失败并写 audit。

`intersection_match_all.geojson` 规则：

- `target_id` 必须唯一。
- 一个 SWSD 语义路口只允许输出一条 relation。
- `level = final nodes.gpkg` 中 SWSD representative node `grade - 1`；缺失、为空或非法时为 `-1`。
- `is_highway = final nodes.gpkg` 中 SWSD representative node `closed_con - 1`；缺失、为空或非法时为 `-1`。
- 多个 RCSDNode 可归组时必须先归组，再输出一条 relation。
- 多个 `base_id` 无法合并时写入 `blocking_errors.csv/json`，不写主表 relation，`summary.passed = false`。

T04 fallback 场景可补读 `divmerge_virtual_anchor_surface.gpkg`、summary、audit 或 case-level audit 中的 `surface_scenario_type / rcsd_alignment_type / fallback_rcsdroad_ids / reference_point` 等正式字段；不得从 review PNG 或几何近邻反推。

全量运行性能观测：

- `progress=True` 时，控制台只输出阶段级进展、输入体量、预分类 plan、只读/可变 target 计数、按 `progress_interval` 稀疏 target 进度和总耗时。
- `readonly_workers` 只用于并行处理不修改 RCSDRoad / RCSDNode 的关系构建分支；RCSDRoad split、RCSDNode grouping、新增 id 分配当前保持串行。
- `summary.performance.data_volume` 记录输入 feature / evidence 体量。
- `summary.performance.plan` 记录 direct / grouping / road_split / no_related 等预分类计数，以及 unique split road / group node 候选数。
- `summary.performance.timings_sec` 记录阶段级耗时，不记录 per-target 明细，避免大数据下打点体量失控。

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
  --t02-input /mnt/d/TestData/POC_Data/patch_all/RCSDIntersection.gpkg \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment \
  --readonly-workers 4 \
  --progress-interval 1000
```

该入口顺序执行：

1. T03 relation evidence handoff 补齐，默认 `--t03-accepted-only`。
2. Phase 1 `junction_anchor_surface.gpkg` 发布。
3. Phase 2 `intersection_match_all.geojson`、copy-on-write RCSD 输出和审计发布。

## 9. T03 Relation Evidence Backfill

T05 提供 T03 -> Phase 2 handoff 补齐工具：

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
