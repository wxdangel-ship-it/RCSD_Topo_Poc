# T06 Segment Fusion Precheck

本文件是 T06 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：基于 T01 Segment 与 T05 relation 构建 RCSDSegment、判定 replaceable，并输出 F-RCSD Road / Node。
- 上游：T01、T05。
- 下游：T09、T10。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求。 |
| `architecture/04-solution-strategy.md` | Step1-Step3 详细需求 / 落地策略。 |
| `INTERFACE_CONTRACT.md` | 输入输出、入口、参数、文本证据包和验收契约。 |
| `architecture/02-business-rules.md` | 旧结构下的稳定业务规则参考。 |
| `architecture/03-input-output-contract.md` | 旧结构下的输入输出契约参考。 |
| `architecture/04-algorithm-strategy.md` | 旧结构下的算法分层参考。 |

## 3. 当前入口位置

T06 提供模块内 callable runner，并保留已登记内网脚本。Step1/Step2、Step3、文本证据包和输入切片包的详细命令以 `INTERFACE_CONTRACT.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/02-business-rules.md`
5. `architecture/03-input-output-contract.md`
6. `architecture/04-algorithm-strategy.md`
7. `AGENTS.md`

## 5. 治理提示

T06 架构目录仍保留旧命名文档。本轮新增标准 `architecture/04-solution-strategy.md` 后，旧文档先作为兼容参考保留，不在本轮删除或重命名。
