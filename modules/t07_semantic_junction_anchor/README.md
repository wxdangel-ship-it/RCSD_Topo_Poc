# T07 Semantic Junction Anchor

本文件是 T07 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：执行已有路口面 1:1 锚定；Step3 是可选兼容补锚能力，可显式消费早期或外部方案产出的 `intersection_match_all` 兼容 relation 文件。
- 上游：T08、DriveZone、RCSDIntersection、RCSDNode；Step3 可选消费外部兼容 relation 文件。
- 下游：T03、T04、T05。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：Step1/2/3 输入输出、业务规则、入口和验收契约。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标和非目标。 |
| `architecture/02-data-and-domain-model.md` | 语义路口、representative node、RCSDIntersection、兼容 relation 文件与 handoff evidence 关系。 |
| `architecture/03-solution-strategy.md` | Step1/2 existing surface anchor 与 Step3 relation backfill 的实现策略。 |
| `architecture/04-evidence-and-audit.md` | nodes 状态、surface handoff、relation evidence、Step3 audit 和 cardinality 审计。 |
| `architecture/05-quality-requirements.md` | 质量要求、GIS / 拓扑 / 性能检查和回归要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、生命周期判断和治理缺口。 |
| `history/` | 历史阶段材料，只用于追溯。 |

## 3. 当前入口位置

T07 提供模块内 callable runner，并通过已登记内网脚本包装 Step1/Step2 和独立 Step3。详细调用方式以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`

## 5. 范围提示

T07 不读取、生成或统计 Segment，也不生成虚拟路口面。它只处理代表 node 的 `has_evd / is_anchor / anchor_reason` 与 T07 relation evidence。
