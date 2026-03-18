# 当前仓库结构元数据说明

## 1. 文档目的

本文档用于描述当前仓库结构、标准文档放置规则和历史资料归档位置。

## 2. 当前顶层目录语义

### repo root

- 放仓库级 durable guidance 和最高层项目规格
- 当前标准文档：`AGENTS.md`、`SPEC.md`

### `.agents/skills/`

- 放 repo root 级标准 Skill 包
- 用来承载可复用流程，不承载长期模块真相或 repo 级 durable guidance
- 当前只有目录说明，尚无具体 Skill 包

### `.specify/`

- 放 spec-kit 工作流脚手架、模板、脚本与宪章内存

### `.codex/prompts/`

- 放与 spec-kit 配套的 Codex prompt 资产

### `docs/`

- 放项目级文档
- 只保留项目摘要、项目级架构、治理入口、结构元数据和归档目录

### `modules/`

- 放模块级文档入口与模块历史资料
- 可执行实现不放这里，模块实现位于 `src/rcsd_topo_poc/modules/`

### `modules/_template/`

- 放新模块启动模板
- 不是业务模块，不参与模块生命周期盘点

### `src/rcsd_topo_poc/`

- 放仓库级共享代码与未来模块实现

### `tests/`

- 放共享代码测试与未来模块测试

### `scripts/`

- 放 repo 级执行辅助脚本
- 新增脚本必须登记

### `tools/`

- 放仓库级迁移、QA、验证工具

### `configs/`

- 放示例配置与未来配置样例

### `specs/`

- 放当前 active change 的 spec-kit 工件

### `specs/archive/`

- 放历史变更工件

## 3. 标准文档白名单

### repo root

允许：

- `AGENTS.md`
- `SPEC.md`
- `.agents/skills/`
- `.specify/`
- `.codex/prompts/`

### `.agents/skills/`

允许：

- `README.md`
- `<skill-name>/SKILL.md`
- `<skill-name>/references/`
- `<skill-name>/scripts/`
- `<skill-name>/assets/`

### `docs/`

允许：

- `PROJECT_BRIEF.md`
- `ARTIFACT_PROTOCOL.md`
- `architecture/`
- `doc-governance/`
- `repository-metadata/`
- `metadata-cleanup/`
- `archive/`

### `docs/doc-governance/`

允许：

- `README.md`
- `module-lifecycle.md`
- `current-module-inventory.md`
- `current-doc-inventory.md`
- `module-doc-status.csv`
- `history/`

### `docs/repository-metadata/`

允许：

- `README.md`
- `repository-structure-metadata.md`
- `code-boundaries-and-entrypoints.md`
- `code-size-audit.md`
- `entrypoint-registry.md`

### `modules/_template/`

允许：

- `AGENTS.md`
- `INTERFACE_CONTRACT.md`
- `README.md`
- `review-summary.md`
- `architecture/`
- `history/`
- `scripts/`

### `modules/<module>/`

允许：

- `AGENTS.md`
- `INTERFACE_CONTRACT.md`
- `README.md`
- `review-summary.md`
- `architecture/`
- `history/`
- `scripts/`

说明：

- 模块根目录不放 `SKILL.md`
- 标准 Skill 统一位于 repo root `.agents/skills/`

## 4. 归档规则

- 项目级历史治理过程：`docs/doc-governance/history/`
- 项目级非标准说明：`docs/archive/nonstandard/`
- 历史变更工件：`specs/archive/`
- 模块级历史资料：`modules/<module>/history/`

## 5. 当前主阅读顺序

1. `AGENTS.md`
2. `SPEC.md`
3. `docs/PROJECT_BRIEF.md`
4. `docs/doc-governance/README.md`
5. `docs/repository-metadata/README.md`
6. `docs/repository-metadata/code-boundaries-and-entrypoints.md`
7. `docs/doc-governance/module-lifecycle.md`
8. `docs/doc-governance/current-module-inventory.md`
9. `docs/doc-governance/current-doc-inventory.md`
10. 如需启动模块，再进入 `modules/_template/`
