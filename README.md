# RCSD_Topo_Poc

本文件是仓库唯一项目级 README 与主阅读入口，负责从根目录进入当前项目文档链路。它不替代项目级 source-of-truth、模块契约或 Agent 执行规则。

## 从哪里开始看

1. `SPEC.md`
2. `docs/PROJECT_REQUIREMENTS.md`
3. 需要理解全局业务概念、字段语义和跨模块技术方案时，进入 `docs/architecture/`
4. `docs/doc-governance/README.md`
5. 只有在需要理解仓库结构、入口、文件体量与目录角色时，再进入 `docs/repository-metadata/README.md`
6. 如需启动新模块，再进入 `modules/_template/`

`specs/*`、`outputs/*`、`outputs/_work/*`、`.claude/worktrees/*`、`.venv/*` 不属于 day-0 主阅读路径。

## 快速入口

| 入口 | 用途 |
|---|---|
| `AGENTS.md` | Agent 会话级硬规则、停机条件和执行边界。 |
| `SPEC.md` | 项目级需求简版，便于从根目录快速看懂目标、主链、范围和改进重点。 |
| `docs/PROJECT_REQUIREMENTS.md` | 项目级需求详细版，解释业务背景、分层需求、模块边界、T06 质量承接和验收口径。 |
| `docs/architecture/` | 全局业务概念、字段语义、跨模块技术方案、证据审计、质量要求和架构风险。 |
| `docs/doc-governance/README.md` | 文档治理入口，维护治理阅读顺序、模块文档模板和非主阅读材料边界。 |
| `docs/doc-governance/module-lifecycle.md` | 当前模块生命周期状态事实。 |
| `docs/doc-governance/current-doc-inventory.md` | 项目级文档结构与职责分工的唯一完整盘点。 |
| `docs/doc-governance/current-module-inventory.md` | 当前模块业务目标、上下游关系和治理缺口。 |
| `docs/doc-governance/module-doc-status.csv` | 机器可读模块文档状态。 |
| `docs/doc-governance/module-doc-template.md` | 模块文档模板与写法规则，基于 T03 已确认结构沉淀。 |
| `docs/repository-metadata/README.md` | 仓库结构、入口、文件体量和目录角色的按需入口。 |

完整项目级文档结构、每份文档的业务范畴与非职责，只在 `docs/doc-governance/current-doc-inventory.md` 维护；模块文档模板与写法规则只在 `docs/doc-governance/module-doc-template.md` 维护。

## 当前治理链路

- 仓库级执行规则：`AGENTS.md`
- 项目级源事实：`SPEC.md`、`docs/PROJECT_REQUIREMENTS.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`
- 项目级盘点 / 索引：`docs/doc-governance/current-module-inventory.md`、`docs/doc-governance/current-doc-inventory.md`、`docs/doc-governance/module-doc-status.csv`
- 模块级源事实：`modules/<module>/architecture/*` 与 `modules/<module>/INTERFACE_CONTRACT.md`

## 边界

- 模块内部算法、字段、步骤、入口与验收细节，以 `modules/<module>/architecture/*` 和 `modules/<module>/INTERFACE_CONTRACT.md` 为准。
- `specs/*` 是 SpecKit 变更工件，不替代当前项目级或模块级源事实。
- `outputs/*` 是运行与审计工件，不属于主阅读路径。
- `docs/doc-governance/history/`、`docs/doc-governance/audits/` 与 `docs/archive/` 可用于追溯，但不替代当前项目级或模块级源事实。
