# T03 交叉 / T 型虚拟路口锚定

本文件是 T03 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：面向 `center_junction` 与 `single_sided_t_mouth` 构建 Step1-Step7 虚拟锚定成果。
- 上游：T07、T08、SWSD Road/Node、DriveZone、RCSDRoad、RCSDNode。
- 下游：T04 downstream nodes、T05 surface / relation evidence。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求。 |
| `architecture/04-solution-strategy.md` | Step1-Step7 详细需求 / 落地策略。 |
| `INTERFACE_CONTRACT.md` | 输入、输出、状态机、入口和验收契约。 |
| `architecture/10-business-steps-vs-implementation-stages.md` | 正式业务步骤与历史实现阶段命名映射。 |
| `architecture/05-building-block-view.md` | 实现构件职责映射。 |
| `architecture/09-quality-requirements.md` | 当前质量要求。 |
| `history/` | 历史阶段 closeout 材料，仅用于追溯。 |

## 3. 当前入口位置

入口命令、脚本、文本证据包与 internal full-input 运行方式以 `INTERFACE_CONTRACT.md` 为准。

入口类别：

- `t03-rcsd-association`
- `t03-step3-legal-space`
- internal full-input 已登记脚本
- T03/T04-ready 单文件文本证据包

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/10-business-steps-vs-implementation-stages.md`
5. `architecture/05-building-block-view.md`
6. `architecture/09-quality-requirements.md`
7. `AGENTS.md`

## 5. 入口治理提示

历史 `Association` 与 `Finalization` 只作为实现阶段和兼容命名出现；正式需求主结构使用 `Step1~Step7`。
