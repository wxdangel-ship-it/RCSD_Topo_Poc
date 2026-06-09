# Implementation Plan: Project Architecture Documentation Governance

**Branch**: `codex/project-doc-architecture-governance-20260609` | **Date**: 2026-06-09 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/project-architecture-doc-governance-20260609/spec.md)
**Input**: Feature specification from `/specs/project-architecture-doc-governance-20260609/spec.md`

## Summary

本轮将项目级架构文档从旧 arc42 式分散章节收敛为当前项目需要的 6 个长期文档：目标、数据与业务模型、跨模块方案、证据审计、质量要求、风险债务。文档治理与仓库技术元数据保持独立目录，不再在 architecture 中重复维护。

## Technical Context

**Language/Docs**: 中文 Markdown
**Primary Dependencies**: 当前项目级源事实、用户 2026-06-09 文档治理裁定
**Storage**: Git working tree
**Target Platform**: WSL, repo root `/mnt/e/Work/RCSD_Topo_Poc`
**Project Type**: GIS topology POC repository documentation governance
**Constraints**: 当前分支不是 `main`；不触碰 `modules/**`、`src/**`、`scripts/**`、`tests/**`；不变更实际入口；不新增 `domain/` 目录

## Constitution Check

- 当前分支：`codex/project-doc-architecture-governance-20260609`
- 本轮修改 project-level docs 和本 spec 目录
- `docs/architecture/*` 属项目级源事实，用户已授权项目级仓库文档治理和 architecture 审计
- `docs/repository-metadata/*` 仅同步结构元数据和入口描述口径，不改变真实入口
- 不进入模块级源事实或实现目录

结论：允许继续；若审计发现必须修改模块契约、CLI 或 scripts 实现，停止并回报。

## Target Architecture Documentation Structure

| 文档 | 职责 |
|---|---|
| `docs/architecture/01-introduction-and-goals.md` | 项目级架构目标、非目标和职责边界 |
| `docs/architecture/02-data-and-domain-model.md` | SWSD / RCSD / F-RCSD 全局业务概念、数据对象、字段语义和术语 |
| `docs/architecture/03-solution-strategy.md` | T08 -> T09 跨模块主方案、P01 边界、T00/T02 生命周期影响 |
| `docs/architecture/04-evidence-and-audit.md` | 文件证据包、summary/audit/review、内外网信息反哺和历史文本协议口径 |
| `docs/architecture/05-quality-requirements.md` | CRS、拓扑、几何语义、审计、性能、复现和字段契约质量要求 |
| `docs/architecture/06-risks-and-technical-debt.md` | 当前项目级架构风险和技术债 |

## Workstreams

1. 建立本轮 SpecKit 工件。
2. 删除或收编旧 architecture 低价值拆分与空壳目录。
3. 重写 architecture 长期文档，承载全局业务概念、字段语义、跨模块方案和质量风险。
4. 将旧 `ARTIFACT_PROTOCOL.md` 归档为历史参考，正式口径改为文件证据包和 summary/audit/review。
5. 收编 `metadata-cleanup/` 与 `archive/nonstandard/` 非主入口目录。
6. 同步 repo root `README.md`、`SPEC.md`、`PROJECT_BRIEF.md`、`doc-governance` 和 `repository-metadata`。
7. 运行检索、路径范围和 `git diff --check`。

## Acceptance Strategy

- `git diff --check`
- `git diff --name-only` 确认未触碰模块级路径、源码、脚本、测试
- `rg` 检索旧文件名和旧协议引用
- 抽样阅读 repo root README、current-doc-inventory、architecture 6 个目标文档
