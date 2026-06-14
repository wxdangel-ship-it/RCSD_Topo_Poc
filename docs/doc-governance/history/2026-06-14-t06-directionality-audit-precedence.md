# 2026-06-14 T06 方向性失败优先于挂接损失归因

## 背景

Case `991176` 的 SWSD Segment `991159_1049534` 在 T06 Step2 被拒绝，主拒绝原因为 `rcsd_not_bidirectional_for_swsd_dual`。

深度审计显示：

- 正向 RCSD path `5396513947461823 -> 5396513947461897` 位于 50m buffer 内，4 条 Road，约 `485.345m`，贴合 SWSD Segment。
- 反向可达只存在于全 RCSD 图绕行路径，11 条 Road，约 `1253.061m`，最远距离目标 SWSD 几何约 `380.907m`。
- 50m 候选图和 retained 图均没有反向 path。

原 T06 failure business audit 先检查 `dropped_junc_nodes`，导致该 Segment 被归为 `junc_required_blocked`，`upstream_issue_owner=T05`。这会把方向性主因误追到挂接路口关系。

## 变更

- T06 failure business category 改为优先消费主 `reject_reason`。
- 当 `reject_reason` 为 `rcsd_not_bidirectional_for_swsd_dual` 或 `rcsd_directed_path_missing` 时，归类为 `directionality_mismatch_fixable`。
- `dropped_junc_nodes`、`junc_attach_loss_reason`、`lost_attach_road_ids` 仍保留在审计字段中，但不覆盖方向性主因。
- 增加单测覆盖方向性主因与 dropped junc 同时存在时的归因优先级。

## 预期影响

- `991159_1049534` 的失败不再被错误归因到 T05 锚定/挂接关系，而是明确为 T06 对 RCSD 双向 corridor 的安全拒绝。
- 本变更只调整审计归因，不放宽替换规则，不扩大 buffer，不改变 Step2 replaceable 判定。

## 验证

- `pytest tests/modules/t06_segment_fusion_precheck/test_failure_business_audit.py -q`
- 复跑 Case `991176`，确认 `991159_1049534` 的主拒绝仍为 `rcsd_not_bidirectional_for_swsd_dual`，但 failure business category 不再被 dropped junc 覆盖。
