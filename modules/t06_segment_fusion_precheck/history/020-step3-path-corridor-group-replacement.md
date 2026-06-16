# 020 Step3 Path Corridor Group Replacement

## 背景

Case `1885118` 的多个高等级双向 Segment 单独执行 50m buffer / 双向审计会失败，但 Step2 group replacement 审计显示它们的 RCSD path 会穿过外部已锚定语义节点；按单 Segment 替换会遗漏同一 RCSD 走廊上的其它 SWSD carrier，导致最终 F-RCSD 同时保留 SWSD 与 RCSD 重叠 road。

## 变更

1. 新增 `step3_group_replacement.py`，读取 Step2 `t06_segment_group_replacement_audit.*` 中 `group_probe_status=passed` 且 `group_probe_repair_owner=T06_path_corridor_group_replacement` 的记录。
2. Step3 将重叠的 path-corridor group 合并为连通组件，组件内所有 SWSD Segment 共享同一组 `group_probe_rcsd_road_ids`，并统一进入 copy-on-write 替换。
3. 对原本不在 Step2 `replaceable` 的 carrier，Step3 基于 T01 Segment 创建 replacement unit；对已在 `replaceable` 的 carrier，Step3 合并 group RCSDRoad 并保留原有 pair/junc 映射。
4. `t06_step3_replacement_units` 与 `t06_step3_swsd_frcsd_segment_relation` 新增 `group_replacement_plan_ids / group_replacement_source_segment_ids / group_replacement_segment_ids`，replacement units 额外输出 `group_replacement_buffer_distances_m`。
5. `scripts/t06_run_step3_segment_replacement.py` 新增 `--step2-group-replacement-audit`，默认优先读取 Step2 同目录 `t06_segment_group_replacement_audit.gpkg`。

## 业务规则

- Step3 不重新搜索 RCSD Segment，不重新判定 group 是否可替换，只消费 Step2 已通过正式 extractor probe 的 group 审计证据。
- 重叠 group 必须按连通组件合并，避免同一个 SWSD Segment 被多个 group 重复替换。
- `group_probe_status=failed` 的 Segment 不由 Step3 兜底；此类问题继续归因到上游锚定或 RCSD 数据方向性/连通性。

## 验证

- `pytest tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement.py -q`
- `pytest tests/modules/t06_segment_fusion_precheck -q`
- Case `1885118` T06 Step1/2 + Step3 复跑：
  - 输出：`outputs/_work/t10_case1885118_group_probe_v1/t06`
  - Step2：`replaceable_count=863`，`rejected_count=202`，`group_probe_status=passed` 94 条。
  - Step3：`replacement_unit_success_count=1053`，`group_replacement_plan_count=51`，`group_replacement_assignment_segment_count=461`，`group_replacement_created_unit_count=190`，`road_id_collision_count=0`，`node_id_collision_count=0`。
  - 五个目标 Segment 中 `1881804_12203262 / 1878480_1881804 / 1881804_1881833 / 14541129_47115534` 进入 `relation_status=replaced`；`1885140_1888173` 仍为 `retained_swsd`，原因是 Step2 group probe 仍失败为 `rcsd_not_bidirectional_for_swsd_dual`。
- T09 Step3 使用新 T06 Step3 结果复跑：
  - 输出：`outputs/_work/t10_case1885118_group_probe_v1/t09_step3_from_group/t09_step3`
  - `restriction_count=1369`
