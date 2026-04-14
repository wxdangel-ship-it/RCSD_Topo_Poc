# Implementation Plan: Repository Governance Realignment

**Branch**: `002-repo-governance-realignment` | **Date**: 2026-04-14 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/002-repo-governance-realignment/spec.md)
**Input**: Feature specification from `/specs/002-repo-governance-realignment/spec.md`

## Summary

本轮治理修复回到 repo root `AGENTS.md` 所声明的原始契约，只做仓库级和非 T02 模块级的治理对齐，不新增治理体系，不新增主入口页，不进入 T02 正文。

修复主线分为四块：

1. 入口链路修复：让 `AGENTS.md -> docs/doc-governance/README.md -> docs/repository-metadata/README.md（按需）` 可执行、无循环。
2. 项目级 source-of-truth 一致化：统一项目阶段、模块名单和项目级叙述。
3. 模板与非 T02 模块对齐：让 `_template`、`t00`、`t01` 文档角色边界与当前仓库入口方式一致。
4. 元数据与验证修复：重建入口注册表可信度、刷新结构元数据和代码体量审计。

## Technical Context

**Language/Docs**: 中文治理文档 + Markdown / CSV
**Primary Dependencies**: 当前仓库文档体系、`src/rcsd_topo_poc/cli.py`、`scripts/`、`pytest` smoke/doctor
**Storage**: Git working tree + `outputs/_work/repo_governance_realign_20260414_142216/`
**Target Platform**: WSL on Windows, repository root `/mnt/e/Work/RCSD_Topo_Poc`
**Project Type**: GIS topology POC repository governance realignment
**Constraints**: 不得修改 T02 正文；不新增新的治理体系；不在 `main` 上做结构化治理改动；必须保留现有未提交改动，不 reset、不覆盖

## Constitution Check

*GATE: Must pass before execution. Re-check after edits.*

- 已确认当前分支不是 `main`：`codex/t02-stage3-arch-refactor-anchor61`
- 已确认存在未提交改动，且 T02 相关改动视为保护区
- 本轮只允许在用户授权路径内工作
- 本轮继续使用 spec-kit，不绕开现有治理链路
- 本轮不新增执行入口、不进入 T02 模块正文

当前 gating 结论：**允许继续，但必须保持范围保护与冲突停机。**

## Workstreams

### Workstream A - AGENTS 与阅读链路修复

责任文件：

- `AGENTS.md`
- `docs/doc-governance/README.md`
- `docs/repository-metadata/README.md`

目标：

- 增强 `AGENTS.md` 的执行阻断力
- 恢复原始阅读链路
- 明确 outputs / `_work` / `.claude/worktrees` / `.venv` 不属于主阅读路径

### Workstream B - 项目级 source-of-truth 一致化

责任文件：

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/architecture/*`
- `docs/doc-governance/module-lifecycle.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/module-doc-status.csv`

目标：

- 统一项目阶段与正式模块口径
- 让 `t00 / t01 / t02` 的项目级表述一致
- 对 T02 只保留最小项目级状态说明

### Workstream C - 模板与非 T02 模块治理修复

责任文件：

- `modules/_template/*`
- `modules/t00_utility_toolbox/*`
- `modules/t01_data_preprocess/*`

目标：

- 修复 `_template` 的旧入口示意
- 明确 README / INTERFACE_CONTRACT / AGENTS / architecture / history 的职责边界
- 让 `t00` 明确保持工具集合模块边界
- 让 `t01` 的操作者入口与仓库入口方式一致

### Workstream D - 元数据、入口注册与验证

责任文件：

- `docs/repository-metadata/repository-structure-metadata.md`
- `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- `docs/repository-metadata/entrypoint-registry.md`
- `docs/repository-metadata/code-size-audit.md`

目标：

- 用真实 `cli.py` / `scripts/` 刷新 registry
- 明确结构元数据和工件边界
- 刷新超阈值文件清单
- 形成验证与范围保护报告

## Execution Order

1. 先落 `spec.md / plan.md / tasks.md`
2. 并行推进 A/B/C/D 四个工作流
3. 集成改动并做范围保护检查
4. 运行 `python -m rcsd_topo_poc --help`
5. 如安全可执行，再运行 `python -m rcsd_topo_poc doctor`
6. 输出执行摘要、改动映射、验证报告、未决事项

## Risks

- 允许路径中已有未提交改动，编辑时必须基于当前工作树增量补丁，避免覆盖用户改动。
- `entrypoint-registry.md` 已有本地改动，刷新时必须以当前内容为基础。
- `cli.py` 包含 T02 入口事实；允许读取并在 registry 中登记，但不允许修改 `cli.py`。
- tracked `outputs` 工件问题可能需要更大范围清理；本轮最多做最小必要说明，避免扩大改动面。

## Acceptance Strategy

### Static Validation

- 修改文件全部位于允许路径内
- 禁止路径无改动
- 入口阅读链路文本自洽
- 项目级 source-of-truth 不再互相打架

### Runtime Validation

- `python -m rcsd_topo_poc --help`
- `python -m rcsd_topo_poc doctor`

### Governance Validation

- 用真实 `cli.py` / `scripts/` 对照 `entrypoint-registry.md`
- 刷新 `code-size-audit.md` 的依据
- 核对 `spec.md / plan.md / tasks.md` 是否闭环
