# T03 交叉 / T 型虚拟路口锚定

本文件是 T03 的模块阅读入口和文档索引。模块需求见 `SPEC.md`，架构设计见 `architecture/01~06`，稳定接口契约见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：面向 `center_junction` 与 `single_sided_t_mouth` 构建 Step1-Step7 虚拟锚定成果。
- 上游：T07、T08、SWSD Road/Node、DriveZone、RCSDRoad、RCSDNode。
- 下游：T04 downstream nodes、T05 surface / relation evidence。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求，用业务语言说明 T03 为什么存在、解决什么问题、什么算对。 |
| `architecture/01-introduction-and-goals.md` | 模块架构目标、上下文、当前范围和非目标。 |
| `architecture/02-data-and-domain-model.md` | T03 关键输入对象、业务对象、RCSD 语义分层和数据约束。 |
| `architecture/03-solution-strategy.md` | 架构设计 / 需求具体实现策略，说明 Step1-Step7 需求如何落地。 |
| `architecture/04-evidence-and-audit.md` | formal、review-only、internal full-input 证据与审计分层。 |
| `architecture/05-quality-requirements.md` | 质量要求和验收关注点，适合做业务验收、QA 或端到端 Case 复盘时阅读。 |
| `architecture/06-risks-and-technical-debt.md` | 历史命名、Step3 冻结语义、RCSD 数据质量、full-input 和入口治理风险。 |
| `INTERFACE_CONTRACT.md` | 输入、输出、状态机、入口和最小审计字段契约，主要供实现、运行、联调和 Agent 维护时查阅。 |
| `history/` | 历史阶段 closeout 材料，仅用于追溯历史交付背景。 |

## 3. 当前入口位置

入口命令、脚本、文本证据包与 internal full-input 运行方式以 `INTERFACE_CONTRACT.md` 为准。

入口类别：

- `t03-rcsd-association`
- `t03-step3-legal-space`
- internal full-input 已登记脚本
- T03/T04-ready 单文件文本证据包

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/01-introduction-and-goals.md`
3. `architecture/02-data-and-domain-model.md`
4. `architecture/03-solution-strategy.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`
8. `INTERFACE_CONTRACT.md`（仅在需要查入口、字段、状态和值域时）

## 5. 入口治理提示

历史 `Association` 与 `Finalization` 只作为实现阶段和兼容命名出现；正式需求主结构使用 `Step1~Step7`。
