# 024 Directed Missing Probe-First Classification

## 时间

2026-06-15

## 背景

在 T10 4-case 端到端审计中，`1013539_1013538` 的 T06 失败原因为 `rcsd_directed_path_missing`。进一步复盘发现：T05 已提供两个 pair relation，T06 full RCSD graph 也存在 directed path，但该 path 长约 1029m，而 SWSD Segment 仅约 35m；path/SWSD 长度比约 29.5，75m/100m 几何参考下仍有大比例 RCSD path 位于 SWSD buffer 外，并穿过多个额外 mapped semantic nodes。

该类现象不应仅凭 full graph directed path 存在而扩大 T06 graph-first 兜底。若 buffer-only probe 已经指出 `ambiguous_corridor` 或 `corridor_found_with_anchor_mismatch`，根因更接近上游锚定、多候选或虚拟路口聚合问题，应回流 T03/T04/T05。

## 业务逻辑变更

- `failure_business_category()` 对 `rcsd_not_bidirectional_for_swsd_dual` 仍保持方向性优先，归类为 `directionality_mismatch_fixable`。
- `rcsd_directed_path_missing` 不再一律归类为 `directionality_mismatch_fixable`。
- 当 `rcsd_directed_path_missing` 同时伴随 buffer-only probe 的 `ambiguous_corridor` 时，归类为 `multi_anchor_ambiguous`。
- 当 `rcsd_directed_path_missing` 同时伴随 buffer-only probe 的 `corridor_found_with_anchor_mismatch` 时，归类为 `pair_anchor_mismatch`。
- 只有 probe 未指向锚定或多候选问题时，`rcsd_directed_path_missing` 才保留为 `directionality_mismatch_fixable`。

## 边界

- 不放宽 single graph-first 的 50m core、长度比、端部外延、75m/100m 几何覆盖和额外 mapped semantic node 硬审计。
- 不新增替换计划，不回写 T05 relation，不把 full graph path 存在解释为自动可替换。
- 不修改 RCSDRoad 原始方向性或连通性数据。

## 验证

- `python -m pytest tests/modules/t06_segment_fusion_precheck/test_failure_business_audit.py -q`
