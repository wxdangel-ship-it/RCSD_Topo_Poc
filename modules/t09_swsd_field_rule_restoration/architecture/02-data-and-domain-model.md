# 02 数据与领域模型

## 1. 数据流

T09 消费 T08 Tool7 restriction、T08 Tool8 Laneinfo arrow、SWSD Node/Road、T01 Segment，以及 T06 F-RCSD Road/Node 和 SWSD-FRCSD Segment relation。Step1/2 输出 SWSD 规则恢复结果；Step3 输出稳定 F-RCSD restriction 与未验证 candidate，供 T10 和人工审计消费。

## 2. 核心对象

| 对象 | 业务含义 |
|---|---|
| SWSD Arm | 一个语义路口内按方向与承载角色聚合的道路单元。 |
| Movement | 同一语义路口 `from_arm -> to_arm` 的实际候选通行方向。 |
| Road-Pair carrier | Movement 的 `in_link_id -> out_link_id` 最细显式 restriction 粒度。 |
| Evidence | Restriction、Laneinfo 或 special carrier 的原始 / 派生证据及 provenance。 |
| Decision | 对某个 scope 的 `prohibited / supported / unknown / ...` 结果。 |
| Restored field rule | SWSD 层带策略、scope、condition、override 和验证状态的规则。 |
| F-RCSD stable restriction | 已由 Restriction 证明并能安全映射到 F-RCSD 的正式结果。 |
| F-RCSD candidate | 因缺 RCSD Laneinfo、carrier 证明不足或需复核而未进入 stable 的结果。 |

## 3. 规则作用域

`RuleScope` 回答“结论对哪个承载范围成立”：

| 值 | 语义 |
|---|---|
| `arm_to_arm` | 整个 from Arm 到 to Arm 的规则，必须由安全提升证明。 |
| `road_to_road` | 特定进入 Road 到特定退出 Road。 |
| `road_to_arm` | 特定进入 Road 到某个退出 Arm / Movement。 |
| `road_direction_exclusion` | Laneinfo 对进入 Road 某方向的排除。 |
| `special_carrier` | 提前左 / 右转 Road 自身的默认专用方向规则。 |
| `core_junction_displacement` | 方向承载被特殊通道移出核心路口。 |

Road 级 scope 不因 Movement 属于某个 Arm 就自动提升为 `arm_to_arm`。

## 4. 决策、优先级与推理等级

`DecisionStatus` 表达 `prohibited / supported / unknown / not_applicable / conflict / manual_review_required / unverified`。现有 `ProhibitionStatus` 作为 v1 兼容视图保留。

`EvidencePriority` 按高到低固定为：

```text
restriction > laneinfo > special_carrier
```

`InferenceLevel` 表达证据如何得到：Restriction 为 `explicit`；完整 Laneinfo 方向并集为 `derived`；special carrier 默认方向或位移为 `weak_derived`；无法解释与冲突分别为 `unknown / conflict`。高优先级与推理等级是不同维度，不能用 confidence 反转业务优先级。

## 5. 验证状态

`VerificationStatus` 区分 SWSD 恢复与 F-RCSD 发布：

- `verified_swsd`：结论已在 SWSD 证据和拓扑上成立。
- `verified_frcsd`：scope 已安全映射到 F-RCSD carrier。
- `unverified_due_to_missing_frcsd_laneinfo`：SWSD Road 级派生结论存在，但缺 RCSD Laneinfo 验证。
- `not_required`：当前对象无需 F-RCSD 验证。
- `manual_review_required`：证据或 carrier scope 不能自动裁定。

## 6. Restriction 条件模型

Restriction evidence 必须保留：

- 基础 Road-Pair 匹配身份 `(restriction_id, in_link_id, out_link_id)`；
- `condition_type`，对应可获得的 `CondType`；
- `condition_payload`，包含可追溯 raw properties；
- `condition_semantics_status`；
- 可稳定比较的 `condition_identity`。

本轮没有正式定义的条件字段只能以 raw payload 保存，并标记 `condition_semantics_status=unknown`。`multi_evidence_v2` 的完整证据实例身份在基础 Road-Pair 身份上增加 `condition_identity`，用于防止不同条件证据被合并；它不代表已理解时间窗、车辆或日期语义。

## 7. Laneinfo 模型

Laneinfo 按进入 Road 聚合而不是按单 arrow feature 决策。聚合审计至少包含 Road ID、原始 lane code、顺序、lane count、sequence complete、direction matched、解析状态、匹配方式和方向并集。

只有全部必要输入完整有效，且目标 Movement 真实存在时，方向并集才能形成 `supported` 或 `road_direction_exclusion`。`9` 是未调查，字母 `o` 是空，数字 `0` 与 `o` 严格区分；未知 / 空 / 未调查不能变成强禁止。

## 8. Special carrier 模型

special carrier 候选来自 SWSD Road `formway`：bit `128` 为提前右转，bit `256` 为提前左转。候选需在 Arm 中结合 trunk / parallel / approach / exit 角色和是否穿过核心路口分析，输出 special carrier 自身方向支持、其它方向弱候选或核心路口位移。显式 parallel 是同角色、同 terminal、同方向 Road 的完整等价组，不按 Road ID 区分 core / branch；每条 special 决策保留实际触发分类的 `source_carrier_road_ids`。`kind` 仅保留 raw audit，不进入强判定。

## 9. 覆盖链

`override_chain` 是有序结构，记录：获胜证据 ID / source、被覆盖证据 ID / source、覆盖原因、最终决策与风险。Restriction 覆盖 Laneinfo / special carrier，Laneinfo 覆盖 special carrier；无冲突时链可为空。最终结果不能丢弃低优先级原始证据。

## 10. T06 carrier 模型

- `replaced` 只接受 `source=1` RCSD Road。
- `retained_swsd` 只接受受当前 Arm seed 约束的 `source=2` SWSD Road。
- `replaced+retained_swsd` 可接受 `{source=1, source=2}` 混源 carrier，但 `source=2` 只能属于当前 Arm approach / exit seed。
- relation / fallback Road 的两个端点都必须存在于 F-RCSD Node，方向必须是 `{0,1,2,3}` 中的有限整数并能在中心 alias 解释角色。
- 未进入 relation 的 SWSD seed 只有同 ID Road 仍以 `source=2` 存在于 F-RCSD 且全部 Gate 通过时才可 fallback；任一已声明 relation、Road 或中心 Node 缺口会阻断该 Arm fallback，并记录风险。

F-RCSD `source` 只说明 carrier 来源，不能反推交通限制语义。

## 11. 发布分层

stable 输出只接收已证明 `arm_to_arm` 的 Restriction，或能精确映射具体 from/to carrier 的 Restriction `road_to_road`。Laneinfo / special carrier 派生 Road 级规则在缺 RCSD Laneinfo 时进入 candidates。candidate 不是稳定 restriction，也不能被 T10 或下游按 stable 口径消费。
