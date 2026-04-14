# 仓库结构入口

本页不是并列的 day-0 主入口。只有在你已经按 `AGENTS.md -> docs/doc-governance/README.md` 建立了治理上下文，并且需要理解仓库结构、目录角色、执行入口和文件体量时，再进入本页。

## 建议阅读顺序

1. `repository-structure-metadata.md`
2. `code-boundaries-and-entrypoints.md`
3. `entrypoint-registry.md`
4. `code-size-audit.md`

## 各文件职责

- `repository-structure-metadata.md`
  - 解释当前顶层目录语义、标准文档白名单、`outputs/` 工件边界与模块关键子目录角色
- `code-boundaries-and-entrypoints.md`
  - 解释单文件体量阈值、执行入口治理和冲突停机规则
- `entrypoint-registry.md`
  - 记录当前已登记的正式入口索引
  - 若其内容与 `src/rcsd_topo_poc/cli.py`、`scripts/` 或模块契约不一致，应列出冲突并停止
- `code-size-audit.md`
  - 记录当前超阈值源码 / 脚本文件清单
  - 不等于拆分计划，只用于暴露结构债

## 阅读原则

- 本页只解释结构，不替代项目级 source-of-truth。
- 标准可复用流程统一看 repo root `.agents/skills/<skill-name>/SKILL.md`。
- 模块根目录不放 `SKILL.md`。
- `outputs/`、`outputs/_work/`、临时审计工件、`.claude/worktrees/`、`.venv/` 不属于结构主阅读路径。
