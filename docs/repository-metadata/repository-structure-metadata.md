# 当前仓库结构元数据说明

## 1. 文档目的

本文档用于描述当前仓库结构、标准文档放置规则和历史资料归档位置。

## 2. 当前顶层目录语义

### repo root

- 放仓库级 durable guidance、项目级 source-of-truth 与仓库级构建 / 运行元文件
- 当前受治理的根文件包括：`AGENTS.md`、`SPEC.md`、`Makefile`、`pyproject.toml`、`uv.lock`、`.gitignore`、`.gitattributes`
- 根目录不承载临时审计产物、运行输出或模块级事实

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

### `outputs/`

- 放本地运行、调试、审计与比对产物
- `outputs/` 与 `outputs/_work/` 默认不属于 source-of-truth，不进入 day-0 主阅读路径
- 若其中内容需要长期保留，应提炼为正式文档并迁移到 `docs/`、`modules/<module>/history/` 或 `specs/archive/`，而不是直接跟踪原始输出

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
- `Makefile`
- `pyproject.toml`
- `uv.lock`
- `.gitignore`
- `.gitattributes`
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
- `baselines/`

说明：

- 模块根目录不放 `SKILL.md`
- 标准 Skill 统一位于 repo root `.agents/skills/`
- `baselines/` 如存在，只承载 accepted / frozen 示例或对照样本；其结论必须由 `architecture/` 或 `INTERFACE_CONTRACT.md` 解释，不能单独充当 source-of-truth

## 4. 归档规则

- 项目级历史治理过程：`docs/doc-governance/history/`
- 项目级非标准说明：`docs/archive/nonstandard/`
- 历史变更工件：`specs/archive/`
- 模块级历史资料：`modules/<module>/history/`

## 5. 本目录的按需阅读顺序

本目录不是仓库 day-0 主入口。
按 `AGENTS.md`，应先进入 `docs/doc-governance/README.md`；只有在需要确认仓库结构、入口边界与体量约束时，再按下列顺序阅读：

1. `README.md`
2. `repository-structure-metadata.md`
3. `code-boundaries-and-entrypoints.md`
4. `entrypoint-registry.md`
5. `code-size-audit.md`

说明：

- `entrypoint-registry.md` 只登记当前真实入口，不裁定项目阶段或模块正式性
- `outputs/`、`outputs/_work/`、`.claude/worktrees/`、`.venv/` 不进入主阅读路径，不作为 source-of-truth
