# 017 Step2 双向高等级候选 pair 的 adaptive buffer 正式重试

- 时间：2026-06-14
- 模块：T06 Segment Fusion Precheck / Step2
- 变更类型：双向高等级 Segment 的候选 pair 正式消费补强

## 根因

T10 `1885118` 审计中，`1881804_12203262`、`1878480_1881804`、`1881804_1881833`、`14541129_47115534` 均已在 T06 Step2 的 buffer-only probe 中得到非人工复核的高置信候选 pair，且全 RCSD 图显示 required nodes 连通、pair 双向可达；但 50m buffer candidate graph 只保留了单方向 corridor，最终以 `rcsd_not_bidirectional_for_swsd_dual` rejected。

既有 `pair_anchor_formal_retry` 只允许 `directionality=single` 进入 formal retry，并且内部固定要求 directed pair、固定 `require_bidirectional=False`。因此双向高等级 Segment 即使 probe 已定位出高置信候选 pair，也只能停留在诊断/repair candidate 表中，不能进入正式 `BufferSegmentExtractor` 的双向硬审计。

## 业务逻辑变更

1. `pair_anchor_formal_retry` 新增双向准入条件：仅允许 `sgrade` 属于 `0-0* / 0-1*`、`failure_business_category=directionality_mismatch_fixable`、`source_reject_reason=rcsd_not_bidirectional_for_swsd_dual`、probe 非人工复核且 recommendation 为 `high_confidence_pair_anchor_candidate` 的候选 pair。
2. 双向候选 pair 不使用 single directed pair 映射；正式 extractor 以 `require_directed_pair=False`、`require_bidirectional=True` 执行硬审计。
3. 若 50m 下候选 pair 仍因双向 corridor 不完整失败，则复用既有高等级 dual adaptive buffer 准入，仅尝试 `75m / 100m / 125m`。只有 adaptive 后 retained graph 仍满足双向、叶子端点、额外 mapped semantic node、几何覆盖等 Step2 硬审计时，才输出 replaceable。
4. 该策略只在当前 Segment 内构造 effective relation，不回写 T05 relation，不新增输入字段语义，不基于 Case ID 补丁。
5. formal retry 的 adaptive 统计不再把 dual 成功误计入 single 分组。

## GIS / 拓扑检查

- CRS 与坐标变换：不新增 CRS 转换，继续复用 T06 Step2 输入的 EPSG:3857 几何和既有 buffer 参数。
- 拓扑一致性：不执行 silent fix；候选 pair 必须重新通过 `BufferSegmentExtractor`，双向 Segment 必须满足 RCSD retained graph 双向可达。
- 几何语义：50m buffer-only probe 仍只是核心证据；纵向不足只通过受限 adaptive buffer 补足，不无限扩大候选范围。
- 审计可追溯性：输出继续记录原始 pair、候选 pair、source reject reason、failure business category、adaptive buffer distance/source reason 和 retained RCSDRoad。
- 性能可验证性：每个候选 pair 只尝试 as-is / reversed 两个方向；adaptive buffer 最多 3 个固定距离。

## 验证

- 新增 `test_dual_directionality_mismatch_formal_retry_uses_candidate_pair_adaptive_buffer`，覆盖 50m 下双向失败、75m adaptive 后通过 `require_bidirectional=True` 的正式重试路径。
