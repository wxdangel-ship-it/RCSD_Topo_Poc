# T07 Semantic Junction Anchor

本文件是 T07 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：执行已有路口面 1:1 锚定与 T05 relation 补锚。
- 上游：T08、DriveZone、RCSDIntersection、T05。
- 下游：T03、T04、T05。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求。 |
| `architecture/04-solution-strategy.md` | Step1-Step3 详细需求 / 落地策略。 |
| `INTERFACE_CONTRACT.md` | 输入输出、业务规则、入口和验收契约。 |
| `architecture/05-building-block-view.md` | 实现构件职责映射。 |
| `architecture/10-quality-requirements.md` | 质量、审计和性能要求。 |
| `architecture/11-risks-and-technical-debt.md` | 当前风险与技术债。 |
| `architecture/12-glossary.md` | 模块术语。 |

## 3. 当前入口位置

T07 当前提供模块内 callable runner，并通过已登记内网脚本包装 Step1/Step2 和独立 Step3。详细调用方式以 `INTERFACE_CONTRACT.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/05-building-block-view.md`
5. `architecture/10-quality-requirements.md`
6. `architecture/11-risks-and-technical-debt.md`
7. `architecture/12-glossary.md`
8. `AGENTS.md`

## 5. 范围提示

T07 不读取、生成或统计 Segment，也不生成虚拟路口面。
