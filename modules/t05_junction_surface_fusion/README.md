# T05 语义路口关系融合与 RCSD Junctionization

本文件是 T05 的模块阅读入口。模块需求见 `SPEC.md`，稳定接口见 `INTERFACE_CONTRACT.md`，架构设计见 `architecture/01-introduction-and-goals.md` 至 `architecture/06-risks-and-technical-debt.md`。

## 1. 当前状态

- 生命周期：Active。
- 当前主职责：融合 T07/T03/T04 路口面成果，发布 SWSD-RCSD 语义路口关系主表，并执行 copy-on-write RCSD junctionization。
- 上游：T07、T03、T04、final nodes、RCSDRoad、RCSDNode。
- 下游：T06、T09。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块需求：业务目标、范围、上下游、输入输出、关键步骤、对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口：Phase 1 / Phase 2 输入输出、业务规则、入口和验收契约。 |
| `architecture/01-introduction-and-goals.md` | 架构背景、目标和非目标。 |
| `architecture/02-data-and-domain-model.md` | Phase 1 / Phase 2 数据对象、relation 字段和 RCSD copy-on-write 关系。 |
| `architecture/03-solution-strategy.md` | Phase 1 / Phase 2 的需求具体实现策略。 |
| `architecture/04-evidence-and-audit.md` | surface fusion、relation、junctionization、cardinality 与 handoff 审计。 |
| `architecture/05-quality-requirements.md` | 质量要求、GIS / 拓扑 / 性能检查和回归要求。 |
| `architecture/06-risks-and-technical-debt.md` | 当前风险、技术债和治理缺口。 |
| `history/` | 历史阶段材料，只用于追溯。 |

## 3. 当前入口位置

T05 主执行面是模块内 callable runner。`scripts/t05_innernet_experiment.py` 和 `scripts/t05_backfill_t03_relation_evidence_innernet.py` 是已登记内网辅助脚本，不替代 Phase 1 / Phase 2 callable 契约。详细调用方式以 `INTERFACE_CONTRACT.md` 与 `docs/repository-metadata/entrypoint-registry.md` 为准。

## 4. 阅读顺序

1. `SPEC.md`
2. `INTERFACE_CONTRACT.md`
3. `architecture/03-solution-strategy.md`
4. `architecture/02-data-and-domain-model.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`

## 5. 边界提示

T05 是路口 1:1 关系层的统一发布点。Phase 1 只融合 surface；Phase 2 才发布 `intersection_match_all.geojson` 并做 RCSD junctionization。T06 消费 T05 的关系主表，但不应再反推 T07/T03/T04 的路口关系。
