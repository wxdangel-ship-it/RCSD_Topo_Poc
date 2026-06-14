# 015 Step2 单向方向缺失候选 pair 的 graph-first 正式重试

- 时间：2026-06-14
- 模块：T06 Segment Fusion Precheck / Step2
- 变更类型：高等级单向 Segment 候选 pair 方向试算后的受限纵向成段补漏

## 根因

T10 `991176` 审计发现，`1013538_974921` 这类高等级单向 Segment 在原始 T05 pair relation 层存在一端锚定异常。T06 已能通过 buffer-only probe 定位 50m core 内的高置信 RCSD corridor，并进入候选 pair 的 as-is / reversed 正式试算；但正式 `BufferSegmentExtractor` 在候选 pair 下仍可能因为 `rcsd_directed_path_missing` 失败。

该失败与既有单向分歧合流问题同源：RCSD 的真实 pair 路口之间需要沿全 RCSDRoad 有向图纵向联通，局部 50m candidate graph 不一定包含完整有向 corridor。既有 `SingleGraphConnectivityRetry` 已提供 50m core、长度比、端部外延与 75m/100m 几何参考硬审计，但 `pair_anchor_formal_retry` 的入口只放行了 `required_semantic_nodes_not_connected_in_buffer`，导致这类 `directionality_mismatch_fixable + rcsd_directed_path_missing` 没有进入同一套硬审计。

## 业务逻辑变更

`pair_anchor_formal_retry` 新增受限入口：

1. 仅适用于 `directionality=single`。
2. 仅适用于 `failure_business_category=directionality_mismatch_fixable` 且 `source_reject_reason=rcsd_directed_path_missing`。
3. buffer-only probe 必须是 `corridor_found` 或 `corridor_found_with_anchor_mismatch`。
4. probe 不得要求人工复核，且 `repair_recommendation` 必须是 `high_confidence_pair_anchor_candidate`。
5. probe 的方向与连通评分必须均为 `1.0`。
6. 仍只对候选 pair 执行 as-is / reversed 正式试算；只有恰好一个 oriented candidate 通过正式 `BufferSegmentExtractor` 或既有 `SingleGraphConnectivityRetry` 时才输出 replaceable。
7. 不回写 T05 relation，不新增输入字段语义，不扩大整体 buffer，不修改 Step2 主入口文件。

## GIS / 拓扑检查

- CRS 与坐标变换：不新增 CRS 处理，继续复用 T06 Step2 已归一化的 `EPSG:3857` 几何。
- 拓扑一致性：不 silent fix；候选 pair 必须重新通过 RCSD 有向 path、叶子端点、额外 mapped semantic node 与特殊组硬审计。
- 几何语义：50m SWSD Segment buffer 仍是必须经过的 core 证据；纵向补足只由 RCSDRoad 联通关系完成，不横向扩大候选 road。
- 审计可追溯性：输出继续记录原始 reject reason、failure business category、候选 pair、oriented pair、`adaptive_buffer_source_reason` 与 retained RCSDRoad。
- 性能可验证性：每个命中 Segment 仍最多试算候选 pair 的两个方向；graph-first 重试沿用现有长度比与参考距离门槛，避免长绕行。

## 验证

- 新增 `test_directionality_mismatch_formal_retry_uses_single_graph_first_path`，覆盖候选 pair as-is 正式 extractor 失败、reversed 方向通过 single graph-first 后输出 replaceable outcome。
