# 03 Input Output Contract

## 输入

- `swsd_segment_path`：T01 `segment.gpkg`。
- `swsd_roads_path`：SWSD road body。
- `swsd_nodes_path`：final `nodes.gpkg`。
- `intersection_match_path`：T05 Phase 2 `intersection_match_all.geojson`。
- `rcsdroad_path`：T05 Phase 2 `rcsdroad_out.gpkg`。
- `rcsdnode_path`：T05 Phase 2 `rcsdnode_out.gpkg`。

输入文件全部只读。缺少 CRS、字段缺失或方向字段非法时，模块不得静默猜测，应进入 rejected 或显式抛出输入错误。

## Step1 输出

- `t06_swsd_segment_evd_candidates.gpkg/csv/json`
- `t06_swsd_segment_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_summary.json`

## Step2 输出

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_segments.gpkg/csv/json`
- `t06_rcsd_buffer_segment_rejected.gpkg/csv/json`
- `t06_step2_summary.json`

## GIS / 拓扑检查项

- CRS 与坐标变换正确性：所有输入通过仓库标准 vector reader 归一到处理 CRS；缺失 CRS 不静默猜测。
- 拓扑一致性：候选抽取不 silent fix 输入拓扑，连通、穿越、侧向泄漏都进入审计。
- 几何语义可解释性：几何用于 buffer 候选筛选与趋势硬筛，不替代 relation / direction / required semantic node 规则。
- 审计可追溯性：summary 记录输入路径、参数、计数、失败原因与输出路径。
- 性能可验证性：summary 记录输入规模、candidate 数、replaceable 数和 reject reason 统计。
