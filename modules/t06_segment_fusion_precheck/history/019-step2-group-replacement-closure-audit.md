# 019 Step2 Group Replacement Closure Audit

## 背景

Case `1885118` 中多个高等级双向 Segment 的 RCSD 图路径具备目视替换可能，但正式审计发现 path 会穿过当前 Segment `pair_nodes / junc_nodes` 之外、已经被 T05 accepted relation 锚定到其它 SWSD 语义节点的 RCSD semantic node。

若在单 Segment 内直接放行，会把其它语义路口 carrier 折叠到当前 Segment，影响 Step3 junction C 重建和 T09 restriction 表达。

## 变更

1. 将 Step2 中已稳定的 special junction group gate、RCSD semantic/internal road coverage 与 graph edge 准备逻辑拆到 `step2_special_junctions.py`，降低 `step2_extract_rcsd_segments.py` 体量并保留主流程职责。
2. 新增 `group_replacement_audit.py`，在 Step2 replaceable/rejected 稳定后，对 rejected Segment 重建 RCSD graph path。
3. 新增正式输出 `t06_segment_group_replacement_audit.gpkg/csv/json`，记录：
   - path 上的外部 accepted RCSD semantic node；
   - 这些 RCSD semantic node 对应的 SWSD target；
   - 关联 SWSD Segment 闭包；
   - 闭包内 replaceable / rejected / outside Step1 carrier；
   - `candidate_group_closure_ready` 或 `blocked_group_closure_incomplete` 等审计状态。

## 业务规则

- `t06_segment_group_replacement_audit` 只作为 group replacement 准入证据，不直接进入 `t06_rcsd_segment_replaceable`。
- 若闭包内存在 rejected carrier 或 outside Step1 carrier，当前 Segment 继续保持 rejected，并给出 `upstream_anchor_or_step1_group_scope_required`。
- 只有当外部 carrier 闭包完整且可解释时，后续才可进入独立的 T06 group replacement 策略评估。
- 2026-06-15 补充：在 incident-closure 的 `audit_status` 之外，新增 `corridor_audit_status`、`path_corridor_group_segment_ids`、`path_corridor_blocked_segment_ids`、`path_corridor_blocker_reasons` 与 `side_incident_group_segment_ids`。新字段只做审计分类，用几何走廊重叠区分真正沿 RCSD path 的 carrier blocker 与旁支 incident blocker，不改变当前 replaceable 结果。
- 2026-06-15 补充：在 path-corridor group 基础上新增正式 extractor probe，输出 `group_probe_status / group_probe_reason / group_probe_buffer_distance_m / group_probe_rcsd_road_ids / group_probe_repair_owner`。该 probe 仍不改变 Step2 `replaceable`，只证明成组 union 是否具备被 Step3 消费的正式 RCSD Segment 构建证据。

## 验证

- `pytest tests/modules/t06_segment_fusion_precheck/test_group_replacement_audit.py`
- `pytest tests/modules/t06_segment_fusion_precheck/test_runner_outputs.py::test_step2_blocks_whole_special_junction_group_when_one_segment_is_not_replaceable tests/modules/t06_segment_fusion_precheck/test_pair_anchor_formal_retry.py tests/modules/t06_segment_fusion_precheck/test_single_graph_connectivity_retry.py`
- Case `1885118` T06 Step1/2 复跑：
  - 输出：`outputs/_work/t10_case1885118_group_audit_v3/t06/step2_extract_rcsd_segments/t06_segment_group_replacement_audit.*`
  - `replaceable_count=863`
  - `rejected_count=202`
  - `group_replacement_audit_count=180`
  - `group_replacement_candidate_ready_count=20`
  - `group_replacement_closure_blocked_count=103`
  - 五个目标 Segment 当前均为 `blocked_group_closure_incomplete`，且阻塞口径只统计 path 内部外部 accepted anchor 对应的 carrier，不统计当前 pair 端点处的普通相邻 Segment。
