# 01 引言与目标

## 文档定位

本文档说明项目级架构目标与边界。模块生命周期、模块业务说明和文档结构盘点分别由 `docs/doc-governance/module-lifecycle.md`、`docs/doc-governance/current-module-inventory.md`、`docs/doc-governance/current-doc-inventory.md` 承载。

## 架构目标

- 支撑 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09` 主业务链的持续治理。
- T10 审计编排在 T06 后、T09 前固定执行 T11 candidate extraction，但不改变主业务数据链。
- 沉淀 SWSD、RCSD、F-RCSD、语义路口、Segment、字段语义等跨模块共用信息。
- 保持项目级架构、文档治理、仓库元数据、模块契约职责分离。
- 保证 GIS / 拓扑 / 空间数据处理结果可解释、可审计、可复现、可验证。

## 非目标

- 不在 architecture 中重复模块内部 Step、参数、阈值、入口和验收细节。
- 不承载目录白名单、入口登记、文件体量等仓库技术元数据。
- 不维护阅读顺序、文档职责完整表或模块生命周期事实。
- 不替代 `modules/<module>/architecture/*` 与 `modules/<module>/INTERFACE_CONTRACT.md`。

## 结构

| 文档 | 职责 |
|---|---|
| `01-introduction-and-goals.md` | 架构目标、非目标和职责边界 |
| `02-data-and-domain-model.md` | 全局业务概念、数据对象、字段语义和术语 |
| `03-solution-strategy.md` | 跨模块主方案与 POC 边界 |
| `04-evidence-and-audit.md` | 文件证据包、summary/audit/review 与内外网信息反哺 |
| `05-quality-requirements.md` | CRS、拓扑、几何、审计、性能和契约质量要求 |
| `06-risks-and-technical-debt.md` | 项目级架构风险和技术债 |
