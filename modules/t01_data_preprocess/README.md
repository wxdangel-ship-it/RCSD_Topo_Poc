# T01 数据预处理模块

本文件是 T01 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：把 T08 预处理后的 SWSD `nodes / roads` 构建为 SWSD Segment。
- 上游：T08 预处理后的 SWSD `nodes / roads`。
- 下游：T06 Segment 替换前检查与替换执行、T09 SWSD 字段与通行规则恢复。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：官方输入输出、CLI 入口、关键参数类别、continuation 约束、验收口径。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标和边界。 |
| `architecture/02-data-and-domain-model.md` | 业务对象、数据关系和字段语义。 |
| `architecture/03-solution-strategy.md` | 需求具体实现策略：Step1-Step6、单向补段、freeze compare 如何落地。 |
| `architecture/04-evidence-and-audit.md` | 运行证据、审计产物和回归基线。 |
| `architecture/05-quality-requirements.md` | 质量要求、GIS / 拓扑 / 性能检查要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、技术债和治理缺口。 |
| `architecture/accepted-baseline.md` | 已确认 baseline 的补充说明；作为当前业务口径补充，不占用 01-06 主结构编号。 |

## 3. 当前入口位置

T01 官方入口采用 repo-level CLI 子命令，具体命令、参数和辅助脚本边界以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

常用入口类别：

- official end-to-end：`t01-run-skill-v1`
- oneway continuation：`t01-continue-oneway-segment`
- freeze compare：`t01-compare-freeze`
- 分步 / 调试入口：`t01-step1-pair-poc`、`t01-step2-segment-poc`、`t01-s2-refresh-node-road`、`t01-step4-residual-graph`、`t01-step5-staged-residual-graph`、`t01-step6-segment-aggregation-poc`

repo root `scripts/t01_run_full_data.sh` 与 `scripts/t01_run_full_data_skill_v1.sh` 是交付和环境辅助脚本，不替代模块官方 CLI 契约。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`
8. `architecture/accepted-baseline.md`

## 5. 入口治理提示

新增或改变 T01 官方入口前，必须先按 repo root `AGENTS.md` 的入口治理规则获得授权，并同步仓库入口登记。
