# 文档治理入口

本文件是项目文档阅读入口和治理链路索引，只维护阅读顺序，不承载模块实现过程、项目事实全文或完整文档职责表。仓库根目录 `README.md` 是面向查看者的基础文档索引。

## 从哪里开始看

从 repo root `README.md` 或 `AGENTS.md` 进入后，按以下顺序阅读：

1. `SPEC.md`
2. `docs/PROJECT_BRIEF.md`
3. 需要理解全局业务概念、字段语义和跨模块技术方案时，进入 `docs/architecture/`
4. `docs/doc-governance/module-lifecycle.md`
5. `docs/doc-governance/current-module-inventory.md`
6. `docs/doc-governance/current-doc-inventory.md`
7. 只有在需要理解仓库结构、入口、文件体量与目录角色时，再进入 `docs/repository-metadata/README.md`
8. 如需启动新模块，再进入 `modules/_template/`

`specs/*`、`outputs/*`、`.claude/worktrees/*`、`.venv/*` 不属于 day-0 主阅读路径。

## 基础文档索引

- 仓库可见索引：`README.md`
- Agent 执行规则：`AGENTS.md`
- 项目事实入口：`SPEC.md`
- 业务摘要入口：`docs/PROJECT_BRIEF.md`
- 架构视图入口：`docs/architecture/`
- 模块生命周期入口：`docs/doc-governance/module-lifecycle.md`
- 模块业务盘点入口：`docs/doc-governance/current-module-inventory.md`
- 文档结构盘点入口：`docs/doc-governance/current-doc-inventory.md`
- 机器可读模块文档状态：`docs/doc-governance/module-doc-status.csv`
- 按需仓库结构入口：`docs/repository-metadata/README.md`

完整项目级文档结构、每份文档的业务范畴与非职责，只在 `docs/doc-governance/current-doc-inventory.md` 维护。

## 当前治理链路

- 仓库级执行规则：`AGENTS.md`
- 项目级源事实：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`
- 项目级盘点 / 索引：`docs/doc-governance/current-module-inventory.md`、`docs/doc-governance/current-doc-inventory.md`、`docs/doc-governance/module-doc-status.csv`
- 模块级源事实：`modules/<module>/architecture/*` 与 `modules/<module>/INTERFACE_CONTRACT.md`

## 非主入口

- `docs/doc-governance/history/`：历史治理过程材料
- `docs/doc-governance/audits/`：历史审计材料
- `docs/archive/`：已经退出主阅读路径的项目级历史参考
- `specs/*`：SpecKit 变更工件
- `outputs/*`：运行与审计工件

这些位置可用于追溯，但不替代当前项目级或模块级源事实。
