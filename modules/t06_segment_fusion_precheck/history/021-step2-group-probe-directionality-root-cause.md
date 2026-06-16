# 021 Step2 Group Probe Directionality Root Cause

## 时间

2026-06-15

## 背景

Case `1885118` 中五个目标 Segment 已经分化为两类结果：

- `1881804_12203262 / 1878480_1881804 / 1881804_1881833 / 14541129_47115534`：Step2 单 Segment 仍 rejected，但 `t06_segment_group_replacement_audit` 的 path-corridor group formal probe 已通过，Step3 已按 `group_path_corridor_replacement` 成组替换。
- `1885140_1888173`：Step2 group audit 仍为 `group_probe_status=failed`，失败原因为 `rcsd_not_bidirectional_for_swsd_dual`，Step3 保持 `retained_swsd`。

## 根因证据

- T07 Step2 将 `1885140` 直接锚定到 RCSD semantic junction `5384383917918853`，将 `1888173` 锚定到 `5395138281604151`。
- T07 Step3 审计发现 `1885140` 的 Step2 surface 内存在多个 RCSD semantic junction：`5384383917918853|5396510826895178`；但 `1885140` 已是 `is_anchor=yes`，Step3 T05 relation backfill 按规则跳过，原因是 `not_step3_candidate`。
- T05 Phase2 最终仍输出 `1885140 -> 5384383917918853`、`1888173 -> 5395138281604151` 两条直接关系。
- T06 group audit 对 `1885140_1888173` 的 path-corridor group 发现 15 个 corridor carrier，其中存在 rejected/outside Step1 carrier；formal group probe 在 150m 下仍失败为 `rcsd_not_bidirectional_for_swsd_dual`。
- 使用同一 T06 `BufferSegmentExtractor` 对候选组合补充验证：原始 pair、将 `5396510826895178` 作为 optional、将 `5396510826895178` 直接作为 `1885140` 侧 pair 起点，以及将 `5395138549908383` 作为 `1888173` 侧替代端点，在 `50/75/100/150/250/400/800m` buffer 下均不能通过 `require_bidirectional=True`，失败原因均为 `rcsd_not_bidirectional_for_swsd_dual`。

## 业务逻辑变更

- `group_probe_status=passed` 时，`repair_recommendation` 统一输出 `t06_group_replacement_candidate`，明确可由 Step3 group replacement 消费。
- `group_probe_status=failed` 且 `group_probe_reason` 为 `rcsd_not_bidirectional_for_swsd_dual` 或 `rcsd_directed_path_missing` 时，`repair_recommendation` 输出 `upstream_anchor_or_rcsd_directionality_required`。
- 该变更只调整审计归因口径，不扩大 Step2 replaceable，不让 Step3 对失败 group 兜底替换。

## 验证

- `python -m pytest tests/modules/t06_segment_fusion_precheck/test_group_replacement_audit.py -q`
- Case `1885118` 现有最新结果中，四个目标 Segment 已替换，`1885140_1888173` 保持未替换；该结果与 formal bidirectional probe 证据一致。
