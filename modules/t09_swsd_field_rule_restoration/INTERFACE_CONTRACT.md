# T09 - INTERFACE_CONTRACT

## 定位

本文件是 `t09_swsd_field_rule_restoration` 的稳定接口契约。业务需求见 `SPEC.md`，实现策略见 `architecture/03-solution-strategy.md`，阅读入口见 `README.md`。

## 1. 支持范围与兼容策略

T09 保留两个既有 callable，不新增执行入口：

```python
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    run_t09_swsd_field_rule_restoration,
    run_t09_frcsd_restriction_modeling,
)
```

两者都接受 `strategy_version: str | RestorationStrategy = "restriction_only_v1"`：

| 值 | 契约 |
|---|---|
| `restriction_only_v1` | 默认；保持既有 Restriction-only 决策和 stable 输出口径。 |
| `multi_evidence_v2` | 显式启用统一多证据决策和 stable / candidate 分层。 |

旧调用不传该参数时必须继续运行并采用 v1。策略必须写入 restored rule 与 summary；Step3 请求策略与输入规则策略不一致时不得静默混用，应明确失败或逐条跳过并审计。

## 2. Inputs

### 2.1 Step1 / Step2 callable

`run_t09_swsd_field_rule_restoration` 接受：

| 参数 | 必选 | 语义 |
|---|---|---|
| `swnode_gpkg` | 是 | SWSD Node，至少含 `id / mainnodeid / kind_2 / geometry`。 |
| `swroad_gpkg` | 是 | SWSD Road，至少含 `id / snodeid / enodeid / direction / geometry`；`formway` 用于 special carrier。 |
| `segment_gpkg` | 否 | T01 Segment，用于 Arm 连续性和 Step3 carrier 辅助。 |
| `restriction_gpkg` | 否 | T08 Tool7 restriction 或等价 Road-Pair restriction。 |
| `arrow_gpkg` | 否 | T08 Tool8 Laneinfo arrow 或等价 arrow。 |
| `output_dir` | 是 | 输出根目录。 |
| `run_id` | 否 | 批次 ID，缺省自动生成。 |
| `target_epsg` | 否 | 统一处理 CRS，默认 `3857`。 |
| `strategy_version` | 否 | 默认 `restriction_only_v1`；v2 必须显式传入。 |

layer 参数仍可用于多图层输入，只选择读取图层，不改变业务语义。所有输入只读。

Restriction 输入必须保留 `inLinkID / outLinkID`、可用的 `id / restriction_id / CondID`、`CondType` 与全部 raw properties。Laneinfo 输入必须保留 Road / Link ID、lane code、lane count / 顺序完整性、方向匹配、raw properties 与几何匹配方式。

### 2.2 Step3 callable

`run_t09_frcsd_restriction_modeling` 接受：

| 参数 | 必选 | 语义 |
|---|---|---|
| `arms_path` | 是 | Step1 `t09_swsd_arms.*`。 |
| `movements_path` | 是 | Step1/2 `t09_arm_movements.*`。 |
| `restored_rules_path` | 是 | Step2 `t09_restored_field_rules.*`。 |
| `frcsd_road_path` | 是 | T06 `t06_frcsd_road.*`。 |
| `frcsd_node_path` | 是 | T06 `t06_frcsd_node.*`。 |
| `segment_relation_path` | 是 | T06 `t06_step3_swsd_frcsd_segment_relation.*`。 |
| `output_dir` | 是 | 输出根目录。 |
| `run_id` | 否 | 批次 ID，缺省自动生成。 |
| `target_epsg` | 否 | 统一处理 CRS，默认 `3857`。 |
| `strategy_version` | 否 | 默认 `restriction_only_v1`；应与输入 restored rules 一致。 |

结构化输入支持 GPKG / CSV / JSON，F-RCSD Road 必须有几何。空间 JSON 必须由顶层 CRS 或每个含几何 feature 的等价 CRS 完整声明；CRS 使用解析后的语义等价比较，缺失、非法或部分声明均不得默认成 `target_epsg`。缺关键字段、CRS、Road、Node、Relation 或方向解释时不得 silent fix。

## 3. 正式枚举和值域

### 3.1 `RestorationStrategy`

```text
restriction_only_v1
multi_evidence_v2
```

### 3.2 `DecisionStatus`

```text
prohibited
supported
unknown
not_applicable
conflict
manual_review_required
unverified
```

### 3.3 `RuleScope`

```text
arm_to_arm
road_to_road
road_to_arm
road_direction_exclusion
special_carrier
core_junction_displacement
```

### 3.4 `EvidencePriority`

序列化值按高到低为：

```text
restriction
laneinfo
special_carrier
```

该顺序是业务优先级，不得由置信度分数反转。

### 3.5 `VerificationStatus`

```text
verified_swsd
verified_frcsd
unverified_due_to_missing_frcsd_laneinfo
not_required
manual_review_required
```

`InferenceLevel` 保留 `explicit / derived / weak_derived / unknown / conflict`。现有 `ProhibitionStatus`、`ProhibitionReason` 与 `field_rule_status` 作为 v1 兼容字段保留，不替代 v2 决策枚举。

## 4. Outputs

### 4.1 Step1 / Step2

目录：

```text
<output_dir>/<run_id>/
```

文件：

- `t09_swsd_arms.gpkg/csv/json`
- `t09_arm_movements.gpkg/csv/json`
- `t09_evidence_items.gpkg/csv/json`
- `t09_restored_field_rules.gpkg/csv/json`
- `t09_swsd_field_rule_restoration_summary.json`

每条 `t09_swsd_arms.*` Arm 记录至少包含 `segment_ids`、`t01_segment_ids`、`segment_membership_status` 与 `risk_flags`。`segment_ids` 保留既有 Road 字段派生结果，`t01_segment_ids` 表达正式 T01 membership；`segment_membership_status` 值域为 `consistent / t01_only / road_only / conflict / missing`。`road_only` 不能冒充正式 T01 证明，`conflict` 不得作为 scope promotion 的等价 carrier 依据。为保持兼容，默认 / 显式 v1 只加性输出新的 T01 审计字段，不改变既有 `risk_flags`；显式 v2 的 `conflict` 必须同时带 `segment_membership_conflict` 风险。

每条 v2 restored rule 至少包含或可从相同记录恢复：

- `strategy_version`
- `decision_status / decision_source / decision_scope`
- `evidence_priority / inference_level / verification_status`
- `junction_id / from_arm_id / to_arm_id / movement_id / movement_type`
- `from_road_ids / to_road_ids`
- `supporting_evidence_ids / conflicting_evidence_ids`
- `override_chain`
- `condition_type / condition_payload / condition_identity / condition_semantics_status`
- `scope_promotion_status / scope_promotion_reason / scope_promotion_audit`
- `risk_flags`
- v1 兼容的 `field_rule_status / rule_scope / confidence`

`override_chain` 是结构化列表。每项至少记录获胜证据 ID / source、被覆盖证据 ID / source、覆盖原因、决策结果和风险标记。

`scope_promotion_audit` 至少可审计 `promotion_allowed`、对应 `condition_identity`、Road-Pair carrier universe、正式 T01 membership 或显式 parallel-branch 等价证明、restriction ID / geometry 匹配证明、未解释 carrier 与 geometry fan-out 风险。显式 parallel 等价组只在 v2 产生，并包含同角色、同 terminal、同方向 bundle 的全部 Road；没有独立角色证据时不得按 Road ID 排序指定 core / branch。多个 condition identity 必须分别保留自己的 promotion 结果，不能用聚合成功覆盖其中的 partial / manual-review 组；完整与 partial 条件并存时 Movement 聚合必须保持 `manual_review_required / partially_prohibited`。

### 4.2 Step3 stable 输出

- `frcsd_restriction.gpkg`
- `frcsd_restriction.csv`
- `frcsd_restriction.json`

stable 记录至少包含：

- `restriction_id / CondType / condition_payload / condition_identity / condition_semantics_status`
- `LinkID / inLinkID / outLinkID`
- `junction_id / frcsd_junction_id`
- `from_arm_id / to_arm_id / movement_id / movement_type`
- `strategy_version / decision_status / decision_scope / verification_status`
- `restriction_source / source_rule_status / confidence`
- `scope_promotion_status / scope_promotion_reason / scope_promotion_audit`
- `supporting_evidence_ids / conflicting_evidence_ids / override_chain`
- `from_road_source / to_road_source / arm_relation_status / risk_flags`

v2 `arm_to_arm` stable 发布必须同时满足 `scope_promotion_status=arm_to_arm_confirmed`、`scope_promotion_audit.promotion_allowed=true` 和 SWSD 侧验证通过；任一 Gate 缺失、失败或 geometry fan-out 未消歧时不得进入 verified stable。`road_to_road` stable 不要求 Arm scope promotion，但必须保留上述 audit 字段，并证明具体 from/to Road carrier 可精确映射且 SWSD 侧验证通过。

### 4.3 Step3 candidate 输出

`multi_evidence_v2` 额外输出：

- `frcsd_restriction_candidates.gpkg`
- `frcsd_restriction_candidates.csv`
- `frcsd_restriction_candidates.json`

candidate 使用与 stable 兼容的 provenance 字段，包括 `scope_promotion_status / scope_promotion_reason / scope_promotion_audit`，并额外明确 `candidate_reason`。因正式 T01 membership 冲突、未证明等价 carrier、geometry fan-out 或其它 promotion Gate 失败而未进入 stable 的 Restriction 必须在 candidate / review 审计中保留对应原因。缺 RCSD Laneinfo 的 Laneinfo / special carrier Road 级派生规则必须为 `verification_status=unverified_due_to_missing_frcsd_laneinfo`，不得同时出现在 stable 输出。

### 4.4 Summary

`t09_swsd_field_rule_restoration_summary.json` 与 `t09_step3_frcsd_restriction_summary.json` 必须记录：

- `strategy_version`
- 输入路径、图层、字段、计数、CRS 与运行环境
- DecisionStatus / RuleScope / EvidencePriority / VerificationStatus 计数
- Restriction scope promotion、condition identity、冲突与 override 计数
- stable / candidate、跳过和风险原因计数
- 各阶段耗时和 QA 结论

## 5. Business Rules

### 5.1 Restriction

- 基础 Road-Pair 匹配身份固定为 `(restriction_id, in_link_id, out_link_id)`；v2 完整证据实例身份还包含 `condition_identity`。
- 同一 restriction id 下不同 Road-Pair 必须独立序列化和审计。
- 精确 Road-Pair 命中形成 `road_to_road` explicit restriction。
- `arm_to_arm` 提升只在同一 condition identity 下覆盖全部经审计的等价 carrier，且无未解释 carrier 时成立。
- 多 Road 等价证明必须消费正式 T01 Segment membership 或显式 parallel-branch 审计；Road 自带 segmentid 与 T01 冲突时不得作为提升依据。
- 同一 raw Restriction identity 的几何匹配必须在一次 v2 restore run 内跨 Movement 汇总；出现多个 Road-Pair 时属于 ambiguity，精确 Link ID evidence 保持 verified，额外 geometry fallback 必须转人工复核且不得提升或发布为 verified stable。
- 部分覆盖、疑似 Arm scope 或条件不一致不得提升。
- Restriction 与任何低优先级证据冲突时，Restriction 决策获胜并写入 override chain。

### 5.2 Laneinfo

- 按进入 Road 聚合全部 Laneinfo；只在目标 Movement 存在时评估。
- 必须同时满足方向匹配、lane sequence 完整、所有 code 可解释。
- `9`、字母 `o`、未知码、序列不完整或方向不匹配得到 `unknown`。
- 完整有效方向并集含目标方向则 `supported`，不含则输出 Road 级 `road_direction_exclusion / prohibited`。
- 缺左转与调头箭头时左转、调头均排除；明确调头箭头只让调头 `supported`。
- 在 v1 中 Laneinfo 继续只作解释 / 冲突证据；在 v2 中才改变 Road 级决策。

### 5.3 Special carrier

- 提前右转候选仅用 `formway & 128 != 0`，提前左转候选仅用 `formway & 256 != 0`。
- `kind` 后缀不得作为强规则。
- 必须按 Arm 汇总；单 Road 属性不能直接输出 Arm-to-Arm 禁止，并必须在 provenance 中保留实际触发分类的 `source_carrier_road_ids`。
- special carrier 默认专用方向支持和其它方向排除只属于 `weak_derived`。
- Laneinfo 或 Restriction 存在确定结论时覆盖 special carrier 弱推导。

### 5.4 条件

- `CondType` 与 raw properties 必须端到端保留。
- 未有正式字段定义时 `condition_semantics_status=unknown`，不解析时间窗、日期、车辆类型。
- 不同 raw payload 不得合并为全时 restriction。
- 同一 Movement 同时出现完整与 partial / manual-review condition 时，聚合结果不得写成 fully prohibited；必须保留逐 condition 结果并标记 `condition_scoped_mixed_outcomes`。
- Step3 不得硬编码 `CondType` 覆盖输入条件。

### 5.5 F-RCSD 投影

- stable 接收：已证明 `arm_to_arm` 的 Restriction，或能精确映射具体 from/to carrier 的 Restriction `road_to_road`。
- `road_to_road`、`road_to_arm`、`road_direction_exclusion`、`special_carrier`、`core_junction_displacement` 不得使用整个 Arm 笛卡尔积。
- Laneinfo / special carrier 派生 Road 级规则因缺 RCSD Laneinfo 默认进入 candidates。
- relation/source 白名单固定为：`replaced -> {1}`、`retained_swsd -> {2}`、`replaced+retained_swsd -> {1,2}`；source 声明缺失、越界或与实际 Road 不一致时拒绝该 relation carrier。
- `retained_swsd / replaced+retained_swsd` 的 `source=2` relation Road 只有属于当前 Arm 的 approach / exit seed 时可用。
- relation 与 fallback carrier 的 `snodeid / enodeid` 都必须存在于正式 F-RCSD Node，方向必须是有限整数且属于 `{0,1,2,3}`，并能在中心 junction alias 上解释 approach / exit 角色。
- 未进入 relation 的 seed 只有同 ID `source=2` Road 仍在 F-RCSD 且上述 Gate 全部通过时才可 fallback，并标记 `retained_swsd_seed_carrier_fallback`；任一已声明 Segment relation、Road 或中心 Node 缺失 / 失败时，当前 Arm 的全局 fallback 必须阻断。
- F-RCSD `source` 只用于 carrier 来源审计，不推断交通规则。

## 6. 去重与条件身份

v1 stable 输出保持既有兼容去重 key：

```text
LinkID + outLinkID + junction_id + movement_type
```

v2 不得让该 key 合并不同条件。v2 stable 发布去重 key 为：

```text
LinkID + outLinkID + junction_id + movement_type + condition_identity + decision_scope
```

不同 condition identity 的 stable 记录必须分别保留。candidate 是未发布的来源规则审计记录，其完整行身份在上述 F-RCSD 语义分组字段之外还包含 `source_rule_id` 与 `candidate_reason`；因此不同 SWSD source rule 映射到同一 F-RCSD 语义分组时可以分别保留，但必须能够按六字段语义 key 聚合审计，不得丢失任一来源 provenance。同一 `source_rule_id` 的所有 Road-Pair proposal 必须原子分层：只要任一 proposal 不能进入 stable，该 source rule 不得同时跨 stable / candidate 两层发布。

## 7. EntryPoints

模块 callable 如本契约第 1 节。已登记辅助脚本：

```bash
.venv/bin/python scripts/t09_export_step3_input_text_bundle_innernet.sh --help
```

该脚本只用于 Step3 证据包，不执行或替代 T09 业务决策。

## 8. Acceptance

1. 默认 v1 与显式 v1 等价，现有相关回归通过。
2. 显式 v2 实现 Restriction > Laneinfo > special carrier。
3. Restriction scope、Laneinfo Road 级规则、禁左 / 调头、special carrier 弱推导和 override 可直接测试。
4. stable 与 candidate 输出分层，缺 RCSD Laneinfo 不伪造验证。
5. 条件 payload 端到端 round-trip，不扁平化。
6. 26 类业务场景和 T10 六 Case v1/v2 对比均有可定位证据。
7. CRS、拓扑、几何语义、审计和性能五类 QA 均通过或明确列出未通过原因。
