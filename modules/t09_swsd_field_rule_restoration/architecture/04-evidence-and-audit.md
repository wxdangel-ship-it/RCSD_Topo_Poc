# 04 证据与审计

## 1. 审计目标

T09 必须让每条 SWSD 决策、F-RCSD stable restriction、candidate、失败和跳过都能回溯到 junction、Arm、Movement、Road / Road-Pair、原始证据、策略、条件、T06 relation 与最终 carrier。无证据、证据不足、拓扑不可达、方向不适用和未验证不能被写成稳定禁止。

## 2. Step1/2 正式证据

| 证据 | 审计用途 |
|---|---|
| `t09_swsd_arms.*` | member nodes、Road 角色、special carrier、segment 与风险。 |
| `t09_arm_movements.*` | Movement 是否存在、carrier universe、方向和兼容状态。 |
| `t09_evidence_items.*` | Restriction / Laneinfo / special carrier 的原始 ID、匹配、condition、优先级和推理等级。 |
| `t09_restored_field_rules.*` | 策略、DecisionStatus、RuleScope、验证状态、supporting / conflicting evidence 与 override chain。 |
| `t09_swsd_field_rule_restoration_summary.json` | 输入、策略、计数、CRS、冲突、QA 和性能。 |

## 3. 最小 provenance

每条结论至少可定位：

- `junction_id / from_arm_id / to_arm_id / movement_id / movement_type`
- `from_road_ids / to_road_ids` 或明确 Road-Pair
- 原始 Restriction / Laneinfo / special carrier evidence ID
- raw field audit、几何 / ID 匹配方式和 confidence
- `strategy_version / evidence_priority / inference_level`
- `decision_status / decision_scope / verification_status`
- `condition_type / condition_payload / condition_identity / condition_semantics_status`
- `scope_promotion_status / scope_promotion_reason / scope_promotion_audit`
- `supporting_evidence_ids / conflicting_evidence_ids / override_chain`
- `risk_flags`

## 4. Restriction 条件与提升审计

Restriction 必须逐 Road-Pair 保存，不因相同 ID 折叠。作用域提升必须按每个 `condition_identity` 独立审计，至少记录：候选 carrier universe、该 condition 的覆盖数、正式 T01 membership 或显式 parallel-branch 等价证明、Road 自带 segmentid 与 T01 的一致性、几何 / 精确 Link 匹配证明、未解释 carrier、geometry fan-out、冲突证据和最终 promotion status。

Road 自带 segmentid 与正式 T01 membership 冲突时不得以 Road 字段覆盖 T01 事实；显式 v2 必须记录 `segment_membership_conflict`，默认 / 显式 v1 为保持既有 `risk_flags` 兼容只加性输出 T01 membership 审计字段。只有独立的显式 parallel-branch 审计才能提供替代等价证明，且审计必须列出同角色、同 terminal、同方向 bundle 的全部 Road，不得按 Road ID 任意选 core。geometry fan-out 按 raw restriction identity 跨本次 run 的全部 Movement 汇总；精确 Link ID evidence 保持 verified，额外 geometry fallback 必须标记 ambiguity 并转人工复核，未经额外唯一性证明不得提升或发布为 verified stable。

raw condition payload 不得因输出格式被丢弃。字段语义未知时保留 JSON payload 和 unknown；不同 payload 不得在统计层被误合并为一条全时禁止。

## 5. Laneinfo 与 special carrier 审计

Laneinfo 审计保留每个进入 Road 的全部 raw lane code、lane 顺序 / 数量、sequence complete、direction matched、解析状态、方向并集、目标 Movement 存在性和 Road 匹配方式。`9`、`o`、未知码和不完整序列必须能从证据解释 `unknown`。

special carrier 审计保留 Road `formway`、bit 命中、Arm Road 角色、核心路口关系、carrier 分类、默认方向、弱推导、实际 `source_carrier_road_ids` 和无法分类原因。`kind` 可作为 raw 字段显示，但不能成为强结论来源。

## 6. Override 审计

每次覆盖都写结构化 `override_chain`：

- 获胜证据 ID 与 source；
- 被覆盖证据 ID 与 source；
- `restriction_over_laneinfo`、`restriction_over_special_carrier` 或 `laneinfo_over_special_carrier` 等原因；
- 最终 DecisionStatus；
- 风险标记。

覆盖只改变最终决策，不删除低优先级 evidence。相同优先级相互矛盾时进入 conflict / manual review，不伪造确定结果。

## 7. Step3 发布审计

| 证据 | 审计用途 |
|---|---|
| `frcsd_restriction.gpkg/csv/json` | 已证明 Restriction scope 的稳定 F-RCSD 发布。 |
| `frcsd_restriction_candidates.gpkg/csv/json` | 缺 RCSD Laneinfo、carrier 不充分或待复核候选。 |
| `t09_step3_frcsd_restriction_summary.json` | strategy、stable / candidate、carrier、condition、跳过、风险和性能。 |

每条 Step3 结果还必须回溯 T06 `relation_status`、Segment ID、F-RCSD Road source、junction alias、具体 carrier 和 fallback 路径。stable 与 candidate 按 `source_rule_id` 原子互斥；Road 级 candidate 不能通过 Arm 笛卡尔积扩张。source/status 白名单、Road 双端 Node、严格整数方向和 relation-gap fallback blocker 都必须进入结构化审计。

## 8. Text Bundle 证据

已登记 Step3 text bundle 脚本只用于内外网轻量传递 SWSD、T08 Tool7/8、T06 F-RCSD 与 Segment relation 证据。它不执行规则，不替代 callable；解包后仍按本模块契约运行。

## 9. Summary 与失败证据

summary 至少汇总：策略版本、输入 / 输出、DecisionStatus、RuleScope、EvidencePriority、VerificationStatus、condition identity、scope promotion、conflict、override、stable、candidate、skip、risk、CRS、运行环境和阶段耗时。

缺 Relation、Road、Node、方向、几何或 CRS，以及 retained SWSD seed fallback、混源 carrier、未知条件、Laneinfo 不完整和 special carrier 无法分类，都必须进入结构化风险 / 跳过字段，不得只记日志。
