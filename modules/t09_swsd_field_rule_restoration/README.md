# T09 SWSD Field Rule Restoration

本文件是 T09 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：基于 SWSD restriction / Laneinfo 和 T06 F-RCSD 承载关系恢复路口通行规则。
- 上游：T08 Tool7 / Tool8、T01、T06。
- 下游：T10、人工 Case 分析和后续通行能力建模。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：callable 输入输出、业务规则、入口和验收契约。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标和非目标。 |
| `architecture/02-data-and-domain-model.md` | Arm、Movement、Evidence、RestoredRule、F-RCSD restriction 和 retained carrier 关系。 |
| `architecture/03-solution-strategy.md` | Step1-Step3 的需求具体实现策略。 |
| `architecture/04-evidence-and-audit.md` | restriction / arrow / special carrier / Step3 投影和文本证据包审计。 |
| `architecture/05-quality-requirements.md` | 质量要求、GIS / 拓扑 / 性能检查和回归要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、技术债和后续证据缺口。 |
| `history/` | 历史阶段材料，只用于追溯。 |

## 3. 当前入口位置

T09 当前以模块内 callable 为主，不提供 repo 官方 CLI 主 runner。Step3 输入证据包脚本只用于证据提炼，不替代 T09 主业务 callable。详细入口以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`

## 5. 缺口提示

当前缺少 RCSD Laneinfo 与轨迹通行证据，F-RCSD 通行能力恢复仍需后续迭代。
