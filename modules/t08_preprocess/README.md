# T08 预处理

本文件是 T08 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：提供 SWSD / RCSD 正式预处理、质检、修复和显性化工具。
- 上游：原始 SWSD / RCSD / patch / restriction / Laneinfo 数据。
- 下游：T01、T03、T04、T05、T06、T09；内网全量总控可把 T08 作为独立前置阶段串入。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、Tool1-9 关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：Tool1-9 输入输出、脚本入口、参数和验收契约。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标和非目标。 |
| `architecture/02-data-and-domain-model.md` | SWSD/RCSD 输入、工具输出、字段显性化和下游关系。 |
| `architecture/03-solution-strategy.md` | Tool1-9 的需求具体实现策略。 |
| `architecture/04-evidence-and-audit.md` | 工具 summary、audit、QC、restriction / arrow 显性化和 RCSD 清理证据。 |
| `architecture/05-quality-requirements.md` | 质量要求、GIS / 拓扑 / 性能检查和回归要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、技术债和治理缺口。 |

## 3. 当前入口位置

T08 通过已登记 `scripts/t08_tool*.py` 执行 Tool1-Tool9。每个工具的参数、输入输出和约束以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`

## 5. 命名提示

T08 成果输出文件名默认在扩展名前以 `_toolX` 结尾，`X` 为工具编号。Tool1 转换成果是命名特例，使用输入文件同 stem、不同格式后缀；Tool1 summary 仍按 `_tool1` 命名。
