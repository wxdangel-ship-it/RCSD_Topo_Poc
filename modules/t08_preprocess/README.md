# T08 预处理

本文件是 T08 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：提供 SWSD / RCSD 正式预处理、质检、修复和显性化工具。
- 上游：原始 SWSD / RCSD / patch / restriction / Laneinfo 数据。
- 下游：T01、T03、T04、T05、T06、T09。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求。 |
| `architecture/04-solution-strategy.md` | Tool1-Tool9 详细需求 / 落地策略。 |
| `INTERFACE_CONTRACT.md` | Tool1-Tool9 输入输出、入口、参数和验收契约。 |
| `architecture/05-building-block-view.md` | 实现构件职责映射。 |
| `architecture/10-quality-requirements.md` | 质量、审计、GIS / 拓扑和性能要求。 |
| `architecture/11-risks-and-technical-debt.md` | 当前风险与技术债。 |
| `architecture/12-glossary.md` | 模块术语。 |

## 3. 当前入口位置

T08 通过已登记 `scripts/t08_tool*.py` 执行 Tool1-Tool9。每个工具的参数、输入输出和约束以 `INTERFACE_CONTRACT.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/05-building-block-view.md`
5. `architecture/10-quality-requirements.md`
6. `architecture/11-risks-and-technical-debt.md`
7. `architecture/12-glossary.md`
8. `AGENTS.md`

## 5. 命名提示

T08 成果输出文件名统一在扩展名前以 `_toolX` 结尾，`X` 为工具编号。
