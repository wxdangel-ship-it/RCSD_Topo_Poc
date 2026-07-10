# Tasks：T09 多证据通行规则恢复能力升级

## Specify

- [x] 固化 v1 默认兼容和 v2 显式选择。
- [x] 固化 `Restriction > Laneinfo > 提前左转 / 提前右转`。
- [x] 固化六类 RuleScope、统一 DecisionStatus、条件 raw 保守语义。
- [x] 固化缺 RCSD Laneinfo 时 stable / candidates 分层。
- [x] 固化产品、架构、研发、测试、QA 五视角。
- [x] 固化 26 类验收场景与六 Case 对比范围。

## Plan

- [x] 确定 SWSD 恢复与 F-RCSD 投影两阶段架构。
- [x] 确定 schema、Restriction、Laneinfo、special carrier、决策器、Step3 的实现边界。
- [x] 确定不修改 T06/T08/T10 实现、对外调用接口、入口或业务输入；仅同步用户授权的 T10 当前基线文档。
- [x] 确定 GIS / 拓扑 / 几何 / 审计 / 性能 Gate。

## Implement：文档与契约

- [x] 更新 T09 `README.md` 和 `SPEC.md`。
- [x] 更新 T09 `INTERFACE_CONTRACT.md`。
- [x] 更新 T09 `architecture/01-06`。

## Implement：Schema 与兼容性

- [x] 增加 `DecisionStatus`、`RuleScope`、`EvidencePriority`、`VerificationStatus`。
- [x] 扩展 evidence / restored rule 的 condition、scope、road、override 与 provenance 字段。
- [x] 两个 callable 增加显式 strategy，默认 `restriction_only_v1`。
- [x] summary 记录策略、输入/CRS/runtime、阶段耗时、风险/跳过和新增统计。
- [x] 同步 GPKG / CSV / JSON schema，保持 v1 兼容字段。

## Implement：Restriction

- [x] 保持基础 Road-Pair 身份不折叠，并让 v2 完整实例包含 `condition_identity`。
- [x] 继承 `CondType` 与 raw condition payload。
- [x] 实现每个 `condition_identity` 独立的安全 scope promotion，直接覆盖“两个完整条件”和“完整 + partial”组合。
- [x] 以正式 T01 Segment membership 或显式 parallel-branch 审计证明多 Road 等价；Road segment 与 T01 冲突时不得充当 membership 证明，只有独立的显式 parallel-branch 审计才能提供替代证明。
- [x] 同一 raw Restriction geometry 一对多匹配时保留 ambiguity 并转人工复核，未经唯一性证明不得进入 verified stable。
- [x] 输出 partial / suspected / manual-review 审计，禁止任一命中提升。

## Implement：Laneinfo

- [x] 按进入 Road 聚合完整车道箭头。
- [x] 实现方向并集、完整性和 code 可解释性 Gate。
- [x] 只对真实存在的 Movement 输出支持或 Road 级排除。
- [x] 实现禁左与调头联动、明确调头箭头例外。
- [x] 保留 lane code、顺序、Road ID、匹配和完整性 provenance。

## Implement：提前左转 / 提前右转

- [x] 使用 `formway & 128/256`，移除 `kind` 后缀强判定。
- [x] 按 Arm 汇总并区分可证明的 carrier / displacement 类型。
- [x] special carrier 默认方向支持和其它方向弱候选。
- [x] Laneinfo / Restriction 覆盖弱推导时写入 override chain。

## Implement：统一决策与 F-RCSD

- [x] 实现确定性优先级决策与完整 override chain。
- [x] stable 输出只接收已证明的 Restriction scope。
- [x] 新增 `frcsd_restriction_candidates.gpkg/csv/json`。
- [x] Road 级投影不做 Arm carrier 笛卡尔积。
- [x] 缺 RCSD Laneinfo 时标记 `unverified_due_to_missing_frcsd_laneinfo`。
- [x] 保持 T06 relation carrier 与 retained SWSD seed fallback 约束，缺 Node/方向解释不得进入 stable。

## Test：26 类场景

- [x] Restriction 场景 1-5，含逐 condition 独立提升、正式 T01 membership 冲突和 geometry fan-out 的直接 Gate。
- [x] Laneinfo 场景 6-11。
- [x] 提左 / 提右场景 12-17。
- [x] 优先级场景 18-20。
- [x] F-RCSD 场景 21-26，含 retained source=2 缺 Node/方向拒绝。
- [x] v1 默认调用与显式 v1 等价。
- [x] 条件 raw payload 序列化 round-trip。
- [x] 全量 T09 现有回归。

## QA：T10 六 Case

- [x] 定位冻结基线六 Case 的相同 T01/T06/T08 handoff。
- [x] 在独立输出根运行默认 v1，不覆盖冻结基线。
- [x] 在独立输出根运行修复后的显式 v2。
- [x] 输出逐 Case及合计 v1 兼容差异。
- [x] 输出逐 Case及合计 v2 DecisionStatus / RuleScope / override / condition / candidate 变化。
- [x] 抽样验证 provenance、T06 relation、F-RCSD carrier。
- [x] 完成 CRS、拓扑、几何语义、审计和性能 Gate。
- [x] 检查除授权的 T10 基线文档外，diff 未触及 T06/T08/T10 实现、接口、入口或业务输入。

## Closeout

- [x] 列出已修改 / 已验证 / 待确认。
- [x] 明确缺 RCSD Laneinfo、未知条件字段和人工复核剩余项。
- [x] 提供所有测试命令、通过 / 失败数和六 Case 输出根。

## Verification（2026-07-10，最终证据）

- T09 全量：`148 passed in 53.60s`；T10 orchestration 回归：`38 passed in 40.52s`。
- 授权只读基线：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full`，T10 六 Case 为 `6/6 passed`。
- 最终独立输出根：`outputs/_work/t09_multi_evidence_v2_20260710_qa/six_case_v1_v2_final3_20260710`；此前探测结果作废。
- v1 复跑合计与冻结基线一致：`8947` Arms / `29145` Movements / `31112` Evidence / `3265` rules / `4357` stable / `0` candidates。
- v2 合计：`8947` Arms / `29145` Movements / `31612` Evidence / `29768` condition-scoped rules / `3778` stable / `1643` candidates / `64` overrides / `1724` condition rules。
- comparison 的 `all_required_gates_pass=true`，14 项必需 Gate 全部通过；source rule 跨 stable/candidate、stable full-key 重复、candidate proposal 重复、unresolved stable carrier 均为 `0`。
- GIS QA 分别验证 CRS、拓扑一致性、几何语义、审计追溯和性能；CSV / JSON / GPKG 存在性、CRS 与行数一致性全部通过。
