# 03 Solution Strategy

本文件是 T09 的架构设计 / 需求具体实现策略说明。模块需求见 `../SPEC.md`，稳定输入输出和入口契约见 `../INTERFACE_CONTRACT.md`。

## 1. Step1 输入归一与语义路口准备

T09 首先读取 SWSD Node、SWSD Road、可选 T01 Segment、可选 restriction、可选 arrow，并统一到处理 CRS。读取阶段必须保留输入路径、图层、字段、计数和 CRS 归一信息，写入 summary。

业务上，SWSD Node 负责定义语义路口成员关系；有效 `mainnodeid` 表示所属语义路口，缺失或无效时按单 node 处理。SWSD Road 负责定义路口内外的拓扑连接和道路方向。T01 Segment 用于理解道路连续单元和后续 F-RCSD 承载映射，但它不是 Arm 成员的唯一来源。

正确结果是：每个语义路口都有可审计的 member node 集合，输入缺失或字段异常被显式记录。错误结果是：根据局部样本猜字段语义、忽略 CRS、或在缺字段时继续 silent fix。

## 2. Step1 SWSD Arm 构建

Arm 表达一个语义路口的道路方向业务单元。T09 按语义路口收集 member nodes 的 incident roads，并区分：

- 两端都在当前语义路口内的 internal road；
- 从外部进入语义路口的 approach road；
- 从语义路口驶向外部的 exit road；
- 双向 road 同时具备进入和退出角色；
- 与提前左转、提前右转、辅路提右等相关的 special carrier road。

Arm 构建应尽量保留特殊道路和未进入 Segment 的 road，不得因为它们不在主干上就静默丢弃。无法明确解释的 road 应进入 risk 或 audit 字段，而不是从业务视图中消失。

正确结果是：`T09SwsdArm` 能说明每个 Arm 的 member nodes、approach / exit roads、segment_ids、角度、终端 node 和风险。错误结果是：只保留主路，导致 restriction 或 arrow 证据无法追溯到真实承载道路。

## 3. Step1 Movement 候选构建

Movement 表达同一语义路口内 `from_arm -> to_arm` 的候选通行方向。T09 对 Arm 两两组合生成 Movement，同时建立 carrier universe：从 `from_arm.approach_road_ids` 到 `to_arm.exit_road_ids` 的候选 road-pair 集合。

业务判定必须先在 road-pair 粒度成立，再汇总到 Movement 粒度。若只有部分 road-pair 被 restriction 命中，Movement 只能是 `partially_prohibited` 或进入更细审计，不能直接升级为 `fully_prohibited`。

正确结果是：Movement 的 `candidate_road_pair_count`、carrier 状态和不适用原因可解释。错误结果是：把 Arm 级关系当作单一 road-pair，或把局部证据扩张到整个 Movement。

## 4. Step2 restriction 证据匹配

restriction 是 T09 当前唯一能改变 Movement 禁行结果的显式禁止证据。restriction 若表达 `inLinkID -> outLinkID`，且该 road-pair 命中 `from_arm` 的 approach road 与 `to_arm` 的 exit road，则生成 restriction evidence。

restriction 证据候选先按 `(in_link_id, out_link_id)` 精确索引匹配 Movement 的 carrier road-pair，再用 restriction 几何与候选 road 几何的空间索引补充邻近候选。候选身份固定为 `(restriction_id, in_link_id, out_link_id)`；同一个 `restriction_id / CondID` 覆盖多组 link-pair 时，每一组都必须作为独立证据参与 Movement 覆盖判断。该候选过滤只减少扫描范围，不改变 raw geometry match 的审计语义。

汇总规则：

- carrier universe 全部 road-pair 都被 restriction 覆盖，Movement 才能是 `fully_prohibited`。
- 仅部分 road-pair 命中 restriction，Movement 是 `partially_prohibited`。
- 没有 restriction 命中，不输出禁止，只输出 `no_prohibition_evidence` 或 `unknown`。

正确结果是：每条禁止规则能回溯到 restriction feature、road-pair、Movement 和 confidence。错误结果是：因为没有通行证据就反推出禁行。

## 5. Step2 arrow 与完整排除证据

arrow 表达地面车道箭头。T09 必须保留原始 code、规范化 token、车道顺序、车道数量、方向匹配和解析状态。字母箭头大小写不敏感；数字 `0` 与字母 `o` 必须严格区分。

完整 arrow 排除只表示“现场箭头没有支持该 Movement”。它可以作为现场证据、解释证据或冲突证据，但在没有 restriction 时不能单独生成禁止规则。

arrow 证据候选可按 road id 缓存并结合空间索引补充几何邻近候选；缓存和索引只服务性能，不得把未命中的 road id 解释为无现场证据。

正确结果是：`complete_arrow_exclusion` 的 `supports_prohibition=false`，且 Movement 仍保持无禁止证据，除非已有 restriction。错误结果是：把完整箭头排除直接写成 prohibited。

## 6. Step2 special carrier / displacement 证据

提前左转、辅路提右、非辅路提前右转等属于现场结构证据。它们说明 Movement 的承载可能不经过中心路口，或通行方向发生位移，但它们不默认等于整个 Arm-Movement 禁止。

T09 应输出：

- `advance_left_carrier_exists`
- `auxiliary_right_turn_carrier_exists`
- `pre_junction_non_aux_advance_right_relation`
- `special_carrier_displacement`

正确结果是：special carrier 进入 evidence 和 risk flags，辅助人工理解 restriction 或 arrow 冲突。错误结果是：无 restriction 时仅凭 special carrier 输出禁行。

## 7. Step2 restored field rules 生成

T09 将 Movement 证据汇总为 `T09RestoredFieldRule`。只有显式 restriction 支撑的 `fully_prohibited` 才能成为稳定禁止规则。冲突证据不改变禁行结论，但必须进入风险和 conflicting evidence。

无证据、证据不足、拓扑不可达、方向不适用，应分别表达为无禁止证据、未知、不适用或人工复核，不得写成 allowed 或 prohibited。

正确结果是：每条 restored rule 都引用 supporting evidence；无法追溯证据的规则不得输出。错误结果是：输出无法定位输入证据的规则。

## 8. Step3 SWSD Arm 到 F-RCSD Arm 映射

Step3 使用 T06 `t06_step3_swsd_frcsd_segment_relation` 映射 SWSD Arm 的 `segment_ids` 到 F-RCSD Road / Node。

- `relation_status=replaced` 时，使用 `source=1` 的 F-RCSD Road 表达 RCSD 承载。
- `relation_status=retained_swsd` 时，使用 `source=2` 的 F-RCSD Road 表达保留 SWSD 承载。
- `relation_status=replaced+retained_swsd` 时，`source=1` 的 F-RCSD Road 表达 RCSD 主通道承载，`source=2` 的 F-RCSD Road 仅表达 detached junc 局部 SWSD carrier。
- 对 `relation_status=retained_swsd` 或 `relation_status=replaced+retained_swsd` 的 `source=2` relation road，Step3 必须继续受 T09 Arm 的 `approach_road_ids` / `exit_road_ids` 约束：只有属于当前 Arm seed 的 road 才能作为该 Arm 的 approach / exit carrier。T06 Segment relation 可能包含同一 Segment 内多个 Arm 的 SWSD Road，不能仅凭共享 junction alias 将其他 Arm 的 road 混入当前 Movement。
- 对于 T09 Arm 中未进入 T06 Segment relation 的 seed road，若该 road 仍以 `source=2` 存在于 T06 F-RCSD Road 输出，且按 SWSD junction alias 与 road direction 可解释为 approach / exit，可作为 `retained_swsd_seed_fallback` carrier；该场景必须进入 risk flags，不得静默当作普通 relation。
- 一个 Arm 涉及多个 Segment 时允许形成混源承载，但必须进入 `source_mix / risk_flags`。
- 缺失 Segment relation、缺失 F-RCSD Road 或端点 Node 时，不生成 restriction，并记录跳过原因。

正确结果是：F-RCSD Arm 承载来自 T06 relation，或来自 T06 F-RCSD 输出中仍保留的 `source=2` SWSD seed road fallback。错误结果是：跳过 T06 输出校验，直接把任意 SWSD Road ID 当作 F-RCSD Road ID。

## 9. Step3 F-RCSD restriction 生成

Step3 只处理 `field_rule_status=fully_prohibited` 且 Movement `prohibition_reason=explicit_restriction` 的规则。对映射后的 from Arm approach F-RCSD roads 与 to Arm exit F-RCSD roads 做笛卡尔积，生成 `LinkID -> outLinkID`。

去重键是：

```text
LinkID + outLinkID + junction_id + movement_type
```

几何可由进入 road 和退出 road 在路口附近连接生成；几何无法构造时不得 silent fix，应记录跳过或风险。

正确结果是：`frcsd_restriction.*` 中每条记录都能回溯到 SWSD Movement、T09 evidence、T09 restored rule 和 T06 relation。错误结果是：对 `no_prohibition_evidence / unknown / not_a_traffic_rule` 也生成 restriction。

## 10. 输出与审计策略

T09 输出必须同时满足人工可读和机器可审计：

- GPKG 支持 GIS 目视检查；
- CSV 支持快速筛选和统计；
- JSON 支持结构化回放和 T10 Case 证据包组织；
- summary 记录输入、输出、跳过原因、CRS、性能和 QA 信息。

所有失败、跳过、冲突和风险都应进入 summary 或 evidence，而不是只出现在日志中。
