# T06 - INTERFACE_CONTRACT

## 定位

本文件是 `t06_segment_fusion_precheck` 的稳定接口契约。T06 当前只覆盖 Segment 替换前置检查：

- Step1：识别可参与融合的 SWSD Segment 单元。
- Step2：抽取对应 RCSD Segment candidate，并用趋势类硬筛判断是否可进入后续替换阶段。

本模块不执行 Segment 替换，不重塑路口，不修改 T01 / T05 输出。

## 1. 目标与范围

### 1.1 当前正式支持

- 消费 T01 `segment.gpkg` 与 final `nodes.gpkg`。
- 按 `pair_nodes + junc_nodes` 的语义路口 ID 集合判断 Segment 是否具备 EVD 与 anchor/fallback 基础。
- 将 `is_anchor = fail4_fallback` 视为可融合 anchor。
- 消费 T05 Phase 2 `intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。
- 基于 relation 映射与 RCSD directed graph 抽取 Segment candidate。
- 支持 SWSD / RCSD 双向 Segment 与单向 Segment。
- 对 SWSD 单向 Segment 从 `swsd_roads_path` 的 road body 推导方向。
- 对 RCSD candidate 执行 relation、方向、junc、语义路口顺序、主轴、粗长度与唯一性硬筛。

### 1.2 当前非目标

- 不执行 SWSD Segment 替换。
- 不重塑路口。
- 不修改 T01 主链、T05 主链或任何输入成果。
- 不新增 repo CLI、`tools`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- 除 `scripts/t06_run_innernet_precheck.py` 这个内网运行包装外，不新增其它 repo 级脚本入口。
- 不使用精细几何拟合指标作为第一版核心硬门槛。

## 2. Inputs

### 2.1 Step1 Runner

```python
run_t06_step1_identify_fusion_units(
    *,
    swsd_segment_path,
    swsd_nodes_path,
    out_root,
    run_id=None,
    progress=False,
)
```

必选输入：

- `swsd_segment_path`：T01 `segment.gpkg`，依赖字段 `id / sgrade / pair_nodes / junc_nodes / roads / geometry`。
- `swsd_nodes_path`：final `nodes.gpkg`，依赖字段 `id / mainnodeid / has_evd / is_anchor`。
- `out_root`：输出根目录。

### 2.2 Step2 Runner

```python
run_t06_step2_extract_rcsd_segments(
    *,
    swsd_fusion_units_path,
    swsd_segment_path,
    swsd_roads_path,
    swsd_nodes_path,
    intersection_match_path,
    rcsdroad_path,
    rcsdnode_path,
    out_root,
    run_id=None,
    max_main_axis_angle_diff_deg=60.0,
    min_coarse_length_ratio=0.4,
    max_coarse_length_ratio=2.5,
    progress=False,
)
```

必选输入：

- `swsd_fusion_units_path`：Step1 输出 `t06_swsd_segment_fusion_units.gpkg`。
- `swsd_segment_path`：T01 `segment.gpkg`。
- `swsd_roads_path`：SWSD road body，用于推导单向 Segment 方向。
- `swsd_nodes_path`：final `nodes.gpkg`，用于节点几何与方向审计。
- `intersection_match_path`：T05 Phase 2 `intersection_match_all.geojson`。
- `rcsdroad_path`：T05 Phase 2 `rcsdroad_out.gpkg`。
- `rcsdnode_path`：T05 Phase 2 `rcsdnode_out.gpkg`。
- `out_root`：输出根目录。

### 2.3 关键输入语义

- `pair_nodes + junc_nodes` 按语义路口 ID 判定，不按物理 node 展开作为主判断。
- `intersection_match_all.geojson` 中只有 `status = 0` 且 `base_id > 0` 的 relation 可用。
- `base_id` 必须是 RCSD 语义路口主 node id。
- `direction in {0,1}` 表示双向；`direction = 2` 表示 `snodeid -> enodeid`；`direction = 3` 表示 `enodeid -> snodeid`。
- `junc_nodes` 在 RCSD 抽取中是内部通过 + 侧向阻断，不是 hard-stop。

## 3. Outputs

### 3.1 Step1 输出

目录：

```text
<out_root>/<run_id>/step1_identify_fusion_units/
```

文件：

- `t06_swsd_segment_evd_candidates.gpkg/csv/json`
- `t06_swsd_segment_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_summary.json`

`fusion_units` 稳定字段：

- `swsd_segment_id`
- `sgrade`
- `pair_nodes`
- `junc_nodes`
- `semantic_node_set`
- `roads`
- `pair_node_count`
- `junc_node_count`
- `has_fail4_fallback`
- `geometry`

`rejected` 稳定字段：

- `swsd_segment_id`
- `reject_stage`
- `reject_reason`
- `failed_node_ids`
- `failed_node_attrs`
- `pair_nodes`
- `junc_nodes`
- `sgrade`
- `geometry`

### 3.2 Step2 输出

目录：

```text
<out_root>/<run_id>/step2_extract_rcsd_segments/
```

文件：

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_step2_summary.json`

`candidates` 稳定字段：

- `swsd_segment_id`
- `rcsd_candidate_id`
- `swsd_sgrade`
- `swsd_directionality`
- `swsd_oneway_source_node`
- `swsd_oneway_target_node`
- `swsd_direction_inference`
- `rcsd_directionality`
- `swsd_pair_nodes`
- `rcsd_pair_nodes`
- `swsd_junc_nodes`
- `rcsd_junc_nodes`
- `rcsd_road_ids`
- `rcsd_node_path`
- `rcsd_forward_reachable`
- `rcsd_reverse_reachable`
- `directionality_trend_pass`
- `oneway_direction_trend_pass`
- `semantic_junc_order_trend_pass`
- `main_axis_angle_diff_deg`
- `main_axis_trend_pass`
- `length_ratio`
- `coarse_length_trend_pass`
- `candidate_status`
- `candidate_reason`
- `geometry`

## 4. EntryPoints

T06 当前不新增 repo CLI。稳定执行面包括模块内 callable runner 与一个已登记的内网运行包装脚本。

```python
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (
    run_t06_step1_identify_fusion_units,
    run_t06_step2_extract_rcsd_segments,
)
```

内网脚本入口：

```bash
.venv/bin/python scripts/t06_run_innernet_precheck.py \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck
```

脚本默认从 `--t05-phase2-root` 自动发现 `intersection_match_all.geojson`、`rcsdroad_out.gpkg` 与 `rcsdnode_out.gpkg`；三者也可以通过显式参数覆盖。

## 5. Params

- `run_id`：可选运行 ID；为空时自动生成。
- `progress`：是否打印稀疏进度。
- `max_main_axis_angle_diff_deg`：主轴趋势最大夹角，默认 `60.0`。
- `min_coarse_length_ratio`：粗长度比例下限，默认 `0.4`。
- `max_coarse_length_ratio`：粗长度比例上限，默认 `2.5`。

## 6. Acceptance

1. Step1 runner 可独立运行并输出 EVD candidates、fusion units、rejected 与 summary。
2. Step2 runner 可独立运行并输出 RCSD candidates、replaceable、rejected 与 summary。
3. `fail4_fallback` 能进入 Step1 final fusion units，但 Step2 仍必须校验 T05 relation。
4. SWSD 单向方向从 road body 推导，不依赖 `pair_nodes` 顺序。
5. SWSD 单向 + RCSD 双向 rejected 为 `directionality_mismatch_rcsd_bidirectional_for_swsd_oneway`。
6. `junc_nodes` 执行内部通过 + 侧向阻断。
7. 所有解析、映射、方向、几何趋势失败都有明确 reason。
8. 输入文件不被原地修改。
