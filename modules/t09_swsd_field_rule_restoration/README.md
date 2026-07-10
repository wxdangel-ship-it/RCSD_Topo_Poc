# T09 SWSD Field Rule Restoration

本文件是 T09 模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 主职责：在 SWSD 层恢复带明确作用域的通行规则，再通过 T06 F-RCSD 承载关系发布稳定 restriction 或未验证 candidate。
- 上游：T08 Tool7 / Tool8、T01、T06。
- 下游：T10、人工 Case 分析和后续通行能力建模。
- 默认策略：`restriction_only_v1`，保持既有 Restriction-only 口径。
- 可选策略：显式 `multi_evidence_v2`，执行 `Restriction > Laneinfo > 提前左转 / 提前右转`。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求、三类证据、作用域、兼容关系和对错边界。 |
| `INTERFACE_CONTRACT.md` | callable、策略参数、输入输出、枚举和值域、最小审计字段。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标、兼容边界和非目标。 |
| `architecture/02-data-and-domain-model.md` | Arm、Movement、Evidence、Decision、RuleScope、condition 与 F-RCSD 发布分层。 |
| `architecture/03-solution-strategy.md` | SWSD 恢复、统一优先级和作用域感知投影策略。 |
| `architecture/04-evidence-and-audit.md` | provenance、override、stable / candidate 与 summary 审计。 |
| `architecture/05-quality-requirements.md` | 业务、GIS、拓扑、几何、回归和性能要求。 |
| `architecture/06-risks-and-technical-debt.md` | RCSD Laneinfo、条件语义和 carrier 证明等剩余风险。 |
| `history/` | 历史阶段材料，只用于追溯。 |

## 3. 当前入口位置

T09 只通过既有模块 callable 执行业务。`scripts/t09_export_step3_input_text_bundle_innernet.sh` 是已登记证据提炼工具，不是主 runner。入口事实以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`

## 5. 当前能力边界

当前实验输入缺少 RCSD Laneinfo。T09 可以在 SWSD 层恢复 Laneinfo / special carrier Road 级规则，但这些派生规则在 F-RCSD 上只能作为 `unverified_due_to_missing_frcsd_laneinfo` candidate；不得混入稳定 restriction，也不得放大为整个 Arm 禁止。
