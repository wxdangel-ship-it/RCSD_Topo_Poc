# T06 Segment Fusion Precheck

本文件是 T06 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：基于 T01 Segment 与 T05 relation 构建 RCSDSegment、发布 replacement plan / problem registry，并执行 F-RCSD Road / Node 替换。
- 上游：T01、T05，Step3 可选消费 T03/T04/T05/T07 surface 与 T04 audit。
- 下游：T09、T10。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：Step1-Step3 输入输出、入口、参数、文本证据包和验收契约。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标、非目标和 T06 在替换链路中的边界。 |
| `architecture/02-data-and-domain-model.md` | SWSD Segment、T05 relation、RCSDSegment、replacement plan、problem registry 与 F-RCSD 对象关系。 |
| `architecture/03-solution-strategy.md` | Step1-Step3 的需求具体实现策略。 |
| `architecture/04-evidence-and-audit.md` | Step1/2/3 证据、replacement plan、problem registry、topology / surface audit 和 T10 handoff。 |
| `architecture/05-quality-requirements.md` | 替换正确性、GIS / 拓扑 / source 边界、性能和回归要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、技术债和端到端修复后的治理缺口。 |
| `history/` | 历史阶段材料，只用于追溯。 |
| `history/030-innernet-baseline-metrics.md` | 内网执行基线指标，用于 PPT 指标摘录和后续 summary 级基线比对。 |

## 3. 当前入口位置

T06 提供模块内 callable runner，并保留已登记内网脚本：

- `scripts/t06_run_innernet_precheck.py`：Step1/Step2 内网包装；内网规模默认跳过 Step2 大体量 JSON feature dump，保留 GPKG/CSV 和 summary。
- `scripts/t06_run_step3_segment_replacement.py`：Step3 替换与可选 surface topology postprocess 包装。

详细调用方式以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`

## 5. 边界提示

T06 不替代 T05 的路口 1:1 relation 主表，也不回写 T01/T05。它只在当前 Segment 内做受限诊断、重试和替换执行；Step3 的正式执行边界是 Step2 发布的 `t06_segment_replacement_plan.*`。
