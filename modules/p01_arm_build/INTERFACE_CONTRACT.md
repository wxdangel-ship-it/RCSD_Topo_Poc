# P01 Arm Build 接口契约

## 1. 模块定位

`p01_arm_build` 覆盖 P01 v1.0.0 的三段成果链路：

- `P01-A1`：单源 Arm 构建、特殊转向识别、ArmMovement 与 trunk 修正。
- `P01-A2`：三源 Arm 配准与 `LogicalArmGroup` 构建。
- `P01-Final`：生成最终 `F-RCSD:RoadNextRoad.geojson`。

P01 的最终承载体是 F-RCSD Road。模块输出 F-RCSD 道路在路口处允许通行到哪些 F-RCSD 退出道路，并保留完整 ArmSourceProfile、SourceArmPassRule、final generation decision、source map、兼容 source policy、audit 与 issue report。

## 2. 入口状态

仓库不提供 P01 repo 官方 CLI、`scripts/` 常驻脚本、Makefile 目标、模块 `__main__.py` 或模块 `run.py`。当前稳定调用面是模块内 callable runner。

A1 / P01-Final：

```python
from rcsd_topo_poc.modules.p01_arm_build.runner import run_p01_arm_build_from_args
```

A2：

```python
from rcsd_topo_poc.modules.p01_arm_build.alignment_runner import run_p01_arm_alignment_from_args
```

文本证据包与单 Case 全量执行位于模块内 dev helper，仅用于取证、复现和开发验收，不登记为正式执行入口。

## 3. 输入契约

### 3.1 A1 / P01-Final 输入

必选参数：

- `--swsd-nodes`
- `--swsd-roads`
- `--rcsd-nodes`
- `--rcsd-roads`
- `--frcsd-nodes`
- `--frcsd-roads`
- `--junction-group <swsd_junction_id>,<rcsd_junction_id>,<frcsd_junction_id>`，可重复传入。
- `--out-root`

可选参数：

- `--run-id`
- `--right-turn-formway-value`：legacy 显式右转 / 渠化右转排除兼容参数；bit7 提前右转优先进入 `AdvanceRightTurnRelation` 或 issue。
- `--swsd-road-next-road`：SWSD `RoadNextRoad.json` / `RoadNodeRoad.json` / GeoJSON。
- `--rcsd-road-next-road`：RCSD `RoadNextRoad.geojson` / JSON。
- `--frcsd-road-next-road`：F-RCSD RoadNextRoad JSON / GeoJSON；仅用于 A1 同源 movement evidence 审计，P01-Final 仍生成新的 `frcsd_road_next_road.geojson`。

字段要求：

- Node 最少字段：`id / mainnodeid / geometry`；可选 `kind`。
- Road 最少字段：`id / snodeid / enodeid / direction / geometry`；可选 `formway`。
- F-RCSD:Road 必须提供 `Source` 用于 P01-Final。
- `grade / grade_2` 禁止进入 P01 主规则。

### 3.2 A2 输入

```text
--arm-build-run-root <P01_A1_RUN_ROOT>
--out-root
--run-id
```

A2 从 A1 `preflight.json` 读取原始数据路径，从 `cases/<group>/<dataset>/` 读取 A1 JSON 结果；不要求用户重新传六类 Node / Road 基础路径。

## 4. A1 输出对象

每个 `cases/<group_id>/<dataset>/` 至少输出：

- `junction_context.json`
- `initial_arms.json`
- `final_arms.json`
- `final_arm_validation.json`
- `corrected_final_arms.json`
- `advance_right_turn_relations.json`
- `local_arm_candidates.json`
- `arm_traces.json`
- `through_decisions.json`
- `issue_report.json`
- `arm_movements.json`
- `road_movement_evidence.json`
- `arm_receiving_road_roles.json`
- `trunk_corrections.json`
- `review_layers.gpkg`
- `p01_arm_review.png`

run root 输出：

- `preflight.json`
- `case_results.json`
- `p01_arm_build_summary.json`
- `p01_arm_build_review_index.csv`
- `cases/<group_id>/compare/p01_arm_compare.png`
- `cases/<group_id>/compare/p01_arm_compare_layers.gpkg`
- `cases/<group_id>/compare/p01_arm_compare_summary.json`

核心业务对象字段以 v1.0.0 需求为准，至少覆盖：

- `JunctionContext`：member nodes、internal roads、seed roads、excluded right-turn roads、advance left/right roads、formway audit 与 input issue flags。
- `InitialArm / FinalArm / corrected_final_arms`：member roads、seed/connector roads、inbound/outbound/bidirectional roads、terminal、build status、risk flags、advance-left fields、trunk fields、advance-right relation refs、FinalArm validation refs。
- `FinalArmValidation`：兜底 FinalArm 的 relaxed reverse / supplemental trace validation 状态、收敛状态、relaxed trace road/node evidence、terminal、confidence、risk 与 issue flags。
- `AdvanceRightTurnRelation`：from/to arm、advance right turn roads、trace roads/nodes、trace status、confidence、risk flags。
- `ArmTrace / ThroughDecisionAudit`：seed、trace path、decision status、stop type/reason、issue flags。
- `RoadMovementEvidence / ArmMovement / ReceivingRoadRole / TrunkCorrection`：RoadNextRoad mapping、full from_arm x to_arm movements、movement type audit、receiving roles、corrected trunk reason。

## 5. A1 业务规则

- 语义路口按有效 `mainnodeid` 聚合；`null / 空字符串 / 0 / 0.0 / none / null 字符串 / nan` 视为无效。
- internal road 两端均在当前 member nodes 内，不进入 Arm。
- seed road 一端在当前语义路口、一端在外部。
- `formway` bit 识别必须使用位运算：`bit7 = 128` 为提前右转，`bit8 = 256` 为提前左转。
- bit7 road 不进入 Arm `member / seed / connector / trunk`，必须进入 `AdvanceRightTurnRelation` 或 issue。
- bit8 road 可进入 Arm member，但不得进入 `trunk_road_ids`。
- trace 发生在语义路口层面；允许继续追溯的状态只有 `simple_through` 与 `t_mainline_through`。
- `kind != 4` 原则继续追溯；`kind = 2048` 作为明确 T 型路口按当前追溯方向裁决；`kind = 4` 先评估 T 型特征再决定停止或继续。
- `FinalArm` 默认与 `InitialArm` 一一对应；trace 过度切碎且 `LocalArmCandidate` 完整覆盖时可采用局部趋势兜底聚合。
- `FinalArmValidation` 是 A1 内部健壮性验证，不是新阶段，也不是 A2 / P01-Final。它只对 `local_candidate_fallback` 或多 source InitialArm 的 FinalArm 做放宽终止条件的反向 / 补充追溯验证，不覆盖原始 InitialArm、ArmTrace 或 ThroughDecisionAudit。
- `FinalArmValidation.validation_status` 支持 `not_required / validated / weak_validated / unvalidated / conflict`。`conflict` 触发 P0，`weak_validated / unvalidated` 至少触发 P1，并在下游 audit 中保留 validation risk。
- `trunk_status` 至少支持 `complete_min_loop / partial / none / ambiguous`。

## 6. RoadNextRoad-aware ArmMovement

RoadNextRoad 表达 `road_id -> next_road_id` 的允许通行 evidence。

在 ArmMovement 阶段：

- RoadNextRoad 存在：`allowed_supported`
- RoadNextRoad 缺失：`no_allowed_evidence`
- `no_allowed_evidence` 不等于 prohibited。

`raw_turn_type` 只保存 `turnType / turntype` 审计字段，不得用于 `movement_type` 判定。

`movement_type` 支持 `straight / left / right / uturn / unknown`，按 same-arm、唯一稳定 straight target、trunk / LocalArmCandidate 走廊连续性、RoadNextRoad trunk evidence 与相对侧向关系判定。T 型可作为语义结构参与判断；Y-like / skew-like / diverge-like / merge-like / curved-mainline-like 只能作为后验审计标签。

trunk 修正只使用 stable straight receiving evidence：`movement_type = straight`、`straight_target_status = unique_straight_target`、confidence high/stable 且 RoadNextRoad 成功映射到目标 Arm 退出道路。无 stable straight receiving evidence 时不得排除 trunk。

## 7. A2 输出契约

A2 输出根目录 `<out-root>/<run-id>/`，至少包含：

- `preflight.json`
- `p01_arm_alignment_summary.json`
- `p01_arm_alignment_review_index.csv`
- `cases/<group_id>/alignment_summary.json`
- `cases/<group_id>/logical_arm_groups.json`
- `cases/<group_id>/arm_build_feedback.json`
- `cases/<group_id>/source_extra_arms.json`
- `cases/<group_id>/arm_alignment_candidates.json`
- `cases/<group_id>/<source_dataset>/raw_arm_alignment.json`
- `cases/<group_id>/<source_dataset>/arm_alignment_issue_report.json`
- `cases/<group_id>/<source_dataset>/arm_alignment_review_layers.gpkg`
- `cases/<group_id>/<source_dataset>/p01_arm_alignment_review.png`
- `cases/<group_id>/compare/p01_arm_alignment_compare.png`
- `cases/<group_id>/compare/p01_arm_alignment_compare_layers.gpkg`

`LogicalArmGroup` 至少包含 `logical_arm_group_id / junction_group_id / frcsd_arm_ids / swsd_arm_ids / rcsd_arm_ids / group_status / acceptable_for_downstream / missing_datasets / partial_datasets / over_split_datasets / over_merged_datasets / evidence_summary / risk_flags / review_priority`。

A2 必须区分 coverage missing / partial 与 grouping error；over-merged 不自动拆分，只输出 `ArmBuildFeedback`。

## 8. P01-Final 输出契约

每个 `cases/<group_id>/FRCSD/` 至少输出：

- `frcsd_road_next_road.geojson`
- `arm_source_profiles.json`
- `source_arm_pass_rules_swsd.json`
- `source_arm_pass_rules_rcsd.json`
- `final_generation_decisions.json`
- `frcsd_source_road_map.json`
- `source_movement_policy_swsd.json`
- `source_movement_policy_rcsd.json`
- `parallel_branch_alignment.json`
- `frcsd_road_next_road_audit.json`
- `frcsd_road_next_road_issue_report.json`
- `frcsd_road_next_road_review_layers.gpkg`
- `frcsd_road_next_road_review.png`

`frcsd_road_next_road.geojson` 为 FeatureCollection，Feature `geometry = null`，properties 至少包含 `id / road_id / next_road_id / type / source / turntype / city_code`。

`turntype` 使用模块契约映射：

```text
unknown -> 0
straight -> 1
left -> 2
right -> 3
uturn -> 4
```

该映射是仓库内已冻结的输出编码。真实 RCSD 规范若提供不同编码，应以规范更新为独立入口变更任务，并同步修改本契约、实现和回归测试。

`parallel_branch_alignment.json` 记录 F-RCSD 平行支路与源侧平行支路的稳定顺序配准审计，字段包括：

- `dataset`
- `junction_group_id`
- `source_dataset`
- `arm_id`
- `frcsd_parallel_branch_road_ids`
- `source_parallel_branch_road_ids`
- `alignment_status`
- `alignment_order_rule`
- `aligned_pairs`
- `issue_flags`

`alignment_status` 至少支持：

- `not_needed`
- `source_missing_in_frcsd`
- `count_matched_ordered`
- `count_mismatch_manual_review_required`
- `insufficient_geometry_for_ordering`

P01-Final 规则：

- F-RCSD:Road.Source = `1` 表示来源 RCSD，`2` 表示来源 SWSD。
- F-RCSD Arm 可以混源；`Source` 只能在 Road 级解释，不得把整个 Arm 简化为单一来源。
- P01-Final 先从 SWSD / RCSD RoadNextRoad、ArmMovement、进入道路角色与目标 Arm 退出道路集合抽象 `SourceArmPassRule`，再把规则投影到 F-RCSD 道路角色。
- 精确源 Road 映射降级为 audit / confidence evidence；Source 缺失、非法、几何匹配缺失或多匹配必须进入 issue，但不得在规则明确且承载道路明确时直接阻断规则级生成。
- Source + CRS 归一化后的 rounded exact geometry 只作为审计强证据；不得使用空间接近或最近邻替代。
- 当前 F-RCSD 未提供可作为权威来源映射的 source road id 字段；`baseroadid` 在已验证 case 中为空，不作为来源映射依据。
- `full_allowed` 的生成范围是进入道路角色到目标 Arm 全部退出 Road，不是只生成到目标主干 Road。
- 主干道路 / 平行支路若只覆盖部分目标退出 Road，必须进入 `data_error_partial_target_coverage / manual_review_required`，不得作为正常 partial 规则投影。
- advance-left left-receiving only、advance-left trunk only 与 uturn trunk only 是合法特殊范围，不按 partial coverage error 处理。
- 完全同源进入 Arm 优先采用对应源规则；混源进入 Arm 先匹配 SWSD 结构，其次 RCSD 结构，均不吻合时使用 SWSD basic rule 并记录低置信审计。
- 参考 RCSD 但 RCSD 目标 Arm 缺失时，fallback 到 SWSD basic rule；SWSD basic 也无法支撑时不生成并进入人工审计。
- 平行支路数量不一致进入 `data_error / manual_review_required`；source 有平行支路而 F-RCSD 没有时以主路逻辑为主，并写入 `source_parallel_branch_missing_in_frcsd` 审计。
- trunk -> right Arm 不通且没有 parallel_branch 或 advance_right relation 承载时，输出 `data_error_or_missing_right_turn_carrier`。
- `source_movement_policy_swsd.json` / `source_movement_policy_rcsd.json` 保留为兼容审计对象，不得作为唯一生成前提。

## 9. 文本证据包与 dev helper

文本证据包 helper 可选带入：

- `--swsd-road-node-road`
- `--swsd-road-next-road`
- `--rcsd-road-next-road`

打包后的 Node / Road GPKG 必须保留原始属性，并补齐 P01 消费的规范字段：Node 至少包含 `id / mainnodeid / kind`，Road 至少包含 `id / snodeid / enodeid / direction / formway`；F-RCSD Road 如有 `Source/source` 字段必须随包保留。解包时恢复对应文件到 `SWSD/`、`RCSD/` 或 `FRCSD/` 目录。`modules/p01_arm_build/dev_helpers/run_p01_case_full.sh` 可消费已解包 case 目录或文本证据包，自动调用 A1 / P01-Final runner。该脚本不是 repo 官方 CLI。

## 10. 自动检查与 QA

- CRS、输入路径、字段、feature count 写入 preflight。
- RoadNextRoad 记录必须进入 mapped 或明确 mapping issue。
- `turnType / turntype` 不参与 movement_type。
- `grade / grade_2` 不参与 P01 主规则。
- corrected trunk 不得包含 bit7 / bit8 special road。
- final RoadNextRoad 不得出现重复 `road_id + next_road_id`。
- review GPKG / PNG 支持审查 Arm、trunk、corrected trunk、special turns、ArmMovement、RoadMovementEvidence、ArmSourceProfile、SourceArmPassRule、final generation decision、generated RoadNextRoad、source map 与 issues。
