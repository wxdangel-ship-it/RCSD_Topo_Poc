# <module_id> Agent Guardrails

本文件是可选的 Agent 局部红线，不是模块源事实，也不是模块启动必建文档。

- 仓库级硬规则继承 repo root `AGENTS.md`。
- 模块需求以 `SPEC.md` 为准；接口契约以 `INTERFACE_CONTRACT.md` 为准；架构设计以 `architecture/*` 为准。
- 只有当模块存在项目级规则无法覆盖的特殊红线时，才保留本文件。
- 不在模块根目录新增 `SKILL.md`；可复用流程统一放 repo root `.agents/skills/`。
- 新增 repo CLI、root `scripts/`、Makefile 目标、模块 `run.py` 或模块 `__main__.py` 前，必须先满足 repo root 入口治理规则。
