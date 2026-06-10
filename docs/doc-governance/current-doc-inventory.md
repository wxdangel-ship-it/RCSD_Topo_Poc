# 当前文档盘点

## 范围

- 盘点日期：2026-06-09
- 目的：说明项目级文档结构、每份文档的业务范畴与治理状态
- 非职责：不复述模块实现过程，不替代模块级契约
- 边界：本文件是项目级文档结构与职责分工的唯一完整盘点；阅读顺序由 `docs/doc-governance/README.md` 维护

## 项目级文档结构

| 层级 | 文档 | 业务范畴 | 不承担 | 当前状态 |
|---|---|---|---|---|
| 仓库索引 | `README.md` | 仓库级基础文档索引，便于从根目录快速进入当前文档链路 | 项目事实全文、模块契约、Agent 硬规则 | active index |
| 仓库规则 | `AGENTS.md` | 会话级硬约束、停机规则、范围边界 | 项目事实摘要、模块业务说明 | active durable guidance |
| 项目规格 | `SPEC.md` | 项目目标、当前事实、主业务链、跨模块原则、治理不变量 | 模块内部步骤、字段规则、运行教程 | source of truth |
| 业务摘要 | `docs/PROJECT_BRIEF.md` | 面向业务读者的项目现状、范围、非目标和近期缺口 | 完整架构说明、模块契约 | source of truth |
| 架构视图 | `docs/architecture/01-introduction-and-goals.md` | 项目目标与架构目标 | 模块生命周期清单 | source of truth |
| 架构视图 | `docs/architecture/02-data-and-domain-model.md` | SWSD / RCSD / F-RCSD 全局业务概念、数据对象、字段语义和术语 | 模块局部字段规则、完整码表 | source of truth |
| 架构视图 | `docs/architecture/03-solution-strategy.md` | T08 -> T09 跨模块主方案、T00/T02/P01 边界 | 具体模块执行步骤 | source of truth |
| 架构视图 | `docs/architecture/04-evidence-and-audit.md` | 文件证据包、summary/audit/review、内外网信息反哺与历史文本协议口径 | 模块输出文件完整契约 | source of truth |
| 架构视图 | `docs/architecture/05-quality-requirements.md` | CRS、拓扑、几何语义、审计、性能、字段契约等项目级质量要求 | 单模块验收标准 | source of truth |
| 架构视图 | `docs/architecture/06-risks-and-technical-debt.md` | 项目级架构风险与技术债 | 运行日志、临时审计结论 | source of truth |
| 治理入口 | `docs/doc-governance/README.md` | 阅读顺序、治理链路、非主入口说明 | 项目事实全文、模块过程说明、完整职责表 | active durable guidance |
| 生命周期 | `docs/doc-governance/module-lifecycle.md` | 模块生命周期状态事实 | 模块业务解释、实现过程 | source of truth |
| 模块盘点 | `docs/doc-governance/current-module-inventory.md` | 模块业务目标、上下游关系、治理缺口 | 模块契约正文 | inventory |
| 文档盘点 | `docs/doc-governance/current-doc-inventory.md` | 文档结构、文档业务范畴、治理状态 | 模块实现细节 | inventory |
| 状态索引 | `docs/doc-governance/module-doc-status.csv` | 机器可读模块文档状态 | 人工阅读说明 | status snapshot |
| 仓库结构 | `docs/repository-metadata/README.md` | 仓库结构、入口、体量和目录角色的按需入口 | day-0 主阅读入口 | on-demand metadata |

## 模块文档面汇总

| 类别 | 范围 | 当前状态 |
|---|---|---|
| Active 正式业务模块文档面 | T01、T03、T04、T05、T06、T07、T08、T10 | 已具备标准模块文档面 |
| Active 正式业务模块缺口 | T09 | 已有实现、测试与文本证据包入口，缺少标准模块文档面 |
| Active POC / 成果模块文档面 | P01 | 已具备标准模块文档面 |
| Retired 模块文档面 | T02 | 历史文档、实现与支撑入口保留 |
| Support Retained 文档面 | T00 | 工具集合模块文档面保留 |
| 模板文档面 | `_template` | 新模块启动模板保留 |

## 非主阅读位置

| 路径 | 当前角色 |
|---|---|
| `docs/doc-governance/history/` | 历史治理过程材料 |
| `docs/doc-governance/audits/` | 历史审计材料 |
| `docs/archive/` | 已退出主阅读路径的项目级历史参考 |
| `specs/*` | SpecKit 变更工件，不替代源事实 |
| `outputs/*` | 运行与审计工件，不替代源事实 |

## 当前结论

1. 项目级文档已按项目规格、业务摘要、架构视图、治理入口、生命周期、模块盘点、文档盘点和状态索引分层。
2. 项目级文档不再承担模块实现过程说明，模块细节回到模块级 source-of-truth。
3. T09 模块文档面缺失仍是下一轮模块文档治理的优先缺口。
4. T10 已具备初始模块文档面，当前定位为端到端编排与 Case 证据组织。
5. T02 已 Retired，保留历史文档面与支撑入口，后续需同步入口登记 retired / historical 口径。
