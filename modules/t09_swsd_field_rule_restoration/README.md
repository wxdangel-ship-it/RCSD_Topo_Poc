# T09 SWSD Field Rule Restoration

本文件是 T09 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：基于 SWSD restriction / Laneinfo 和 T06 F-RCSD 承载关系恢复路口通行规则。
- 上游：T08、T01、T06。
- 下游：T10、人工 Case 分析和后续通行能力建模。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求。 |
| `architecture/04-solution-strategy.md` | Step1-Step3 详细需求 / 落地策略。 |
| `INTERFACE_CONTRACT.md` | callable 输入输出、业务规则、入口和验收契约。 |
| `architecture/05-building-block-view.md` | 实现构件职责映射。 |
| `architecture/10-quality-requirements.md` | 质量、审计和性能要求。 |
| `architecture/11-risks-and-technical-debt.md` | 当前风险与技术债。 |
| `architecture/12-glossary.md` | 模块术语。 |

## 3. 当前入口位置

T09 当前以模块内 callable 为主，不提供 repo 官方 CLI 主 runner。Step3 输入证据包脚本只用于证据提炼，不替代 T09 主业务 callable。详细入口以 `INTERFACE_CONTRACT.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/05-building-block-view.md`
5. `architecture/10-quality-requirements.md`
6. `architecture/11-risks-and-technical-debt.md`
7. `architecture/12-glossary.md`
8. `AGENTS.md`

## 5. 缺口提示

当前缺少 RCSD Laneinfo 与轨迹通行证据，F-RCSD 通行能力恢复仍需后续迭代。
