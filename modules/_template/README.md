# <module_id>

本文件是 `<module_id>` 的模块阅读入口和文档索引。模块需求见 `SPEC.md`，架构设计见 `architecture/01~06`，稳定接口契约见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：`<Active | Support Retained | Retired | Active POC / 成果模块>`。
- 当前主职责：`<用一句话说明模块当前承担的业务职责>`。
- 上游：`<模块或数据>`。
- 下游：`<模块或数据>`。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求，用业务语言说明模块为什么存在、解决什么问题、什么算对。 |
| `architecture/01-introduction-and-goals.md` | 模块架构目标、上下文、当前范围和非目标。 |
| `architecture/02-data-and-domain-model.md` | 关键输入对象、业务对象、领域分层和数据约束。 |
| `architecture/03-solution-strategy.md` | 架构设计 / 需求具体实现策略，说明模块需求如何落地。 |
| `architecture/04-evidence-and-audit.md` | formal、review-only、internal 和 handoff 证据与审计分层。 |
| `architecture/05-quality-requirements.md` | 质量要求和验收关注点。 |
| `architecture/06-risks-and-technical-debt.md` | 历史命名、数据质量、入口治理、性能和跨模块 handoff 风险。 |
| `INTERFACE_CONTRACT.md` | 输入、输出、状态、入口和最小审计字段契约，主要供实现、运行、联调和 Agent 维护时查阅。 |
| `history/` | 历史阶段 closeout 材料，仅用于追溯历史交付背景。 |

## 3. 当前入口位置

入口命令、脚本和 callable 以 `INTERFACE_CONTRACT.md` 为准。

入口类别：

- `<repo CLI 子命令；无则写“无 repo 官方 CLI”>`
- `<root scripts；无则写“无 root script 入口”>`
- `<模块内 callable；说明主要函数或 runner>`

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

若模块没有 repo 官方 CLI、root `scripts/` 或长期 shell wrapper，应明确写“当前只提供模块内 callable”。新增、删除、重命名或改变官方调用方式前，必须先获得任务授权并同步入口登记。
