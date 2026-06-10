# T04 分歧 / 合流 / 复杂路口虚拟锚定

本文件是 T04 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：面向分歧、合流、连续分歧 / 合流和复杂路口执行 Step1-7 虚拟锚定。
- 上游：T03/T07 downstream 状态、SWSD Road/Node、DriveZone、DivStripZone、RCSDRoad、RCSDNode。
- 下游：T05 surface / relation evidence。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求。 |
| `architecture/04-solution-strategy.md` | Step1-7 详细需求 / 落地策略。 |
| `INTERFACE_CONTRACT.md` | 正式范围、输入输出、状态机、入口和验收契约。 |
| `architecture/05-building-block-view.md` | 实现构件职责映射。 |
| `architecture/10-quality-requirements.md` | 质量、baseline、审计和性能要求。 |
| `architecture/11-risks-and-technical-debt.md` | 当前风险与技术债。 |
| `architecture/12-glossary.md` | 模块术语。 |

## 3. 当前入口位置

T04 稳定执行面是模块内 Python runner 和已登记 internal full-input 脚本。case-package、full-input、文本证据包和脚本边界以 `INTERFACE_CONTRACT.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/05-building-block-view.md`
5. `architecture/10-quality-requirements.md`
6. `architecture/11-risks-and-technical-debt.md`
7. `architecture/12-glossary.md`
8. `AGENTS.md`

## 5. 基线提示

Anchor_2 official 39-case baseline 是当前唯一正式冻结基线；历史 23/30 case 只作为子集投影或旧审计材料。
