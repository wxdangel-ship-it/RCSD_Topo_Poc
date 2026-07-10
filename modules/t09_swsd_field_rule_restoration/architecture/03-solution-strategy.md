# 03 Solution Strategy

本文件是 T09 的需求具体实现策略。模块需求见 `../SPEC.md`，稳定接口和值域见 `../INTERFACE_CONTRACT.md`。

## 1. 策略入口与兼容层

两个既有 callable 都接受 `strategy_version`。不传参数时固定为 `restriction_only_v1`；只有显式传入 `multi_evidence_v2` 才启用多证据决策。策略版本必须写入 restored rule 和两个 summary，Step3 不得静默混用不同策略的输入。

v1 保留现有规则：Restriction 是唯一能改变禁行结论的证据，Laneinfo 与 special carrier 仅用于解释、冲突和风险。v2 复用同一 Arm / Movement universe，但增加 Road 级 Laneinfo 决策、Arm 级 special carrier 弱推导、统一覆盖链和 candidate 输出。

## 2. Step1 输入归一

读取 SWSD Node/Road、可选 T01 Segment、Restriction 和 Laneinfo，并统一到 `target_epsg`。输入审计必须记录路径、图层、字段、计数、原始 CRS、变换结果和缺失字段。

Restriction 读取时完整保留 properties，提取 `CondType` 但不猜其值语义。Laneinfo 读取时保留 Road / Link ID、lane code、lane count、序列完整性、方向匹配和 raw properties。缺 CRS、关键字段或不可解释几何必须显式失败、跳过或审计，禁止 silent fix。

## 3. Step1 Arm 与 Movement

Arm 按 SWSD 语义路口 member nodes 聚合 incident Roads，区分 internal、approach、exit、bidirectional、seed、trunk、parallel 和 special carrier。special carrier 候选使用 `formway & 128/256`，不得以 `kind` 后缀替代正式字段。

Movement 是同一 junction 内 `from_arm -> to_arm` 的真实候选方向。每个 Movement 建立从 `from_arm.approach_road_ids` 到 `to_arm.exit_road_ids` 的 Road-Pair universe。只有拓扑和方向上真实存在的 Movement 才能参与 Laneinfo 方向排除；不存在的方向是 `not_applicable`，不是 prohibited。

## 4. Step2 Restriction Road-Pair 与条件

Restriction 候选先按 `(in_link_id, out_link_id)` 精确索引，再用几何候选补充匹配。基础 Road-Pair 匹配身份是 `(restriction_id, in_link_id, out_link_id)`，同一 ID 的多组 pair 独立保留；v2 完整证据实例身份还包含 `condition_identity`。

每条匹配先形成 `road_to_road / prohibited / explicit`。条件处理遵循：

1. 保存 `CondType` 与全部 raw properties。
2. 对 raw payload 做确定性序列化，形成 `condition_identity`。
3. 未有正式定义的字段标记 `condition_semantics_status=unknown`。
4. 不同 condition identity 不合并计算 Arm 全覆盖。
5. Step3 原样继承条件，不能硬编码普通全时禁止。

## 5. Restriction scope 安全提升

Road-Pair Restriction 只有同时满足以下审计条件，才能提升为 `arm_to_arm`：

- 所有证据属于同一 from Arm、to Arm 和 condition identity；
- 覆盖该 Movement 经审计后的全部等价 carrier；
- 并行 Road、等价 Road 切分和方向关系由正式 T01 Segment membership 或显式 parallel-branch 审计证明；显式 parallel 只在 v2 产生，且将同角色、同 terminal、同方向 bundle 全部作为一个等价组，不按 Road ID 指定 core / branch；Road 自带 segmentid 只能交叉审计，不能覆盖 T01 冲突；
- Restriction 几何覆盖核心通行路径或精确 link identity 已充分证明；
- 同一 raw Restriction identity 的 exact / geometry evidence 必须跨本次 restore run 的全部 Movement 汇总；geometry 不得通过一对多邻近匹配拼出完整覆盖，exact 仍保持权威，额外 geometry fallback 必须转人工复核；
- 没有未被解释的其它 carrier；
- Laneinfo / special carrier 的支持或冲突已记录，但不反转 Restriction 优先级。

不满足时分别保持 `road_pair_explicit`、`partial_coverage`、`suspected_arm_to_arm` 或 `manual_review_required`。禁止把“必须全覆盖”机械替换为“任一命中”，也禁止跨条件 payload 拼出全覆盖。

## 6. Step2 Laneinfo Road 级推理

Laneinfo 按进入 Road 聚合全部匹配 arrow，并执行以下 Gate：

1. Road 与 Laneinfo 方向匹配。
2. 车道序列和 lane count 完整。
3. 所有 code 可解释，且没有 `9`、字母 `o` 或未知码。
4. 目标 Movement 在当前路口拓扑中真实存在。

任一 Gate 失败，输出 `unknown` 和完整审计，不生成确定禁止。全部通过后，对有效 lane directions 取并集：包含目标方向则输出 `road_to_arm / supported / derived`；不包含则输出 `road_direction_exclusion / prohibited / derived`。

左转与调头联动：完整方向并集同时缺少 left 与 u-turn 时，左转和调头分别生成 Road 级排除；缺 left 但有明确 u-turn 时，左转排除、调头支持。数字 `0` 与字母 `o` 在解析和审计中严格区分。

v1 仍把这些结论映射为兼容的解释 / 冲突证据，不改变最终禁行；v2 才将其纳入统一决策。

## 7. Step2 special carrier Arm 级推理

先以 `formway` bit 识别提前左 / 右转候选，再在 Arm 内结合 Road 角色和核心路口拓扑分类：

- 提前左转；
- 辅路提前右转；
- 绕开核心路口的提前右转；
- 经过核心路口的路口前提右。

只有拓扑足以解释时才输出具体分类；不足时为 unknown / manual review。special Road 默认对专用方向 `supported / special_carrier / weak_derived`；没有更高优先级证据时，其它方向可成为弱排除候选。主路方向被特殊通道移出核心路口时输出 `core_junction_displacement`，但不能据单 Road 属性把整个 Movement 判为禁止。所有结果都保存实际触发分类的 `source_carrier_road_ids`，避免把目标 Road 当成来源 Road。

若 Laneinfo 明确支持主路或 special Road 的某方向，Laneinfo 覆盖 special 默认推导；Restriction 永远具有最高优先级。

## 8. 统一证据决策

v2 对相同 junction、Movement、Road / Road-Pair 和 condition scope 收集证据，按固定顺序裁定：

```text
restriction > laneinfo > special_carrier
```

决策流程：

1. 先选择最高优先级确定证据。
2. 同优先级证据矛盾时输出 `conflict` 或 `manual_review_required`，不得仅按 confidence 选择。
3. 低优先级证据与获胜结果冲突时，加入 `conflicting_evidence_ids` 和 `override_chain`。
4. `override_chain` 记录获胜 / 被覆盖证据、原因、结果和风险。
5. 无确定证据时保持 `unknown`；缺 allowed evidence 不能反推 prohibited。
6. 同一 Movement 的 condition group 同时出现完整与 partial / manual-review 结果时，Movement 聚合为 `manual_review_required / partially_prohibited`，并保留逐 condition 结果。

Restored rule 同时保留 v1 兼容字段与 v2 的 DecisionStatus、RuleScope、EvidencePriority、InferenceLevel、VerificationStatus、condition、Road / Arm、supporting / conflicting evidence 和风险。

## 9. Step3 Arm carrier 映射

Step3 使用 T06 Segment relation、F-RCSD Road/Node 和 junction alias 映射 Arm：

- `replaced` 只接受 `source=1`，`retained_swsd` 只接受 `source=2`，`replaced+retained_swsd` 接受 `{1,2}`；source 声明缺失、越界或与实际 Road 不一致时拒绝 relation carrier。
- `source=2` Road 仍受当前 Arm approach / exit seed 约束。
- relation / fallback Road 的两个端点必须存在于正式 F-RCSD Node，方向必须是有限整数 `{0,1,2,3}` 且能在中心 junction alias 上解释角色。
- 未进入 relation 的 seed 只有同 ID `source=2` Road 仍存在于 F-RCSD 且全部 Gate 通过时才可 fallback，并记录 `retained_swsd_seed_carrier_fallback`；已声明 relation、Road 或中心 Node 存在缺口时阻断当前 Arm 的全局 fallback。

缺 Relation、Road、Node、方向或 junction alias 时跳过并写入结构化原因，不得直接把任意 SWSD Road ID 当作 F-RCSD carrier。

## 10. Step3 scope-aware 投影

### 10.1 Stable restriction

`frcsd_restriction.*` 只接收：

- 已安全提升为 `arm_to_arm` 的 Restriction；可对经审计的 Arm carrier 组合发布。
- 仍为 `road_to_road`、但 from/to 具体 Road 都能精确映射到 F-RCSD carrier 的 Restriction；只发布这些具体 carrier。

不同 condition identity 分别输出。v1 保持既有兼容路径；v2 不允许兼容去重键折叠不同 condition。

### 10.2 Candidate

Laneinfo / special carrier 的 `road_to_arm`、`road_direction_exclusion`、`special_carrier` 和 `core_junction_displacement` 必须按具体 Road carrier 尝试映射，不能对整个 Arm 做笛卡尔积。当前缺 RCSD Laneinfo，映射结果写入 `frcsd_restriction_candidates.*` 并标记 `unverified_due_to_missing_frcsd_laneinfo`；不能精确映射或需人工确认的 Restriction scope 也可进入 candidate / review 审计。

同一 `source_rule_id` 的全部 Road-Pair proposal 必须先完成整条规则预检并原子分层；同一规则不得同时进入 stable 与 candidate。

## 11. 输出与审计

GPKG 用于 GIS 目视检查，CSV 用于筛选统计，JSON 用于结构化回放。两个 summary 必须记录 strategy、输入、CRS、DecisionStatus / RuleScope / priority / verification 计数、Restriction scope promotion、condition、conflict、override、stable、candidate、skip、risk、阶段耗时与 QA。

所有失败、跳过、冲突、未知条件和未验证状态必须进入输出或 summary，不能只出现在日志。

## 12. 六 Case 对比策略

权威冻结根为：

```text
/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full
```

该基线 T10 六 Case 为 `6/6 passed`；T09 v1 合计 `8947` Arms、`29145` Movements、`31112` Evidence、`3265` rules、`4357` stable。

对 `1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176` 复用相同 T01/T06/T08 handoff，在两个新输出根分别运行默认 v1 与显式 v2。v1 比较兼容字段、规则身份 / 状态与 stable restriction；v2 按 Case 和合计报告状态、scope、override、condition、candidate / unverified、跳过和耗时。冻结基线只读，不得覆盖。
