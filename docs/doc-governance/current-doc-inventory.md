# 当前文档盘点

## 范围

- 盘点日期：2026-06-10
- 目的：说明项目级文档结构、每份文档的业务范畴与治理状态
- 非职责：不复述模块实现过程，不替代模块级契约
- 边界：本文件是项目级文档结构与职责分工的唯一完整盘点；治理阅读顺序由 `docs/doc-governance/README.md` 维护，repo root `README.md` 只保留项目级最短入口

## 项目级文档结构

| 层级 | 文档 | 业务范畴 | 不承担 | 当前状态 |
|---|---|---|---|---|
| 仓库阅读入口 | `README.md` | 仓库唯一项目级 README，维护主阅读顺序、基础文档索引和治理链路入口 | 项目事实全文、模块契约、Agent 硬规则 | active durable guidance |
| 仓库规则 | `AGENTS.md` | 会话级硬约束、停机规则、范围边界 | 项目事实摘要、模块业务说明 | active durable guidance |
| 项目简版需求 | `SPEC.md` | 根目录项目级需求简版：目标、主业务链、核心需求、范围、非目标和近期改进重点 | 详细业务背景、模块内部步骤、字段规则、运行教程 | source of truth |
| 项目详细需求 | `docs/PROJECT_REQUIREMENTS.md` | 项目级需求详细版：业务背景、分层需求、模块边界、T06 质量承接、质量验收和改进路线 | 模块完整接口契约、实现细节、运行教程 | source of truth |
| 架构视图 | `docs/architecture/01-introduction-and-goals.md` | 项目目标与架构目标 | 模块生命周期清单 | source of truth |
| 架构视图 | `docs/architecture/02-data-and-domain-model.md` | SWSD / RCSD / F-RCSD 全局业务概念、数据对象、字段语义和术语 | 模块局部字段规则、完整码表 | source of truth |
| 架构视图 | `docs/architecture/03-solution-strategy.md` | T08 -> T09 跨模块主方案、T00/T02/P01 边界 | 具体模块执行步骤 | source of truth |
| 架构视图 | `docs/architecture/04-evidence-and-audit.md` | 文件证据包、summary/audit/review、内外网信息反哺与历史文本协议口径 | 模块输出文件完整契约 | source of truth |
| 架构视图 | `docs/architecture/05-quality-requirements.md` | CRS、拓扑、几何语义、审计、性能、字段契约等项目级质量要求 | 单模块验收标准 | source of truth |
| 架构视图 | `docs/architecture/06-risks-and-technical-debt.md` | 项目级架构风险与技术债 | 运行日志、临时审计结论 | source of truth |
| 生命周期 | `docs/doc-governance/module-lifecycle.md` | 模块生命周期状态事实 | 模块业务解释、实现过程 | source of truth |
| 文档治理入口 | `docs/doc-governance/README.md` | 文档治理阅读顺序、模块模板入口和非主阅读材料边界 | 项目业务需求正文、模块契约正文 | active durable guidance |
| 模块盘点 | `docs/doc-governance/current-module-inventory.md` | 模块业务目标、上下游关系、治理缺口 | 模块契约正文 | inventory |
| 文档盘点 | `docs/doc-governance/current-doc-inventory.md` | 文档结构、文档业务范畴、治理状态 | 模块实现细节 | inventory |
| 模块模板 | `docs/doc-governance/module-doc-template.md` | 模块文档模板、T03 结构沉淀和业务表达规则 | 具体模块事实、模块接口值域 | active durable guidance |
| 状态索引 | `docs/doc-governance/module-doc-status.csv` | 机器可读模块文档状态 | 人工阅读说明 | status snapshot |
| 仓库结构 | `docs/repository-metadata/README.md` | 仓库结构、入口、体量和目录角色的按需入口 | day-0 主阅读入口 | on-demand metadata |

## 模块文档面汇总

| 类别 | 范围 | 当前状态 |
|---|---|---|
| Active 正式业务模块文档面 | T01、T03、T04、T05、T06、T07、T08、T09、T10 | 已按 T03 模板具备标准 01-06 模块文档面；模块 `SPEC.md` 承载模块需求，`architecture/03-solution-strategy.md` 承载架构设计 / 需求具体实现策略，`INTERFACE_CONTRACT.md` 承载稳定接口契约；模块级 `AGENTS.md` 仅作为可选 Agent 局部红线 |
| Active POC / 成果模块文档面 | P01、P02 | 已具备标准模块文档面；各模块 `SPEC.md` 明确 POC 业务需求和不替代正式业务模块的边界 |
| Retired 模块文档面 | T02 | 历史文档、实现与支撑入口保留；`SPEC.md` 明确 retired / historical 需求口径 |
| Support Retained 文档面 | T00 | 工具集合模块文档面保留；`SPEC.md` 明确支撑工具范围和非业务生产边界 |
| 模板文档面 | `_template` | 新模块启动模板保留；结构与 `docs/doc-governance/module-doc-template.md` 保持一致 |

## 非主阅读位置

| 路径 | 当前角色 |
|---|---|
| `docs/doc-governance/history/` | 历史治理过程材料 |
| `docs/doc-governance/audits/` | 历史审计材料 |
| `docs/archive/` | 已退出主阅读路径的项目级历史参考 |
| `specs/*` | SpecKit 变更工件，不替代源事实 |
| `outputs/*` | 运行与审计工件，不替代源事实 |

## 当前结论

1. 项目级文档已按根目录简版需求、docs 详细需求、架构视图、生命周期、模块盘点、文档盘点、模板说明和状态索引分层；项目入口收口到 repo root `README.md`，文档治理入口收口到 `docs/doc-governance/README.md`。
2. 项目级文档不再承担模块实现过程说明，模块细节回到模块级 source-of-truth。
3. T00、T01、T03、T04、T05、T06、T07、T08、T09、T10 已按 T03 模板完成模块级主结构对齐；T02 与 P01 按本轮任务边界不纳入整改范围。
4. T09 后续业务迭代重点仍是 RCSD Laneinfo 与轨迹通行证据补充。
5. T10 当前定位为端到端编排与 Case 证据组织，不替代项目级主业务链。
6. T02 已 Retired，保留历史文档面与支撑入口，后续需同步入口登记 retired / historical 口径。
