# Research：11 个 Segment 原始数据审计

## 1. 输入与可评估性

- 输入根：`E:\TestData\POC_QA\T10_Segment`，共 11 个 `<SegmentID>/` 目录，selection CRS 均为 `EPSG:3857`，范围均为 Segment 几何固定 `200m` buffer。
- 原显式 `frcsd_1v1` 切片在 11/11 包中缺少部分 Road endpoint Node，不能直接运行 T12；这属于切片打包完整性问题，不是 FRCSD 质量问题。
- 每包兼容 `rcsdroad/rcsdnode` 与显式层记录相同的原始 1V1 FRCSD source path；公共 Road endpoint 语义和公共 Node 几何一致，兼容层保留全部 Road endpoint Node 及完整 Road 几何 attachment。
- 使用兼容层前执行同源、ID 子集、endpoint 语义、Node 几何及拓扑依赖门禁；11/11 通过，兼容层 missing endpoint=0，`silent_fix=false`。因此 11 个均可评估，`not_assessable=0`。

## 2. 当前规则重放

正式 T10 Case chain 已对 11 包完成 T01→T07→T03→T04→T05→T06；独立 T12 使用同源拓扑完整子图重放，旧规则将 11 个目标全部自动 confirmed。T12 重放总耗时约 `40.41s`。

旧规则共同问题：raw Road endpoint 图将同一 FRCSD semantic node 的不同 raw endpoint 视为断裂；即使 canonical local directed 路径满足方向、长度和走廊阈值，也只能解释 issue type，不能排除 raw 假断裂。

## 3. 泛化判定

raw local directed 失败方向只有同时满足以下条件，才能被 semantic carrier 排除：

1. semantic local directed path 至少包含一条物理 Road，禁止零长度 canonical folding；
2. 继续使用既有 `path_max_length_ratio=1.5`、`path_max_additive_m=100`、`path_max_corridor_distance_m=50`；
3. path raw endpoint 与 raw portal 完全一致时可信；
4. T07 非完全一致端点必须与 portal 位于同一唯一 RCSDIntersection 标准路口面，面距离容差 `1m`；
5. T03/T04 非完全一致端点必须属于同 canonical group，且 raw 点间距不超过既有 `portal_radius_m=50`；
6. 每个内部 canonical alias transition 的两侧 raw endpoint 间距不超过 `portal_radius_m=50`；
7. semantic carrier 只排除 raw false positive，不能单独把 candidate 提升为 confirmed。

生产代码不包含 Case/Segment/Road/Node ID 特判。

## 4. 逐 Segment 结论

| Segment | 结论 | 原始数据依据 |
|---|---|---|
| `1520811_25466551` | `excluded_false_positive` | raw `pair0_to_pair1` 失败；semantic 有向路径通过，两端为 exact raw portal，内部 alias gap `2.21m`。 |
| `1623512_508276240` | `confirmed_quality_issue` | raw 双向失败；`pair0_to_pair1` semantic directed path 缺失，反向可解释，保留 `directed_carrier_missing`。 |
| `1629816_1643047` | `excluded_false_positive` | raw `pair0_to_pair1` 失败；semantic 有向路径通过，两端 exact，内部 alias gap `4.20m`。 |
| `1878482_1881808` | `excluded_false_positive` | raw `pair0_to_pair1` 失败；semantic 有向路径通过，两端 exact，内部 alias gap `2.00m`。 |
| `1881810_1898171` | `excluded_false_positive` | raw 双向失败；semantic 双向通过，两端 exact，最大内部 alias gap `30.02m`。 |
| `1888260_1921768` | `confirmed_quality_issue` | `pair1_to_pair0` raw/semantic directed 均缺失、semantic undirected 存在；T06 同时记录 `full_rcsd_graph_one_direction_only`，保留 `directed_carrier_missing`。 |
| `1908169_1921764` | `excluded_false_positive` | raw 双向失败；semantic 双向通过，两端 exact，最大内部 alias gap `18.63m`。 |
| `1921739_1921764` | `confirmed_quality_issue` | `pair0_to_pair1` semantic 路径存在，但 T07 start alias 不在对应标准路口面；反向通过，保留 `required_local_connectivity_missing`。 |
| `500636195_505415445` | `confirmed_quality_issue` | `pair1_to_pair0` semantic directed 缺失，`pair0_to_pair1` 的 T07 start alias 位于标准面外；T06 记录单向图，保留 `directed_carrier_missing`。 |
| `722528_722529` | `excluded_false_positive` | raw `pair0_to_pair1` 失败；semantic 路径通过，T03 start 为同组 `6.95m` 近邻 alias，T07 end exact。 |
| `722569_12927873` | `excluded_false_positive` | raw 双向失败；semantic 双向通过，非 exact T07 end 与 portal 同属标准面，内部 alias gap 最大 `1.29m`。 |

汇总：`excluded_false_positive=7`、`confirmed_quality_issue=4`、`not_assessable=0`。

## 5. GIS 与审计证据

- CRS：输入与处理均为 `EPSG:3857`，未执行坐标变换。
- 拓扑：兼容子图 11/11 endpoint 完整；未 repair、snap、补点或补路。
- 几何语义：semantic carrier 仍受原长度/增量/走廊阈值约束；200m package 范围覆盖 50m local corridor。
- QGIS 自动等价检查：11 个目标 Segment 对 DriveZone in-road ratio 均通过 `0.60` 门禁，范围约 `0.69–1.00`；DriveZone 只作证据，不改变 verdict。
- 审计路径：`outputs/_work/t12_false_positive_hardening_20260719/` 下保留 package audit、before/after replay、alias audit、prototype rule、QGIS gate 和 `1026960` regression。
- 性能：修复后 11 个 T12 replay 总耗时约 `45.33s`；完整城市性能仍需在内网正式全量数据上验证。
