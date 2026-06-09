# Implementation Plan: Project Documentation Structure Cleanup

**Branch**: `codex/project-doc-audit-cleanup-20260609` | **Date**: 2026-06-09 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/project-doc-structure-cleanup-20260609/spec.md)
**Input**: Feature specification from `/specs/project-doc-structure-cleanup-20260609/spec.md`

## Summary

本轮以项目级文档低耦合重排为目标：入口文档只讲阅读链路和职责边界，项目事实文档只讲当前项目事实，模块盘点只讲模块业务目标和生命周期，文档盘点只讲文档结构与治理状态。所有模块级实现细节继续归属模块文档，不在项目级重复展开。

## Technical Context

**Language/Docs**: 中文 Markdown / CSV
**Primary Dependencies**: 当前项目级文档事实、用户 2026-06-08/2026-06-09 裁定
**Storage**: Git working tree
**Target Platform**: WSL, repo root `/mnt/e/Work/RCSD_Topo_Poc`
**Project Type**: GIS topology POC repository documentation governance
**Constraints**: 当前分支不是 `main`；不触碰模块级文档、源码、脚本、测试、入口登记；不新增长期执行入口；不改模块契约

## Constitution Check

- 当前分支：`codex/project-doc-audit-cleanup-20260609`
- 当前工作区存在既有未提交改动，必须保留并基于当前内容做增量编辑
- 本轮修改 project-level docs 和本 spec 目录
- 不进入 `modules/**`、`src/**`、`scripts/**`、`tests/**`
- 不修改 `docs/repository-metadata/**`

结论：允许继续；若审计发现必须进入模块级源事实或入口登记，停止并回报。

## Document Structure Decision

项目级文档按以下职责分层：

| 层级 | 文档 | 职责 |
|---|---|---|
| 项目事实 | `SPEC.md` | 项目目标、当前阶段、正式模块集合、主业务链、跨模块不变量 |
| 业务摘要 | `docs/PROJECT_BRIEF.md` | 面向业务读者的项目现状、范围、非目标与下一步治理缺口 |
| 架构视图 | `docs/architecture/*` | 架构目标、边界、约束、策略、质量、风险和术语 |
| 治理入口 | `docs/doc-governance/README.md` | 阅读顺序、文档职责边界、非主入口说明 |
| 生命周期 | `docs/doc-governance/module-lifecycle.md` | 模块生命周期状态，不展开模块实现过程 |
| 模块盘点 | `docs/doc-governance/current-module-inventory.md` | 模块业务目标、上下游关系和治理缺口 |
| 文档盘点 | `docs/doc-governance/current-doc-inventory.md` | 项目文档结构、每份文档业务范畴和治理状态 |
| 文档状态表 | `docs/doc-governance/module-doc-status.csv` | 机器可读模块文档状态索引 |

## Workstreams

1. 建立本轮 SpecKit 工件。
2. 审计项目级文档重复描述与过程性描述。
3. 清理 `docs/doc-governance/README.md`、`module-lifecycle.md`、`current-module-inventory.md`、`current-doc-inventory.md` 的职责重叠。
4. 视审计结果对 `SPEC.md`、`PROJECT_BRIEF.md`、`docs/architecture/*` 做最小必要收敛。
5. 运行范围检查、文本检索与 `git diff --check`。

## Acceptance Strategy

- `git diff --check`
- `git diff --name-only` 确认未触碰模块级路径
- `rg` 检索旧口径和过程性触发语
- 抽样阅读项目级文档结构表、生命周期表和模块凝练表
