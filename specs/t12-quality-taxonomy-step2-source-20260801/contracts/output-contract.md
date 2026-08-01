# T12 v10 输出契约增量

## 1. Schema

```text
2026-08-01.t12_frcsd_quality_audit.v10
```

## 2. 正式类型

新 `issue_type` 只允许：

```text
segment_required_direction_unavailable
segment_required_connection_missing
segment_unexpected_reverse_passability
junction_required_topology_missing
junction_unmatched_support_topology
junction_anchor_one_to_many
junction_anchor_many_to_one
```

## 3. 新增字段

Segment/Junction candidates、confirmed、exclusions/manual 的 CSV 均加入统一分类字段。confirmed GPKG 与 Junction Point GPKG 同步携带这些字段，供 QGIS 分类。

## 4. T07 输入契约

新参数：

```text
--t07-run-root <T07 Step1/2 run root or step2_anchor_recognition root>
```

当提供时必须定位：

```text
step2_anchor_recognition/nodes.gpkg
step2_anchor_recognition/node_error_1.gpkg
step2_anchor_recognition/node_error_2.gpkg
step2_anchor_recognition/t07_step2_summary.json
step2_anchor_recognition/t07_swsd_rcsd_relation_evidence.csv|json
```

缺失、final state 与 error evidence 不一致、summary 计数不一致时 run blocked。

`--t07-step3-run-root` 标记 deprecated，只可尝试定位同一运行链的 Step2 root；不读取 `relation_cardinality_errors.*`。

## 5. 几何与文件兼容

- Segment 文件名保持不变，主几何沿用 T01 Segment 线几何族（`LineString/MultiLineString`）。
- Junction 文件名保持不变，主几何 Point。
- 不提供 T03/T07 来源时仍写结构完整的空 Junction 文件。
