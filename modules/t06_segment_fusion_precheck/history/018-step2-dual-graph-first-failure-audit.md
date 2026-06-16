# 018 - Step2 dual graph-first failure audit

## 时间

2026-06-14

## 背景

Case `1885118` 中多个高等级 dual SWSD Segment 在 50m buffer 下表现为 `rcsd_not_bidirectional_for_swsd_dual`。buffer-only probe 能找到高置信候选 RCSD pair，但正式 Step2 仍不能构建双向 RCSDSegment。

## 业务逻辑变更

- dual 候选 pair 经过 50m / 75m / 100m / 125m buffer 仍不能通过时，进入 `dual_graph_first_bidirectional_retry`。
- `dual_graph_first_bidirectional_retry` 的安全门槛为：
  - 正反两个 RCSD 有向 path 都必须存在；
  - 两个 path 都必须经过 50m SWSD Segment core；
  - 两个 path 都必须满足 path / SWSD 长度比例门槛；
  - union path 不得穿过额外 mapped semantic nodes。
- 若以上硬审计仍拒绝，`t06_rcsd_segment_failure_business_audit` 对 rejected 的 `directionality_mismatch_fixable` 不再沿用 probe 阶段的自动修复建议，而是写出：
  - `manual_review_required=True`
  - `repair_recommendation=upstream_anchor_or_segment_grouping_required`
  - `upstream_issue_owner=T03/T04/T05_or_T06_group_replacement`

## Case 1885118 审计结论

- `1878480_1881804`、`1881804_1881833`、`14541129_47115534`：正反 RCSD path 存在，且 path 几何门槛可通过，但 union path 穿过已经锚定给其他 SWSD target 的 RCSD 语义路口，不能在当前单 Segment 内静默放行。
- `1881804_12203262`：除额外 mapped semantic nodes 外，一向 path / SWSD 长度比例超限，存在绕行风险。
- `1885140_1888173`：probe 给出两个候选 pair component，且候选方向 path 不完整，不满足自动构建双向 RCSDSegment 的硬门槛。

## 后续修复方向

这些目标不应通过 T06 当前单 Segment 兜底策略强行替换。若目视业务上确认应替换，应优先上溯：

- T03/T04/T05：评估是否应把同一 SWSD 语义路口附近的多个 RCSD 语义路口归并为可消费的虚拟路口面。
- T06：若上游不能归并，应新增 multi-SWSD Segment group replacement，而不是把跨多个已锚定语义路口的 RCSD path 压成单个 Segment。

## 审计产物

- `outputs/_work/t10_1885118_dual_path_root_cause_audit_20260614/target_segment_dual_path_root_cause.csv`
- `outputs/_work/t10_1885118_dual_path_root_cause_audit_20260614/unexpected_mapped_rcsd_to_swsd_targets.csv`
