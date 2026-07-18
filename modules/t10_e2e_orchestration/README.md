# T10 端到端业务流程编排

本文件是 T10 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：组织端到端业务流程、Case / Segment 级证据包、Case replay、feedback、visual check 和 innernet full pipeline manifest。
- 项目级主业务链：`T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
- T10 v1 Case runner 范围：`T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T11 -> T09`；T11 只发布人工 relation 候选审计，不回写 T09 输入。
- F-RCSD 质量检查专用链：`T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T11 -> T12 -> T09`；固定跳过 T08、启用 T12，T09 仍消费 T06 输出。
- T07 Step3：可选兼容 relation 补锚，不是 Case runner 默认阶段；innernet full pipeline 仅在显式配置兼容 relation 输入时运行。
- T08：独立前置预处理、质检与修复模块，不由 T10 v1 callable 或 Case runner 调用；innernet full pipeline 总控可把 T08 作为独立前置阶段串入。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：workflow、Case package、Case runner、feedback、full pipeline、resume/finalize 契约。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标和非目标。 |
| `architecture/02-data-and-domain-model.md` | Case、package、handoff、stage、feedback、visual check 和 full pipeline 对象关系。 |
| `architecture/03-solution-strategy.md` | 端到端编排、Case replay、T06 funnel、feedback 和 full pipeline 实现策略。 |
| `architecture/04-evidence-and-audit.md` | manifest、summary、logs、T06 funnel、visual check、feedback 和 text bundle 审计。 |
| `architecture/05-quality-requirements.md` | 质量要求、GIS / 拓扑 / 性能检查和回归要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、技术债和治理缺口。 |
| `architecture/statistical-baseline.md` | 补充材料：2026-07-10 / `96b0ea5` 当前全量基线，覆盖 T10 六 Case、T10-Error 26 Case、T10-Error-2 20 Case（合计 `52/52 passed`）；旧 `ce1cc72` 细分指标仅作历史快照。 |
| `history/` | 历史阶段材料，只用于追溯。 |

## 3. 当前入口位置

当前正式 root 脚本入口：

```bash
bash scripts/t10_pack_innernet_cases.sh 991176 74155468
bash scripts/t10_pack_innernet_segments.sh 1534342_62397379
bash scripts/t10_run_e2e_cases.sh --package-dir outputs/_work/t10_case_evidence/<package_id>
bash scripts/t10_run_innernet_full_pipeline.sh
bash scripts/t10_run_frcsd_quality_pipeline.sh
```

模块 callable 入口和参数以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`
8. 如需对照当前 T10 六 Case 或三套 package 的 52 Case 冻结基线，再读 `architecture/statistical-baseline.md`

## 5. 边界提示

T10 只编排、记录和组织证据，不改写 T01-T09 / T11 / T12 算法事实。失败阶段的部分输出不得提升为正式 handoff；feedback 不得绕过 T03/T04/T05/T06 的正式审计。
