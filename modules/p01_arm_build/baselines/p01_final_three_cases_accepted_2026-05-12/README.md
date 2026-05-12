# P01-Final Three Cases Accepted Baseline

冻结日期：`2026-05-12`

范围：`1019789`、`38724646`、`950044` 三个真实 Case 的 P01-Final F-RCSD RoadNextRoad 结果。

## 验收状态

- `1019789`：本轮结果与上一轮用户已目视确认正确的 direction-fix 结果完全一致，冻结为 accepted。
- `38724646`：本轮新增路口内提前右转 `621439810 -> 617826765`，其原始证据为 `SWSD#5930602`，整体冻结为 accepted。
- `950044`：本轮结果与上一轮 direction-fix 结果完全一致，冻结为 accepted；低置信 fallback 关系保留审计标记，不阻断验收。

## 文件说明

- `manifest.json`：冻结基线元数据、源 run root、计数、哈希、accepted 说明。
- `case_summary.csv`：每个 Case 的生成数量、audit 数量和接受说明。
- `final_pass_relations_with_original_evidence.csv`：所有最终通行关系及其原始 RoadNextRoad 证据。
- `cases/<case_id>/frcsd_road_next_road.geojson`：该 Case 冻结的最终 F-RCSD RoadNextRoad。
- `cases/<case_id>/frcsd_road_next_road_audit.json`：该 Case 冻结的生成 / 未生成审计。
- `cases/<case_id>/frcsd_road_next_road_issue_report.json`：该 Case 冻结的问题报告。
- `cases/<case_id>/final_generation_decisions.json`：该 Case 冻结的规则级生成决策。

## 使用边界

该目录只冻结当前已接受的输出状态。后续规则变更如导致这些文件变化，必须说明差异来源，并明确是更新 baseline 还是判定回归。
