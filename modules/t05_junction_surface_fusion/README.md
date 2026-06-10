# T05 Junction Surface Fusion

本文件是 T05 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：融合 T07/T03/T04 路口面成果，生产 SWSD-RCSD 语义路口关系，并执行 RCSD junctionization。
- 上游：T07、T03、T04、final nodes、RCSDRoad、RCSDNode。
- 下游：T06、T09。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求。 |
| `architecture/04-solution-strategy.md` | Phase 1 / Phase 2 详细需求 / 落地策略。 |
| `INTERFACE_CONTRACT.md` | Phase 1 / Phase 2 输入输出、业务规则、入口和验收契约。 |
| `architecture/01-introduction-and-goals.md` | 模块目标和背景。 |
| `architecture/03-context-and-scope.md` | 上下文与范围。 |
| `architecture/10-quality-requirements.md` | 当前质量要求。 |

## 3. 当前入口位置

T05 当前主执行面是模块内 callable runner；内网联合实验、T03 evidence backfill 和 junctionization 输入证据包的详细调用方式以 `INTERFACE_CONTRACT.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/03-context-and-scope.md`
5. `architecture/10-quality-requirements.md`
6. `AGENTS.md`

## 5. 治理提示

T05 仍缺标准 `architecture/02-constraints.md`、`05-building-block-view.md`、`11-risks-and-technical-debt.md` 和 `12-glossary.md`，后续需要补齐。
