# P01 v1.0.0 需求覆盖审计

审计主源：`/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/RCSD_Topo_Poc__P01__REQUIREMENT.md`，文档版本 `v1.0.0（2026-05-12 修订版）`。

P01-Final 规则级修正源：`/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/P01_Final_RoadNextRoad_Rule_Model_Discussion.md`。

审计对象：`p01_arm_build` 模块文档、SpecKit、A1 / A2 / P01-Final 实现与测试。

状态取值：已实现 / 部分实现 / 未实现 / 不适用 / 需确认。

2026-05-12 已按当前仓库实现和 accepted baseline，将外部 P01 基准需求文档重写为 Step 1-16 的业务链路结构，并同步纳入路口前 / 路口内提前右转、规则级 P01-Final、三 Case accepted baseline 等已确认口径。

| 序号 | 需求项 | 状态 | 实现 / 测试事实 |
| --- | --- | --- | --- |
| 1 | P01 最终目标为 F-RCSD RoadNextRoad | 已实现 | `final_road_next_road.py` 生成 `frcsd_road_next_road.geojson`；`runner.py` 写出 final JSON / GeoJSON / review 产物；测试覆盖 final generation。 |
| 2 | 语义路口定义 | 已实现 | `topology.py` 按有效 `mainnodeid` 聚合，无效值退化为单节点；A1 tests 覆盖 semantic junction。 |
| 3 | Arm 基于拓扑追溯 | 已实现 | `topology.py` 输出 InitialArm / FinalArm / ArmTrace / ThroughDecisionAudit；tests 覆盖 trace 与 kind-aware stop。 |
| 4 | formway bit7 / bit8 位运算 | 已实现 | `special_roads.py` 解析整数 formway 并使用 bit7 / bit8；tests 覆盖 bit 运算与缺失 / 不可解析 audit。 |
| 5 | 提前左转 / 提前右转规则 | 已实现 | bit8 road 可进入 Arm member 且排除 trunk；bit7 road 按路口前 / 路口内分流，路口前不进入 member / seed / connector / trunk 并进入 relation / issue，路口内进入 Arm member / seed 且排除 trunk，不进入 relation。 |
| 6 | AdvanceRightTurnRelation | 已实现 | `special_roads.py` 输出 relation；`runner.py` 写出 `advance_right_turn_relations.json`；tests 覆盖 resolved / unresolved。 |
| 7 | trunk_road_ids 与 trunk_status | 已实现 | `trunk.py` 输出 trunk ids、status、reason、non-trunk member；A1 tests 覆盖 complete / partial / none / ambiguous。 |
| 8 | RoadNextRoad allowed evidence | 已实现 | `road_next_road.py` 归一化 RoadNextRoad；`movement.py` 将其投影为 RoadMovementEvidence；缺失不作为禁止。 |
| 9 | ArmMovement 全量候选 | 已实现 | `movement.py` 输出 `from_arm × to_arm`；tests 覆盖全量候选数量。 |
| 10 | 不使用 turnType / turntype 判断 movement_type | 已实现 | `road_next_road.py` 仅保留 raw audit；`movement.py` 判定不读取 raw turn type；tests 覆盖 raw turn type 改变但 movement_type 不变。 |
| 11 | 直行 / 左转 / 右转交通设计语义 | 已实现 | `movement.py` 基于 same-arm、stable straight、trunk / local trend 连续与相对侧向输出 type；证据不足输出 unknown。 |
| 12 | T 型可参与规则，Y-like 不作先验输入 | 已实现 | `topology.py` T 型 through / terminal 结合 kind、方向与拓扑；`movement.py` 的 post_shape_label 为后验审计字段。 |
| 13 | stable straight 参与 trunk 修正 | 已实现 | `movement.py` 仅使用 `unique_straight_target` 且高置信 straight evidence 生成 straight receiving。 |
| 14 | ReceivingRoadRole | 已实现 | `movement.py` 输出 `arm_receiving_road_roles.json`，包含 straight / left / advance_left / right / unknown roles。 |
| 15 | advance-left-only receiving road 排除 trunk | 已实现 | `movement.py` 在 stable straight receiving 非空且 road 未被 straight 接入时排除；tests 覆盖排除和 straight priority。 |
| 16 | FinalArm fallback validation | 已实现 | `final_arm_validation.py` 对兜底 FinalArm 做 relaxed reverse / supplemental trace validation；`runner.py` 写出 `final_arm_validation.json`；tests 覆盖 not_required / validated / weak_validated / unvalidated / conflict。 |
| 16a | FinalArm 远端走廊证据 | 已实现 | `corridor.py` 输出 `arm_corridor_evidence.json`；A2 ArmProfile 和 Movement 方向向量消费该证据；review GPKG / PNG 增加 corridor support roads。 |
| 17 | corrected_final_arms | 已实现 | `runner.py` 写出 `corrected_final_arms.json`；tests 覆盖字段保留与 validation 状态输出。 |
| 18 | P01-A2 LogicalArmGroup | 已实现 | `alignment.py` 构建 LogicalArmGroup、RawArmAlignment、ArmBuildFeedback；`test_p01_arm_alignment.py` 覆盖 stable/missing/partial/conflict 等场景。 |
| 19 | F-RCSD:Road.Source | 已实现 | `final_road_next_road.py` 读取并校验 Source；ArmSourceProfile 按 Road 级统计 Source 分布，支持混源 Arm 审计。 |
| 20 | Source + CRS-normalized rounded exact geometry 映射 | 已实现 | `final_road_next_road.py` 按 Source 尝试 rounded exact geometry mapping；missing / ambiguous 进入 issue，但该映射仅作为 audit / confidence evidence，不再作为生成前提；tests 覆盖精确匹配缺失仍可规则生成。 |
| 21 | 源侧规则抽象 | 已实现 | `SourceArmPassRule` 从 SWSD / RCSD RoadNextRoad、ArmMovement、进入道路角色与目标 Arm 退出道路集合抽象 `full_allowed / prohibited / trunk_only_allowed / left_receiving_only_allowed / data_error_partial_target_coverage` 等状态；tests 覆盖。 |
| 22 | 全通投影 | 已实现 | `full_allowed` 生成进入道路角色到目标 Arm 所有退出 Road；tests 覆盖目标 Arm 多退出 Road。 |
| 23 | 部分目标覆盖异常 | 已实现 | 主干道路 / 平行支路部分目标覆盖输出 `data_error_partial_target_coverage / manual_review_required`，不自动投影；advance-left 和 uturn 特例不误报；tests 覆盖。 |
| 24 | 平行支路数量一致性 | 已实现 | `parallel_branch_alignment.json` 输出 source_missing、count_matched_ordered、count_mismatch 与 insufficient_geometry 审计；count mismatch 输出 `parallel_branch_count_mismatch_manual_review_required` 与 `data_error`；源有平行支路而 F-RCSD 没有输出 `source_parallel_branch_missing_in_frcsd`。 |
| 25 | 混源 Arm 规则源选择与 fallback | 已实现 | 混源进入 Arm 按 SWSD 结构匹配、RCSD 结构匹配、SWSD basic rule 兜底选择；primary source 无可生成规则时可用 alternate source Arm role / corridor ordinal 低置信投影；参考 RCSD 但目标 Arm 缺失时 fallback 到 SWSD basic rule；tests 覆盖。 |
| 26 | frcsd_road_next_road.geojson | 已实现 | final FeatureCollection 使用 `geometry=null` 与 `id/road_id/next_road_id/type/source/turntype/city_code` properties，包含 duplicate 防护。 |
| 27 | audit / issue report | 已实现 | 输出 `arm_source_profiles.json`、`source_arm_pass_rules_swsd.json`、`source_arm_pass_rules_rcsd.json`、`final_generation_decisions.json`、`frcsd_source_road_map.json`、兼容 `source_movement_policy_swsd.json` / `source_movement_policy_rcsd.json`、`frcsd_road_next_road_audit.json` 与 `frcsd_road_next_road_issue_report.json`。 |

## 已冻结真实 Case 基线

`1019789 / 38724646 / 950044` 三个真实 Case 的 P01-Final 结果已冻结为 accepted baseline：

- 基线目录：`modules/p01_arm_build/baselines/p01_final_three_cases_accepted_2026-05-12/`
- 冻结源 run root：`outputs/_work/p01_adv_right_inside_fix/`
- `1019789`：本轮结果与上一轮用户已目视确认正确的 direction-fix 结果完全一致，冻结为 accepted。
- `38724646`：本轮包含路口内提前右转修正，`621439810` 进入 F3 Arm 并生成 `621439810 -> 617826765`，原始证据为 `SWSD#5930602`；整体冻结为 accepted。
- `950044`：本轮结果与上一轮 direction-fix 结果完全一致，冻结为 accepted；低置信 SWSD basic fallback 关系保留审计标记，不阻断验收。
- 三个 Case 的冻结输出均无重复 `road_id + next_road_id`。

## 未完全闭合项

- final RoadNextRoad `turntype` 输出编码已按模块契约固定为 `unknown=0 / straight=1 / left=2 / right=3 / uturn=4`；真实 RCSD 编码规范仍需用户提供权威材料确认。
