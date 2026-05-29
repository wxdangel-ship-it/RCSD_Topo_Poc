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

T03 -> T05 Phase 2 handoff 补齐提供一个内网脚本入口。该脚本只读取现有 T03 run root 中的 `t03_swsd_rcsd_relation_evidence.*` 与 `cases/<case_id>/step6_status.json` / `step6_audit.json`，写出补齐后的 T05 可消费 evidence，不修改 T03 主链或原始输出：

```bash
.venv/bin/python scripts/t05_backfill_t03_relation_evidence_innernet.py \
  --t03-run-root /path/to/t03/run \
  --relation-evidence-path /path/to/t03_swsd_rcsd_relation_evidence.csv \
  --out-root /path/to/t05_phase2_handoff \
  --accepted-only
```

T05 Phase 1 + Phase 2 内网联合实验提供 repo 级入口。当前主流程把 T07/T03/T04 成果目录、原始 RCSDRoad/RCSDNode、final nodes 与既有 `RCSDIntersection` handoff surface 作为参数，先执行 T03 evidence handoff 补齐，再执行 Phase 1 surface fusion 与 Phase 2 relation 发布：

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

`--t07-dir` 会自动发现 `t07_swsd_rcsd_relation_evidence.csv` 与 `t07_rcsdintersection_anchor_surface.gpkg`；也可通过 `--t07-evidence / --t07-input` 显式传入。`--t02-dir / --t02-evidence / --t02-input` 仅作为旧批次兼容路径保留。

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
- `rcsd_junctionization_audit.csv/json`
- `intersection_match_all_audit.csv/json`
- `blocking_errors.csv/json`
- `module_relation_audit_summary.csv/json`
- `summary.json`

失败关系统一 `base_id = 0`。如果同一 SWSD 路口只生成 1 个 RCSDNode，则 `mainnodeid = null`；如果生成或归组多个 RCSDNode，则组内所有 RCSDNode 包括主节点自己 `mainnodeid` 都填主节点 id。

`intersection_match_all.geojson` 中 `target_id` 必须唯一，一个 SWSD 语义路口只输出一条 relation。多个 RCSD 候选可合并时先归组；无法合并时写 `blocking_errors.*`，不在主表中输出该 `target_id`。`level` 使用 final nodes 的 `grade - 1`，`is_highway` 使用 `closed_con - 1`；缺失或非法时填 `-1`。

Road-only 场景中，若投影点距离 RCSDRoad 起终点小于 `min_endpoint_gap_m`，Phase 2 不生成极短 split 段，改为复用对应 `snodeid / enodeid` 的已有 RCSDNode；多个端点节点命中同一 SWSD 路口时先归组，再输出唯一 relation。

全量运行可设置 `progress=True`。runner 会在控制台输出稀疏进展：输入数据体量、预分类 plan、只读/可变 target 计数、每 `progress_interval` 个 target 的处理进度和总耗时；summary 的 `performance` 字段记录聚合打点，不写 per-target 明细。

`readonly_workers` 仅并行处理不修改 RCSDRoad / RCSDNode 的只读关系分支，包括已有单一 RCSD 语义路口直接关联、无 RCSD 普通失败、缺少 evidence 普通失败等。RCSDNode grouping 与 RCSDRoad split 当前仍串行执行，以保持新增 id 分配和 copy-on-write 拓扑更新稳定。

输出阶段会逐文件打印 `writing/done` 进度，并在 `summary.performance.output_timings_sec` 与 `summary.performance.output_sizes_bytes` 中记录每个输出文件的耗时与大小。大体量 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 使用分批 GPKG 写出，避免逐 feature 写入成为瓶颈。

`module_relation_audit_summary.csv/json` 按 `T07 / T02_INPUT / T03 / T04` 统计输入 evidence 总量与四类结果：前置失败无关联、前置成功且有 RCSD 语义路口、前置成功且有 RCSDRoad、前置成功但无 RCSD 关联。每类记录 relation 成功数、失败数、缺失 relation 数与 blocking error 数，用于验证最终关系生产是否符合预期。

T07 历史路口锚定成果与 T03/T04 relation evidence 同构。若 `t07_swsd_rcsd_relation_evidence.*` 中某个 target 提供 `status_suggested = 0` 且 `base_id_candidate` 为有效 RCSD 语义路口主 node id 或 group id，Phase 2 作为 direct relation 处理；即使该 target 没有 Phase 1 surface，也会进入 `intersection_match_all.geojson`。

## T03 Evidence 补齐

T03 当前部分运行路径会在 case 级 `step6_status.json` 中产出 `required_rcsdnode_ids / support_rcsdroad_ids`，但批次级 `t03_swsd_rcsd_relation_evidence.*` 未必携带这些字段值。T05 提供 `backfill_t03_relation_evidence(...)` 与 `scripts/t05_backfill_t03_relation_evidence_innernet.py` 用于方案 1 handoff 补齐：

- `required_rcsdnode_ids` 非空时，补齐为已有 RCSD 语义核心，Phase 2 将直接关联或归组 RCSDNode。
- `support_rcsdroad_ids` 非空且无 `required_rcsdnode_ids` 时，补齐为 `relation_state = rcsd_present_not_junction`，Phase 2 将进入 T03 road-only split。
- 补齐输出为独立 `t03_swsd_rcsd_relation_evidence_backfilled.csv/json`，并写 `t03_swsd_rcsd_relation_evidence_backfill_audit.*` 与 summary。
- 标准 run root 使用 `cases/<case_id>/step6_status.json`；测试包或聚合目录可使用一层嵌套的 `*/cases/<case_id>/step6_status.json`。
