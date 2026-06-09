# Feature Specification: Project Documentation Structure Cleanup

**Feature Branch**: `codex/project-doc-audit-cleanup-20260609`
**Created**: 2026-06-09
**Status**: Draft
**Input**: 用户要求进行项目级、暂不涉及模块级的需求审计，清理项目级文档中的重复描述和早期过程性约束，并给出低耦合、高内聚的项目文档结构与业务范畴。

## Summary

本轮只治理项目级文档表达，不改业务算法、不改执行入口、不进入 `modules/<module>/` 模块级文档。目标是让项目级文档从“早期约束与过程记录混杂”收敛为“当前事实、文档职责、模块关系、治理缺口”四类低耦合表面。

## Scope

### In Scope

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/architecture/*`
- `docs/doc-governance/README.md`
- `docs/doc-governance/module-lifecycle.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/module-doc-status.csv`
- `specs/project-doc-structure-cleanup-20260609/*`

### Out of Scope

- `modules/**`
- `src/**`
- `scripts/**`
- `tests/**`
- `docs/repository-metadata/**` 入口、体量与仓库结构登记
- 新增、删除、重命名官方入口
- 新增模块级契约或模块级 architecture 文档

## User Scenarios & Testing

### User Story 1 - 项目文档读者能快速找到唯一职责入口 (Priority: P1)

作为项目文档读者，我需要知道每份项目级文档承担什么职责、哪些内容不应写入该文档，避免在多个文档中阅读同一模块过程描述。

**Independent Test**: 仅阅读 `docs/doc-governance/README.md` 和 `docs/doc-governance/current-doc-inventory.md`，即可明确项目级文档结构与职责边界。

### User Story 2 - 项目事实描述以当前状态为准 (Priority: P1)

作为治理维护者，我需要项目级源事实不再复述早期“为了约束边界”的过程性描述，而是直接表达当前项目阶段、模块生命周期和主业务链。

**Independent Test**: 检索项目级主文档，不应再出现大段重复模块过程、旧阶段防御性说明或与当前生命周期相反的口径。

### User Story 3 - 模块关系可在项目级被快速理解 (Priority: P2)

作为新进入项目的人，我需要一张凝练的模块业务说明表，能理解每个模块的目标、上下游关系与当前生命周期，而不需要进入模块级文档。

**Independent Test**: 阅读 `docs/doc-governance/current-module-inventory.md` 的凝练表，即可理解 T00/T01/T02/T03/T04/T05/T06/T07/T08/T09/P01 的关系。

## Requirements

### Product

- **FR-PD-001**: 项目级文档必须面向“快速理解项目现状与模块关系”，不再承担模块级实现过程说明。
- **FR-PD-002**: 每个模块的业务目标说明必须凝练、准确，并能表达与上下游模块关系。

### Architecture

- **FR-AR-001**: 项目级文档结构必须低耦合、高内聚，每份文档只承担一个主要职责。
- **FR-AR-002**: 项目级 source-of-truth、盘点索引、治理入口、架构视图必须分工明确，不互相复制正文。

### Development

- **FR-DV-001**: 本轮不得修改模块级文档、源码、脚本、测试或入口登记。
- **FR-DV-002**: 清理只能基于当前仓库已确认事实，不得发明新模块状态或新增业务规则。

### Testing

- **FR-TE-001**: 必须通过文本检索验证旧口径、重复性大段描述和过程性触发语已收敛。
- **FR-TE-002**: 必须通过 `git diff --check` 验证 Markdown / CSV 无空白格式错误。

### QA

- **FR-QA-001**: 完成回报必须区分已修改、已验证、待确认，并列出每个修改文件目的。
- **FR-QA-002**: 若发现项目级事实冲突或需要进入模块级文档，必须停止并回报。

## Success Criteria

- **SC-001**: 项目级文档有明确结构表，能说明每份文档的业务范畴与非职责。
- **SC-002**: `docs/doc-governance/README.md` 不再展开长篇模块过程说明，只保留阅读链路与职责边界。
- **SC-003**: `docs/doc-governance/current-module-inventory.md` 保留凝练模块业务说明，移除重复的长篇实现状态展开。
- **SC-004**: 项目级文档中 T02/T09/P01/T01/T04 的当前口径与用户裁定一致。
- **SC-005**: 本轮实际修改不触及 `modules/**`、`src/**`、`scripts/**`、`tests/**`。
