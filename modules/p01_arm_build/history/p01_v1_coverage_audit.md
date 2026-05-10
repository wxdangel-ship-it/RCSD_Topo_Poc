# P01 v1.0.0 需求覆盖审计

审计主源：`/mnt/e/_chatgpt_sync/RCSD_Topo_Poc/P01_1/RCSD_Topo_Poc__P01__REQUIREMENT_v1.0.0.md`

审计对象：`p01_arm_build` 模块文档、SpecKit、A1 / A2 / P01-Final 实现与测试。

状态取值：已实现 / 部分实现 / 未实现 / 不适用 / 需确认。

| 序号 | 需求项 | 状态 | 实现 / 测试事实 |
| --- | --- | --- | --- |
| 1 | P01 最终目标为 F-RCSD RoadNextRoad | 已实现 | `final_road_next_road.py` 生成 `frcsd_road_next_road.geojson`；`runner.py` 写出 final JSON / GeoJSON / review 产物；测试覆盖 final generation。 |
| 2 | 语义路口定义 | 已实现 | `topology.py` 按有效 `mainnodeid` 聚合，无效值退化为单节点；A1 tests 覆盖 semantic junction。 |
| 3 | Arm 基于拓扑追溯 | 已实现 | `topology.py` 输出 InitialArm / FinalArm / ArmTrace / ThroughDecisionAudit；tests 覆盖 trace 与 kind-aware stop。 |
| 4 | formway bit7 / bit8 位运算 | 已实现 | `special_roads.py` 解析整数 formway 并使用 bit7 / bit8；tests 覆盖 bit 运算与缺失 / 不可解析 audit。 |
| 5 | 提前左转 / 提前右转规则 | 已实现 | bit8 road 可进入 Arm member 且排除 trunk；bit7 road 排除 member / seed / connector / trunk。 |
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
| 16 | corrected_final_arms | 已实现 | `runner.py` 写出 `corrected_final_arms.json`；tests 覆盖字段保留与输出。 |
| 17 | P01-A2 LogicalArmGroup | 已实现 | `alignment.py` 构建 LogicalArmGroup、RawArmAlignment、ArmBuildFeedback；`test_p01_arm_alignment.py` 覆盖 stable/missing/partial/conflict 等场景。 |
| 18 | F-RCSD:Road.Source | 已实现 | `final_road_next_road.py` 读取并校验 Source；异常进入 issue，不生成相关 final pair。 |
| 19 | Source + 几何完全一致映射 | 已实现 | `final_road_next_road.py` 使用 exact geometry key 按 Source 限定源数据集；missing / ambiguous 进入 issue；tests 覆盖。 |
| 20 | 同源继承 | 已实现 | 同源 pair 直接查源 RoadNextRoad evidence；tests 覆盖 same-source inheritance。 |
| 21 | 不同源 primary source | 已实现 | 跨源 pair 使用 from road Source 选择 primary source；tests 覆盖 cross-source generation。 |
| 22 | 最终生成阶段 RoadNextRoad 缺失视为不通 | 已实现 | SourceMovementPolicy 输出 prohibited；final GeoJSON 不生成缺失 pair；tests 覆盖 missing no generation。 |
| 23 | 平行支路数量一致性 | 部分实现 | count mismatch 输出 `parallel_branch_count_mismatch_manual_review_required` 与 `data_error`；源有平行支路而 F-RCSD 没有输出 `source_parallel_branch_missing_in_frcsd`。稳定顺序配准未作为独立对象输出，role-level policy 承担生成决策。 |
| 24 | RCSD -> SWSD fallback | 已实现 | `final_road_next_road.py` 限定 from Source=1/to Source=2 且 primary to_arm 缺失时 fallback，并检查 entering arm road count；tests 覆盖。 |
| 25 | frcsd_road_next_road.geojson | 已实现 | final FeatureCollection 使用 `geometry=null` 与 `id/road_id/next_road_id/type/source/turntype/city_code` properties，包含 duplicate 防护。 |
| 26 | audit / issue report | 已实现 | 输出 `frcsd_source_road_map.json`、`source_movement_policy_swsd.json`、`source_movement_policy_rcsd.json`、`frcsd_road_next_road_audit.json`、`frcsd_road_next_road_issue_report.json`。 |

## 未完全闭合项

- 平行支路稳定顺序配准未形成独立审计对象；实现以 role-level policy、count mismatch issue 与 manual review 防护完成生成约束。
- 真实 1019789 RoadNextRoad case 依赖内网数据路径；本地可访问路径不存在时，只能完成 synthetic / fixture 验证并提供内网命令。
