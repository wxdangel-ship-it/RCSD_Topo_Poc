# T09 Step1/2/3：SWSD 现场证据还原与 FRCSD 通行限制建模需求说明书

- 文档类型：SpecKit 需求说明书
- 模块代号：T09
- 需求范围：T09 Step1 / Step2 / Step3
- 状态：Draft / ready for CodeX task decomposition
- 需求来源：2026-05-31 业务讨论

## 1. 背景与目标

T09 的总体业务目标是：基于 SWSD 数据还原路口处的交通限制，并在后续阶段对融合后的 FRCSD 数据恢复路口处的交通限制。

本需求说明书覆盖 T09 的前三步：

1. 构建 SWSD 路口 Arm，并建立 Arm 与 Arm 间的 Movement。
2. 以 Movement 为单元，通过原始四维 restriction 与 arrow 地面箭头，回溯当前 SWSD Arm / Movement 的现场禁止通行证据，并输出 Arm 级的箭头排布、特殊转向载体和禁止通行规则证据。
3. 基于 T06 输出的 SWSD Segment 与 F-RCSD 关系，将 Step1/2 的 SWSD Movement 禁止通行证据投影到融合后的 FRCSD，输出 `frcsd_restriction.gpkg`。

T09 Step1/2 的定位是 **SWSD 现场证据模糊还原层**。T09 Step3 使用 T06 的 F-RCSD 生产关系作为 Arm 映射依据，对融合后的 FRCSD 构建禁止通行关系。Step3 当前只输出 restriction 形态，不生成 FRCSD `RoadNextRoad`。

## 2. 范围

### 2.1 本阶段包含

- 基于 SWSD Node / Road 与 T01 Segment 构建 SWSD 语义路口的 Arm。
- 重点处理 `kind_2 = 4` 的语义交叉路口。
- 建立 Arm-to-Arm Movement 候选全集。
- 消费 T08 Tool7 显性 restriction 输出或等价原始四维 restriction LineString，作为最高优先级禁止通行证据。
- 消费 T08 Tool8 显性 arrow 输出或等价原始四维 Laneinfo arrow LineString，恢复进入 Arm 的道路级与车道级箭头排布。
- 基于完整地面箭头排布形成现场佐证、解释证据或冲突审计证据。
- 识别提前左转、辅路提右、非辅路提前右转等特殊 carrier / displacement 证据。
- 输出 Arm 级、Movement 级、road-pair 级的结构化证据和审计信息。
- Step3 消费 T06 Step3 的 FRCSD Road / Node 与 SWSD-FRCSD Segment 关系输出。
- Step3 基于 SWSD Arm-to-Arm 禁止证据，生成 FRCSD road-to-road 禁止通行关系。
- Step3 输出 `frcsd_restriction.gpkg/csv/json` 与审计 summary。

### 2.2 本阶段不包含

- 不生成 FRCSD `RoadNextRoad`。
- 不引入未确认的理论交通限制，例如“辅路默认不能调头 / 左转”。
- 不因缺少 allowed evidence 自动推导 prohibited。
- 不将拓扑方向不可达误表达为交通规则禁止。
- Step3 暂不消费 FRCSD 车道级箭头；后续可用 FRCSD arrow 或轨迹通行能力做补充对齐。
- Step3 不修改 T06 输出，不反向改写 SWSD / FRCSD 输入。

## 3. 输入

### 3.1 基础拓扑输入

- T01 模块输出的 `Segment`。
- SWSD Node 数据，至少需要：`id / mainnodeid / kind_2 / geometry`。
- SWSD Road 数据，至少需要：`id / snodeid / enodeid / direction / geometry`，并尽量保留 `kind / formway / segmentid` 等字段。

### 3.2 restriction 输入

restriction 表达当前路口 road 级方向的不可通行关系：

- 几何为有向 `LineString`。
- 几何与 SWSD 路口 Road 基本一致。
- 业务上按 `inLinkID -> outLinkID` 或等价字段表达从进入 road 到退出 road 的禁止通行。
- restriction 可能来源于地面箭头，也可能来源于实地交限；T09 Step1/2 统一视为实地禁止通行证据。

### 3.3 arrow 输入

arrow 表达进入路口处 road 级方向的地面箭头：

- 几何为有向 `LineString`。
- 几何与 SWSD 路口前 Road 基本一致。
- 同一道路方向包含道路级 arrow group 与车道级 arrow sequence。
- 箭头必须保留 lane 顺序、lane 数量、原始编码和方向匹配审计。

### 3.5 Step3 FRCSD 输入

T09 Step3 采用技术路线 2：通过 T06 的 Segment 替换关系建立 SWSD Arm 与 FRCSD Arm 的映射，不在 FRCSD 上独立重复 P01 式 Arm 构建作为主策略。

Step3 输入至少包括：

- T09 Step1/2 输出：`t09_swsd_arms.* / t09_arm_movements.* / t09_evidence_items.* / t09_restored_field_rules.*`。
- T06 Step3 输出的 FRCSD Road：`t06_frcsd_road.gpkg` 或等价 GeoJSON。
- T06 Step3 输出的 FRCSD Node：`t06_frcsd_node.gpkg` 或等价 GeoJSON。
- T06 Step3 新增的 `t06_step3_swsd_frcsd_segment_relation.gpkg/csv/json`。

FRCSD Road / Node 必须保留 `source` 字段：`source=1` 表示 RCSD 来源，`source=2` 表示 SWSD 保留来源。T09 Step3 只使用该字段区分当前 FRCSD road 的来源，不通过该字段反推通行限制。

### 3.4 原始 SW 箭头编码定义

T09 必须按以下原始 SW 箭头码表解析 `Arrow_Dir` 或等价 arrow 字段。实现时应同时保留原始 code 与规范化 token，不得只保留中文展示值。

| code | 中文定义 | 规范化 token |
|---|---|---|
| `9` | 未调查 | `uninvestigated` |
| `a` | 直 | `straight` |
| `b` | 左 | `left` |
| `c` | 右 | `right` |
| `d` | 调 | `uturn` |
| `e` | 直调 | `straight,uturn` |
| `f` | 直右 | `straight,right` |
| `g` | 直左 | `straight,left` |
| `h` | 左直右 | `left,straight,right` |
| `i` | 调直右 | `uturn,straight,right` |
| `j` | 调左直 | `uturn,left,straight` |
| `k` | 左右 | `left,right` |
| `l` | 调左 | `uturn,left` |
| `m` | 调左右 | `uturn,left,right` |
| `n` | 调右 | `uturn,right` |
| `o` | 空 | `empty` |
| `p` | 左直右调 | `left,straight,right,uturn` |
| `r` | 斜左 | `slight_left` |
| `s` | 斜右 | `slight_right` |
| `t` | 直斜左 | `straight,slight_left` |
| `u` | 左斜左 | `left,slight_left` |
| `v` | 右斜左 | `right,slight_left` |
| `w` | 调斜左 | `uturn,slight_left` |
| `x` | 直斜右 | `straight,slight_right` |
| `y` | 左斜右 | `left,slight_right` |
| `z` | 右斜右 | `right,slight_right` |
| `0` | 调斜右 | `uturn,slight_right` |
| `1` | 斜左斜右 | `slight_left,slight_right` |
| `2` | 直左斜左 | `straight,left,slight_left` |
| `3` | 直左斜右 | `straight,left,slight_right` |
| `4` | 直右斜左 | `straight,right,slight_left` |
| `5` | 直右斜右 | `straight,right,slight_right` |

说明：

- `9 / uninvestigated` 不能作为禁止通行证据。
- `o / empty` 表示空箭头，默认不能单独作为禁止通行证据。
- 字母型箭头码按大小写不敏感方式归一到小写码表；已确认 `A` 等同于 `a`，表示 `straight`。实现仍需保留原始 code 进入审计。
- 数字 `0` 与字母 `o` 必须严格区分。
- 斜左 / 斜右是否支持普通左转 / 右转，不在本需求中直接折叠；应先作为 `slight_left / slight_right` 保留，后续由 Movement 类型匹配策略显式判定。

## 4. 输出

T09 Step1/2 至少输出以下结构化对象。文件命名可在实现阶段进一步确定，但语义对象必须稳定。

### 4.1 `T09SwsdArm`

用于表达 SWSD 语义路口的道路方向业务单元。

核心字段至少包含：

- `junction_id`
- `arm_id`
- `member_node_ids`
- `internal_road_ids`
- `seed_road_ids`
- `connector_road_ids`
- `segment_ids`
- `inbound_road_ids`
- `outbound_road_ids`
- `bidirectional_road_ids`
- `approach_road_ids`
- `exit_road_ids`
- `trunk_road_ids`
- `parallel_branch_road_ids`
- `advance_left_road_ids`
- `auxiliary_right_turn_road_ids`
- `advance_right_turn_relation_ids`
- `angle_deg`
- `terminal_node_id`
- `terminal_kind`
- `build_status`
- `risk_flags`
- `audit_refs`

### 4.2 `T09ArmMovement`

用于表达 `from_arm -> to_arm` 的候选 Movement。

核心字段至少包含：

- `junction_id`
- `movement_id`
- `from_arm_id`
- `to_arm_id`
- `movement_type`
- `movement_applicability`
- `candidate_road_pair_count`
- `carrier_universe_status`
- `prohibition_status`
- `prohibition_reason`
- `prohibition_confidence`
- `restriction_coverage`
- `partial_basis`
- `remaining_restriction_status`
- `arrow_direction_status`
- `arrow_lane_summary`
- `advance_left_status`
- `advance_right_status`
- `evidence_item_ids`
- `risk_flags`

其中，Movement 级业务证据摘要含义如下：

- `restriction_coverage`：以原始 restriction 为基准，表达当前 Arm-to-Arm Movement 是全部禁行、部分禁行、没有显式 restriction 证据，还是不适用。
- `partial_basis`：当 restriction 只覆盖 Movement 的部分承载对象时，表达 partial 发生在进入 Arm 子集、退出 Arm 子集，还是只能定位到承载子集但无法继续解释。
- `remaining_restriction_status`：当 partial 存在时，表达未被 restriction 覆盖的剩余部分当前只能视为没有显式 restriction 证据，不反推为通行。
- `arrow_direction_status`：表达进入 Arm 的道路级箭头是否支持该 Movement、是否完整排除了该 Movement，或是否存在空车道、未调查、未知、不完整等无法强推的情况。
- `arrow_lane_summary`：记录匹配到的道路级箭头数量、车道数量、支持 / 排除 / 空 / 未调查 / 未知车道计数和原始箭头序列，作为 `arrow_direction_status` 的审计摘要。
- `advance_left_status`：仅对左转 Movement 表达进入 Arm 是否存在提前左转载体证据。
- `advance_right_status`：仅对右转 Movement 表达进入 Arm 是否存在不经过核心路口的提前右转，或经过核心路口关系表达的提前右转证据。

### 4.3 `T09EvidenceItem`

用于表达所有证据来源，至少覆盖：

- `restriction`
- `arrow`
- `complete_arrow_exclusion`
- `special_carrier`
- `topology_not_applicable`
- `conflict`

每条证据必须能追溯到原始输入 feature、匹配的 Arm / Movement / road-pair、几何匹配方式、字段解析方式和置信度。

### 4.4 `T09RestoredFieldRule`

用于表达面向后续 T09 Step3 消费的现场还原规则。

核心字段至少包含：

- `junction_id`
- `from_arm_id`
- `to_arm_id`
- `movement_type`
- `field_rule_status`
- `rule_scope`
- `supporting_evidence_ids`
- `conflicting_evidence_ids`
- `inference_level`
- `confidence`
- `risk_flags`

### 4.5 `FrcsdRestriction`

用于表达 Step3 输出到 FRCSD 的 road-to-road 禁止通行关系。输出文件固定为：

- `frcsd_restriction.gpkg`
- `frcsd_restriction.csv`
- `frcsd_restriction.json`
- `t09_step3_frcsd_restriction_summary.json`

核心字段至少包含：

- `restriction_id`
- `LinkID`
- `outLinkID`
- `junction_id`
- `frcsd_junction_id`
- `from_arm_id`
- `to_arm_id`
- `movement_type`
- `restriction_source`
- `source_rule_status`
- `confidence`
- `supporting_evidence_ids`
- `from_frcsd_arm_id`
- `to_frcsd_arm_id`
- `from_road_source`
- `to_road_source`
- `arm_relation_status`
- `risk_flags`

其中 `LinkID` 表达进入 FRCSD Road，`outLinkID` 表达退出 FRCSD Road。单独一个 `LinkID` 不足以表达路口处禁止通行关系。

## 5. 核心业务规则

### 5.1 Arm 构建规则

- Arm 按 SWSD 语义路口构建，优先使用有效 `mainnodeid` 聚合 member nodes。
- 两端均在当前 member nodes 内的 Road 是 internal road，不作为普通外向 seed。
- 一端在当前语义路口、一端在外部的 Road 是 seed 候选。
- T01 Segment 用作 Arm 主方向、主干连续性与远端终止判断的重要参考，但不是 Arm 的唯一成员来源。
- 特殊道路、辅路和未进入 Segment 的 road 不得被静默丢弃，必须进入 Arm special fields 或 issue / risk audit。

### 5.2 Movement 与 carrier universe

- Movement 以 Arm-to-Arm 为业务单元。
- Movement 禁止证据应先在 road-pair 粒度成立，再汇总到 Arm-Movement 粒度。
- `carrier universe` 表示从 `from_arm` 可进入路口的 road 到 `to_arm` 可退出路口的 road 的候选 road-pair 集合。
- 若只覆盖部分 road-pair，Movement 必须表达为 `partially_prohibited` 或更细粒度状态，不得直接放大为 `fully_prohibited`。

### 5.3 禁止通行为主线

T09 Step1/2 以禁止通行证据为主线：

- restriction 是最高优先级的显式禁止证据。
- 只有 restriction 中实际存在的禁行，才能改变 Movement 的禁行结果。
- 完整地面箭头排除、提前左转、提前右转与特殊 carrier 只作为 restriction 禁行的现场证据、解释证据或冲突证据；没有 restriction 时不得单独生成禁行。
- 特殊 carrier / displacement 是现场结构证据，不默认等价为整个 Arm-Movement 禁止。
- 拓扑或方向不可达应表达为 `not_applicable / topology_impossible / direction_incompatible`，不表达为交通规则禁止。
- 无禁止证据时，应输出 `no_prohibition_evidence` 或 `unknown`，不得自动输出 allowed。

### 5.4 restriction 禁止证据

当 restriction 能匹配到：

```text
inLinkID ∈ from_arm.approach_road_ids
outLinkID ∈ to_arm.exit_road_ids
```

或等价 road-pair 关系时，生成 road-pair 级 `prohibited_by_restriction`。

汇总规则：

- carrier universe 全量 road-pair 均被 restriction 覆盖：`fully_prohibited_by_restriction`。
- carrier universe 仅部分 road-pair 被 restriction 覆盖：`partially_prohibited_by_restriction`。
- restriction 与 arrow 存在冲突：restriction 优先，同时输出 conflict evidence。

### 5.5 完整箭头排除现场证据

完整箭头排布可以形成“现场未提供该方向箭头”的证据，但不得在没有 restriction 的情况下独立形成禁行结果。完整性门槛如下：

- arrow 成功匹配到进入 Arm。
- arrow 有向几何与进入路口方向一致。
- lane sequence 可解释，且无明显缺失。
- arrow code 全部可解析。
- `9 / uninvestigated` 与 `o / empty` 不参与强禁止推导。
- 目标 Movement 类型可与箭头 token 稳定匹配。
- 不存在未解释的特殊 carrier 覆盖同一 Movement。

满足上述条件，且所有进入车道 arrow token 均不支持目标 Movement 时，输出 `complete_arrow_exclusion / arrow_excludes_movement` 证据，`supports_prohibition=false`，Movement 仍保持 `no_prohibition_evidence`，除非同一 Movement 已有 restriction 禁行。

当 restriction 禁行存在且 arrow 支持该 Movement 时，restriction 仍决定禁行结果，同时输出 conflict evidence；冲突标识只影响审计风险，不改变禁行结论。

不满足完整性门槛时，只能输出：

- `arrow_incomplete_for_prohibition`
- `arrow_ambiguous_for_prohibition`
- `arrow_not_usable_for_prohibition`
- `manual_review_required`

### 5.6 特殊 carrier / displacement

特殊道路优先表达为 carrier 或 displacement 证据，不直接等价为整个 Arm-to-Arm Movement 禁止。

- 提前左转：表达为 `advance_left_carrier_exists / left_turn_carrier_shifted`。
- 辅路提右：进入路口 Road 的 `kind` 同时存在 `12` 与 `0a` 时，表达为 `auxiliary_right_turn_carrier_exists`。
- 非辅路提前右转：进入路口 Road 的 `kind` 存在 `12` 且不存在 `0a` 时，表达为 `pre_junction_non_aux_advance_right_relation`。

只有当中心路口普通 carrier 同时被 restriction 或完整 arrow 排除时，才可进一步表达 `core_junction_movement_prohibited`。

### 5.7 Step3 FRCSD 投影规则

Step3 基于 Step1/2 的 Movement 级证据生成 FRCSD restriction：

- 只有 `T09RestoredFieldRule.field_rule_status = fully_prohibited` 且 Movement `prohibition_reason = explicit_restriction` 的 Movement 可投影为 FRCSD restriction。
- `partially_prohibited` 暂不自动放大到 FRCSD 全 Arm 禁行；必须进入审计或仅投影有明确 carrier 子集映射的部分。
- `no_prohibition_evidence / unknown / not_a_traffic_rule` 不生成 FRCSD restriction。
- `complete_arrow_exclusion`、提前左转、提前右转与特殊 carrier 只作为 Step3 审计证据；不得作为 `restriction_source` 独立生成 FRCSD restriction。
- 提前左转 / 提前右转当前只作为 Movement 证据与审计字段，不在无显式禁止证据时自动生成 FRCSD restriction。

SWSD Arm 到 FRCSD Arm 的映射规则：

- 对被 T06 替换的 SWSD Segment，使用 `t06_step3_swsd_frcsd_segment_relation` 中 `relation_status=replaced` 的 `frcsd_road_ids` 和 SWSD-to-FRCSD node mapping。
- 对未被替换的 SWSD Segment，使用 `relation_status=retained_swsd` 的 FRCSD `source=2` road 作为承载。
- 若一个 SWSD Arm 同时包含多个 Segment，Step3 允许形成混源 FRCSD Arm，但必须在 `source_mix / risk_flags` 中可审计。
- Step3 不依赖 SWSD Road ID 与 FRCSD Road ID 相等；Road ID 相等只作为 `source=2` 保留道路的自然结果。
- 若无法把 SWSD Arm 映射到 FRCSD 进入 / 退出道路，不生成 restriction，并输出审计原因。

FRCSD road-to-road 生成规则：

- 对每条 fully prohibited SWSD Movement，找到映射后的 FRCSD from Arm approach road 集合与 to Arm exit road 集合。
- 对两个集合做笛卡尔积，生成 `LinkID -> outLinkID` 禁止关系。
- 同一 `LinkID + outLinkID + junction_id + movement_type` 不得重复输出。
- 输出几何可使用进入 road 与退出 road 的路口端连接线，若几何无法构造则不得 silent fix，必须记录审计风险。

## 6. 状态枚举建议

### 6.1 `movement_applicability`

- `applicable`
- `not_applicable`
- `topology_impossible`
- `direction_incompatible`
- `manual_review_required`

### 6.2 `prohibition_status`

- `fully_prohibited`
- `partially_prohibited`
- `core_junction_displaced`
- `no_prohibition_evidence`
- `unknown`
- `conflict`
- `not_a_traffic_rule`

### 6.3 `prohibition_reason`

- `explicit_restriction`
- `complete_arrow_exclusion`
- `special_carrier_displacement`
- `topology_not_applicable`
- `direction_not_applicable`
- `insufficient_evidence`
- `conflicting_evidence`

### 6.4 `inference_level`

- `explicit`
- `derived`
- `weak_derived`
- `unknown`
- `conflict`

## 7. 审计与质量要求

T09 Step1/2 涉及 GIS / 拓扑 / 空间数据，必须显式覆盖：

- CRS 与坐标变换正确性。
- 拓扑一致性，不允许 silent fix。
- 几何语义可解释性。
- 审计可追溯性：输入、参数、字段解析、匹配方式、输出和运行环境可定位。
- 性能可验证性。

每条禁止通行规则必须能追溯到至少一个 `T09EvidenceItem`。无法追溯的规则不得进入 `T09RestoredFieldRule`。

## 8. 验收口径

T09 Step1/2 的最小验收应覆盖：

- 完整解析 3.4 中全部 SW arrow code，且区分数字 `0` 与字母 `o`。
- restriction road-pair 匹配可生成显式禁止证据。
- 单条 restriction 不会被误放大为整个 Arm-Movement 禁止。
- 完整 arrow 排除只生成现场证据，不单独生成 Movement 禁止。
- 不完整 arrow、`9`、`o` 不会生成强禁止证据。
- 辅路提右、非辅路提前右转、提前左转优先输出 carrier / displacement，而不是直接输出整个 Movement 禁止。
- 拓扑不可达输出 `not_applicable`，不输出 prohibited。
- 输出包含足够的 JSON / GPKG 或等价审计材料，支持人工和机器复核。
