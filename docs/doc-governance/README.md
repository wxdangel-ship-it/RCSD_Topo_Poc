# 文档治理入口

## 从哪里开始看

如果你是从 repo root `AGENTS.md` 进入这里，按以下顺序继续：

1. `SPEC.md`
2. `docs/PROJECT_BRIEF.md`
3. `docs/doc-governance/module-lifecycle.md`
4. `docs/doc-governance/current-module-inventory.md`
5. `docs/doc-governance/current-doc-inventory.md`
6. 只有在需要理解仓库结构、入口、文件体量与目录角色时，再进入 `docs/repository-metadata/README.md`
7. 如需启动新模块，再进入 `modules/_template/`

说明：

- 本页是治理主入口，不是项目级 source-of-truth 的替代面。
- `docs/repository-metadata/README.md` 是按需结构入口，不是并列 day-0 主入口。
- `specs/*`、`outputs/*`、`.claude/worktrees/*`、`.venv/*` 不属于 day-0 主阅读路径。

## 当前治理链路

- 仓库级执行规则：`AGENTS.md`
- 项目级源事实：
  - `SPEC.md`
  - `docs/PROJECT_BRIEF.md`
  - `docs/architecture/*`
  - `docs/doc-governance/module-lifecycle.md`
- 项目级盘点 / 索引：
  - `docs/doc-governance/current-module-inventory.md`
  - `docs/doc-governance/current-doc-inventory.md`
  - `docs/doc-governance/module-doc-status.csv`

## 当前模块状态简表

- Active 正式业务模块：
  - `t01_data_preprocess`
  - `t02_junction_anchor`
  - `t03_virtual_junction_anchor`
  - `t04_divmerge_virtual_polygon`
- Support Retained：
  - `t00_utility_toolbox`
- 模板目录：
  - `modules/_template/`

说明：

- `_template` 仅用于后续模块启动，不属于业务模块生命周期盘点对象。
- `t00_utility_toolbox` 纳入治理，但定位为工具集合模块 / 非业务生产模块。
- `t02_junction_anchor` 当前仍是 Active 模块；其模块正文若处于独立重构中，应以该轮任务边界为准，不在其它治理轮次中顺手改写。
- `t03_virtual_junction_anchor` 当前进入 Active 模块集合；其正式范围为冻结 `Step3 legal-space baseline` 之上的 `Step4-7 clarified formal stage`。
- `t03_virtual_junction_anchor` 当前 repo 官方入口仍只有 `t03-step3-legal-space` 与 `t03-step45-rcsd-association`；`Step67` 已形成正式交付，但仍通过模块内 batch runner 与 closeout 维持。
- `t04_divmerge_virtual_polygon` 当前进入 Active 模块集合；其正式范围为 `Step1-4` 的模块化实现与 Step4 审计输出，不承接 Step5-7 与 repo 官方 CLI。
- 未在模块生命周期文档中登记的模块目录，不自动视为当前正式治理对象。

## 哪些文档不是主入口

- `docs/doc-governance/history/`：仓库级历史治理过程材料
- `docs/archive/nonstandard/`：项目级非标准历史说明
- `specs/*`：spec-kit 变更工件
- `outputs/*`：运行与审计工件

这些位置可以用于追溯与审计，但不替代当前项目级或模块级源事实。
