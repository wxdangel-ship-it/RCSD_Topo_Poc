# T04 分歧 / 合流 / 复杂路口虚拟锚定

本文件是 T04 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：面向分歧、合流、连续分歧 / 合流和复杂路口构建虚拟锚定面与 T05 可消费 relation evidence。
- 上游：T03/T07 downstream 状态、SWSD Road/Node、DriveZone、DivStripZone、RCSDRoad、RCSDNode。
- 下游：T05 surface / relation evidence。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：正式范围、输入输出、状态机、入口和值域。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标和非目标。 |
| `architecture/02-data-and-domain-model.md` | T04 业务对象、数据关系和关键字段语义。 |
| `architecture/03-solution-strategy.md` | Step1-Step7 的需求具体实现策略。 |
| `architecture/04-evidence-and-audit.md` | full-input、case-package、surface、relation 与 nodes 回写审计。 |
| `architecture/05-quality-requirements.md` | 基线、质量门槛、GIS / 拓扑 / 性能要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、技术债和治理缺口。 |
| `history/` | 历史阶段材料，只用于追溯，不作为当前主阅读结构。 |

## 3. 当前入口位置

T04 稳定执行面是模块内 Python runner 和已登记 internal full-input 脚本。case-package、full-input、文本证据包和脚本边界以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`

## 5. 基线提示

Anchor_2 official 39-case baseline 是当前唯一正式冻结基线；历史 23/30 case 只作为子集投影或旧审计材料。
