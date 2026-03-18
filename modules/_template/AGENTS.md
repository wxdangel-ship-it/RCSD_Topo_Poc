# <module_id> - AGENTS

## 开工前先读

- 先读 `architecture/01-introduction-and-goals.md`、`architecture/04-solution-strategy.md`、`architecture/10-quality-requirements.md`。
- 再读 `INTERFACE_CONTRACT.md`，确认稳定输入、输出、参数类别和验收标准。
- 若需要操作者入口，再读 `README.md`。
- 若需要治理摘要，再读 `review-summary.md`。
- 如需标准可复用流程，应创建 repo root `.agents/skills/<skill-name>/SKILL.md`，而不是在模块根目录新建 `SKILL.md`。

## 允许改动范围

- 默认只改本目录下文档：`architecture/*`、`INTERFACE_CONTRACT.md`、`AGENTS.md`、`README.md`、`review-summary.md`。
- 若无明确任务，不修改 `src/`、`tests/`、`scripts/`、`outputs/`、`data/`。
- 不跨模块改动其它 `INTERFACE_CONTRACT.md`。

## 必做验证

- 改文档前后对照 repo root `AGENTS.md`、`SPEC.md` 与项目级 `docs/architecture/*`，避免口径冲突。
- 修改 contract 时，必须回看本模块实现入口与关键测试，确认入口、输出与参数类别没有写错。
- 提交前至少执行 `git diff --check`。

## 禁做事项

- 不把 `AGENTS.md` 写成模块真相主表面。
- 不在没有明确任务书的情况下扩写为业务实现计划。
- 不在模块根目录新增 `SKILL.md`。

## 相邻模块关系

- 本文件应在模块具体化时补充上下游关系。
- 如发现与相邻模块或项目级源事实冲突，先停止并汇报。
