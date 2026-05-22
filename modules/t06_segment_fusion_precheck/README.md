# T06 Segment Fusion Precheck

`t06_segment_fusion_precheck` 是 SWSD-RCSD Segment 数据融合的前置模块。当前只做 Step1 / Step2，不执行替换。

## 当前范围

- Step1：从 T01 `segment.gpkg` 中识别可参与融合的 SWSD Segment。
- Step2：基于 T05 Phase 2 relation 与 copy-on-write RCSD 网络抽取 RCSD Segment candidate，并执行趋势类硬筛。

## 非目标

- 不执行 Segment 替换。
- 不重塑路口。
- 不修改 T01 / T05 输出。
- 不新增 repo CLI。
- 仅保留一个内网运行包装脚本：`scripts/t06_run_innernet_precheck.py`。

## Callable Runner

```python
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (
    run_t06_segment_fusion_precheck,
)

artifacts = run_t06_segment_fusion_precheck(
    swsd_segment_path="segment.gpkg",
    swsd_roads_path="roads.gpkg",
    swsd_nodes_path="nodes.gpkg",
    intersection_match_path="intersection_match_all.geojson",
    rcsdroad_path="rcsdroad_out.gpkg",
    rcsdnode_path="rcsdnode_out.gpkg",
    out_root="outputs/_work/t06_segment_fusion_precheck",
    run_id="manual_run",
)
```

## 内网脚本

```bash
.venv/bin/python scripts/t06_run_innernet_precheck.py \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck
```

脚本会运行 Step1 + Step2，并在 stdout 打印包含输入路径、输出路径与核心计数的 JSON 摘要。

## 关键规则

- `pair_nodes + junc_nodes` 按语义路口 ID 判定。
- `junc_nodes.kind_2 in {1,4096,8192}` 的节点不参与 Step1 `has_evd / is_anchor` 判定，也不进入 Step2 T05 relation 必检映射集合；`pair_nodes` 不适用该豁免。
- `is_anchor = fail4_fallback` 视为可融合 anchor。
- Step2 relation 只接受 `status = 0` 且 `base_id > 0`；必检集合为 `pair_nodes + 非豁免 junc_nodes`。
- `junc_nodes` 是内部通过 + 侧向阻断，不是 hard-stop。
- SWSD 单向方向从 `swsd_roads_path` 的 road body 推导。
- SWSD 单向 + RCSD 双向判为不一致。

## 输出

Step1 输出：

- `t06_swsd_segment_evd_candidates.gpkg/csv/json`
- `t06_swsd_segment_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_summary.json`

Step2 输出：

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_step2_summary.json`
