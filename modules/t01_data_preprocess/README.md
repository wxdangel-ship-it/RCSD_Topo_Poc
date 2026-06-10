# T01 数据预处理模块

本文件是 T01 的模块阅读入口和文档索引。凝练版业务需求见 `SPEC.md`，详细业务落地见 `architecture/04-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：构建 SWSD 双向与单向 Segment。
- 上游：T08 预处理后的 SWSD `nodes / roads`。
- 下游：T06 Segment 替换、T09 通行规则恢复。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 凝练版模块业务需求：目标、范围、上下游、输入输出、关键步骤和对错边界。 |
| `architecture/04-solution-strategy.md` | 详细版需求 / 落地策略：Step1-Step6 与单向补段如何落地。 |
| `INTERFACE_CONTRACT.md` | 稳定输入、输出、入口、参数类别、freeze compare 与验收口径。 |
| `architecture/06-accepted-baseline.md` | 当前 accepted baseline 业务口径。 |
| `architecture/05-building-block-view.md` | 实现构件职责映射。 |
| `architecture/10-quality-requirements.md` | 质量、审计、GIS / 拓扑和性能要求。 |
| `architecture/11-risks-and-technical-debt.md` | 当前风险与技术债。 |

## 3. 当前入口位置

T01 官方入口采用 repo-level CLI 子命令，具体命令、参数和辅助脚本边界以 `INTERFACE_CONTRACT.md` 为准。

常用入口类别：

- official end-to-end：`t01-run-skill-v1`
- oneway continuation：`t01-continue-oneway-segment`
- freeze compare：`t01-compare-freeze`
- 分步 / 调试入口：见 `INTERFACE_CONTRACT.md`

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/04-solution-strategy.md`
3. `INTERFACE_CONTRACT.md`
4. `architecture/06-accepted-baseline.md`
5. `architecture/05-building-block-view.md`
6. `architecture/10-quality-requirements.md`
7. `architecture/11-risks-and-technical-debt.md`
8. `AGENTS.md`

## 5. 入口治理提示

新增或改变 T01 官方入口前，必须先按 repo root `AGENTS.md` 的入口治理规则获得授权，并同步仓库入口登记。
