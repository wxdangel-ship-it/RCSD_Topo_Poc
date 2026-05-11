# 04 方案策略

## 总体策略

P01-A1 按“输入读取 -> 语义路口 -> seed -> trace -> arm 聚合 -> FinalArm 兜底验证 -> RoadNextRoad-aware movement -> corrected trunk -> 输出审计 -> 目视审查”的顺序实现。P01-A2 按“读取 A1 run root -> ArmProfile -> candidate evidence -> evidence graph -> LogicalArmGroup -> 输出审计 -> 目视审查”的顺序实现。P01-Final 按“ArmSourceProfile -> SWSD / RCSD SourceArmPassRule -> 规则源选择 -> F-RCSD 道路角色投影 -> final RoadNextRoad 输出”的顺序实现。精确源 Road 映射只作为审计 / 置信增强证据。所有构建与配准规则优先基于结构证据，不通过几何形态反推业务语义。

## 数据读取

使用 Fiona 读取矢量数据，统一字段大小写后构建轻量 Node / Road 模型。CRS、feature count、字段缺失情况写入 preflight。

## 语义路口

有效 `mainnodeid` 聚合为语义路口；无有效 `mainnodeid` 时按 Node 自身成组。internal road 是两端都落在当前 member node 集合内的 Road。

## Seed、特殊转向和 Right-Turn

一端在当前路口、一端在外部的 Road 是 seed 候选。P01-A1 正式特殊转向识别采用 `formway` bit 运算：

- `(formway & 128) != 0`：提前右转 road。
- `(formway & 256) != 0`：提前左转 road。

提前右转 road 不进入 seed、connector、member 或 trunk，必须生成 `AdvanceRightTurnRelation` 或明确 issue。bit7 候选范围包括直接连接当前语义路口 member node 的 road，以及 Arm 非特殊 inbound / bidirectional seed 外侧节点相邻的 bit7 road，避免提前右转接在路口前 seed 外侧时被漏掉。连续 bit7 road 链按一条 Arm 级提前右转 relation 输出，链内 road segment 仍保留在 relation 的 `advance_right_turn_road_ids` 中。提前左转 road 可以进入 Arm member，但必须标记并从 trunk 中排除；未进入 Arm member 的外侧 bit8 road 不计为当前 Arm 的提前左转。

`--right-turn-formway-value` 仅保留为 legacy 显式右转 / 渠化右转排除参数；bit7 优先于 legacy 参数，不会被静默写入 `excluded_right_turn_road_ids`。字段缺失、不可解析或未声明确认值时不做几何反推。

## Trace

trace 从 seed 外侧端点继续。每步只沿拓扑连接向外追溯：

- `kind != 4` 的语义节点组原则上需要继续追溯，除非命中 dead end、patch boundary 或 loop。
- `kind = 2048` 作为明确 T 型路口，按当前追溯方向裁决横向主通道 through 与竖向侧支 terminal。
- `kind = 4` 先评估实际拓扑是否符合 T 型特征；符合则按 T 型规则，不符合则作为语义边界停止。
- degree 2 语义节点组可输出 `simple_through` 并继续。
- degree 0/1 输出 `dead_end`。
- degree >= 3 必须结合 kind、当前追溯方向和 continuation 角度判断；如果 T 型主侧向无法稳定确认，则输出 `ambiguous_boundary` 与 `t_junction_uncertain`，不静默 through。
- 回到当前路口输出 `loop_to_current_junction`。
- 找不到下一条可用 Road 输出 `patch_boundary`。

## Arm 聚合

按 trace 的终端类型与终端语义路口 ID 聚合 InitialArm。FinalArm 默认复制 InitialArm 并写入 `not_applied`；当 InitialArm 数量大于 LocalArmCandidate 数量、LocalArmCandidate 完整覆盖全部 InitialArm，且至少一个候选对应多个 InitialArm 时，FinalArm 采用局部趋势兜底聚合并写入 `local_candidate_fallback`。

经过兜底聚合或包含多个 source InitialArm 的 FinalArm 会执行 relaxed reverse / supplemental trace validation。该验证只尝试放宽 `ambiguous_boundary / semantic_boundary / t_side_terminal / dead_end` 等保守停止点来评估 source InitialArm 是否收敛到同一语义路口或合理终端，不改写原始 trace 和 through decision。`conflict` 进入 P0；`weak_validated / unvalidated` 至少进入 P1，并作为下游 audit risk 透传。

每个 Arm 在 member road 中排除提前左转 / 提前右转后计算 trunk。唯一最小闭环输出 `complete_min_loop`；无完整闭环但存在可解释主链输出 `partial`；没有完整闭环但 Arm 有非特殊 seed road 时，退回这些局部 seed 作为 `partial` 主干审计结果；无可用主链输出 `none`；多条等价最小闭环输出 `ambiguous`。FinalArm fallback 合并时必须聚合来源 InitialArm 的特殊转向、trunk 与 relation 字段。

## 局部趋势候选

为辅助识别 trace 在 T 型或 ambiguous boundary 前被过度切碎的 case，模块额外输出 `LocalArmCandidate`。该候选只基于当前语义路口 seed road 从 member node 指向外侧 node 的局部趋势，把同侧进入 / 退出 / 双向 seed 归为参考分组，并可保留少量方向一致的外侧 stub road 作为目视证据。它不使用目标 case ID；当候选完整覆盖 InitialArm 时可进入 FinalArm 兜底聚合。

## 输出与 QA

JSON 输出承担机器审计，GPKG 输出承担 GIS 审查，PNG 输出承担快速目视判断。summary 与 review index 承担批量筛查和人工优先级排序。

## A2 Arm 配准

A2 以 F-RCSD FinalArm 为目标承载体。每个 FinalArm 先归一化为 ArmProfile，汇总 InitialArm、LocalArmCandidate、ArmTrace 与 ThroughDecisionAudit 证据。候选边覆盖 FRCSD-SWSD、FRCSD-RCSD 与 SWSD-RCSD，评分由 seed role、局部趋势、trace / terminal、road coverage 和 geometry 辅助证据组成。

几何只作为辅助分数；非几何证据不足时不得 high confidence。A2 形成跨三源 LogicalArmGroup，并显式区分 source_missing / source_partial 与 over_split / over_merged / conflict / uncertain。over_merged 不自动拆分，只输出 ArmBuildFeedback。

## RoadNextRoad-aware ArmMovement 与 P01-Final

RoadNextRoad 在 A1 阶段只表达 allowed evidence；缺失只输出 `no_allowed_evidence`，不代表禁止。movement_type 使用 same-arm、唯一 stable straight target、trunk / LocalArmCandidate 方向连续性和相对侧向关系判定，不使用 `turnType / turntype`。

trunk correction 只允许 stable straight receiving evidence 参与：`movement_type = straight`、`straight_target_status = unique_straight_target`，且置信度为 high / stable。

P01-Final 中，SWSD / RCSD RoadNextRoad 先抽象为进入道路角色到目标 Arm 的通行规则。`full_allowed` 生成到目标 Arm 全部退出 Road；`prohibited` 不生成；主干道路 / 平行支路的部分目标覆盖进入 `data_error_partial_target_coverage`，不自动投影。advance-left left-receiving only 与 uturn trunk only 是合法特殊范围。F-RCSD Arm 可以混源，规则源按 SWSD 结构匹配、RCSD 结构匹配、SWSD basic rule 兜底选择；参考 RCSD 但目标 Arm 缺失时 fallback 到 SWSD basic rule。精确源 Road 映射、source map 与旧 SourceMovementPolicy 只用于审计和兼容解释。平行支路以 `parallel_branch_alignment.json` 独立记录 source missing、count matched ordered、count mismatch 与 insufficient geometry ordering 状态。
