# Feature Specification: Project Architecture Documentation Governance

**Feature Branch**: `codex/project-doc-architecture-governance-20260609`
**Created**: 2026-06-09
**Status**: Draft
**Input**: 用户要求基于当前项目级讨论启动仓库文档治理，重点审计并收敛 `docs/architecture/` 与 `docs/doc-governance/`、`docs/repository-metadata/` 的重复耦合。

## Summary

本轮只治理项目级仓库文档结构，不进入模块级文档、源码、脚本、测试或入口变更。目标是把 `docs/architecture/` 从早期分散章节收敛为“全局业务数据语义、跨模块技术方案、证据审计、质量要求、风险债务”的长期架构文档面，同时保留 `repository-metadata/` 作为仓库技术元数据目录，并让 repo root `README.md` 成为基础文档索引。

## Scope

### In Scope

- repo root `README.md`
- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/architecture/*`
- `docs/doc-governance/README.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/repository-metadata/repository-structure-metadata.md`
- `docs/repository-metadata/entrypoint-registry.md` 中旧文本协议入口的描述口径
- `docs/archive/*`
- `specs/project-architecture-doc-governance-20260609/*`

### Out of Scope

- `modules/**`
- `src/**`
- `scripts/**`
- `tests/**`
- 新增、删除、重命名或改变官方执行入口
- T09 模块文档面补齐
- architecture 目录下模块级算法细节展开

## User Scenarios & Testing

### User Story 1 - 用户能快速理解项目级仓库文档结构 (Priority: P1)

作为项目维护者，我需要从 repo root `README.md` 快速知道每份项目级文档承载什么内容，避免只看文件名仍不知道应读哪份文档。

**Independent Test**: 只阅读 repo root `README.md` 与 `docs/doc-governance/current-doc-inventory.md`，即可区分项目事实、架构、文档治理和仓库元数据职责。

### User Story 2 - architecture 只承载项目级架构事实 (Priority: P1)

作为架构文档读者，我需要 `docs/architecture/` 聚焦全局业务概念、字段语义、跨模块方案、证据审计、质量风险，不再重复文档治理和仓库技术元数据。

**Independent Test**: 检索 architecture 文档，不应出现把阅读链路、入口登记、目录白名单等仓库治理正文重复维护为架构事实的内容。

### User Story 3 - 旧文本协议不再误导为当前唯一协作方式 (Priority: P2)

作为项目协作者，我需要知道当前以内网文件证据包、summary/audit/review 和必要文本提炼为主，旧 `TEXT_QC_BUNDLE` 只作为历史兼容工具存在。

**Independent Test**: 项目级主文档不再把 `TEXT_QC_BUNDLE` 表述为当前正式唯一协议；入口注册表仍可保留真实存在的兼容入口。

## Requirements

### Product

- **FR-PD-001**: repo root `README.md` 必须作为仓库级基础文档索引，说明每个主要文件的内容承载范围。
- **FR-PD-002**: `docs/architecture/` 必须提供项目级全局业务概念、字段语义和跨模块设计信息。

### Architecture

- **FR-AR-001**: `docs/architecture/`、`docs/doc-governance/`、`docs/repository-metadata/` 必须低耦合：架构写业务与技术方案，文档治理写阅读链路和盘点，仓库元数据写目录/入口/体量事实。
- **FR-AR-002**: 不新增 `domain/` 目录；全局业务概念和字段说明由 `docs/architecture/` 承载。
- **FR-AR-003**: 空壳 ADR 目录不作为当前结构保留；未来有真实决策记录时再建立。

### Development

- **FR-DV-001**: 本轮不得修改模块级文档、源码、脚本、测试或实际入口。
- **FR-DV-002**: 若入口注册表描述发生变化，只能描述当前真实入口状态，不得暗示代码入口已删除或变更。
- **FR-DV-003**: 删除或收编非主入口目录时，必须同步更新文档结构盘点和仓库结构元数据。

### Testing

- **FR-TE-001**: 必须通过 `git diff --check` 验证 Markdown 无空白格式错误。
- **FR-TE-002**: 必须检索旧 architecture 文件名、`TEXT_QC_BUNDLE`、`ARTIFACT_PROTOCOL`、`metadata-cleanup`、`archive/nonstandard` 等残留引用。
- **FR-TE-003**: 必须确认本轮未触碰 `modules/**`、`src/**`、`scripts/**`、`tests/**`。

### QA

- **FR-QA-001**: 完成回报必须区分已修改、已验证、待确认，并列出修改文件目的。
- **FR-QA-002**: 若发现项目级源事实冲突或需要进入模块级事实，必须停止并回报。

## Success Criteria

- **SC-001**: `docs/architecture/` 收敛为少量长期文档，不再保留无内容 ADR 目录和低价值拆分。
- **SC-002**: `docs/doc-governance/current-doc-inventory.md` 是完整职责表；repo root `README.md` 是基础文档索引。
- **SC-003**: `repository-metadata/` 继续保留，只承载仓库技术元数据。
- **SC-004**: 旧 `ARTIFACT_PROTOCOL.md` 不再作为正式项目协议出现在主文档结构中。
- **SC-005**: 本轮实际修改不触及模块级文档、源码、脚本、测试和执行入口实现。
