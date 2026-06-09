# RCSD_Topo_Poc

本文件是仓库级基础文档索引，便于从仓库根目录快速进入当前项目文档。它不替代项目级 source-of-truth、模块契约或 Agent 执行规则。

## 快速入口

| 入口 | 用途 |
|---|---|
| `AGENTS.md` | Agent 会话级硬规则、停机条件和执行边界。 |
| `SPEC.md` | 项目目标、当前事实、主业务链、跨模块原则和治理不变量。 |
| `docs/PROJECT_BRIEF.md` | 面向业务读者的项目摘要、范围、非目标和近期治理缺口。 |
| `docs/architecture/` | 全局业务概念、字段语义、跨模块技术方案、证据审计、质量要求和架构风险。 |
| `docs/doc-governance/README.md` | 项目文档阅读顺序和治理链路。 |
| `docs/doc-governance/current-doc-inventory.md` | 项目级文档结构与职责分工的唯一完整盘点。 |
| `docs/doc-governance/current-module-inventory.md` | 当前模块业务目标、上下游关系和治理缺口。 |
| `docs/doc-governance/module-lifecycle.md` | 当前模块生命周期状态事实。 |
| `docs/repository-metadata/README.md` | 仓库结构、入口、文件体量和目录角色的按需入口。 |

## 当前阅读建议

1. 想快速了解项目现状：读 `SPEC.md` 和 `docs/PROJECT_BRIEF.md`。
2. 想理解全局业务概念、字段语义和跨模块技术方案：读 `docs/architecture/`。
3. 想了解文档怎么分工：读 `docs/doc-governance/current-doc-inventory.md`。
4. 想了解模块关系：读 `docs/doc-governance/current-module-inventory.md`。
5. 想执行 Agent 任务：先读 `AGENTS.md`。

## 边界

- 模块内部算法、字段、步骤、入口与验收细节，以 `modules/<module>/architecture/*` 和 `modules/<module>/INTERFACE_CONTRACT.md` 为准。
- `specs/*` 是 SpecKit 变更工件，不替代当前项目级或模块级源事实。
- `outputs/*` 是运行与审计工件，不属于主阅读路径。
