# Tasks: Project Documentation Structure Cleanup

## Phase 1 - Scope

- [x] T001 确认当前分支不是 `main`
- [x] T002 读取 `docs/doc-governance/README.md` 与 `.agents/skills/default-imp/SKILL.md`
- [x] T003 创建本轮 SpecKit 工件

## Phase 2 - Audit

- [x] T010 审计项目级文档重复模块状态描述
- [x] T011 审计项目级文档早期过程性描述
- [x] T012 确认项目级文档职责结构

## Phase 3 - Cleanup

- [x] T020 清理 `docs/doc-governance/README.md`，保留阅读链路和职责边界
- [x] T021 清理 `docs/doc-governance/module-lifecycle.md`，收敛为生命周期事实
- [x] T022 清理 `docs/doc-governance/current-module-inventory.md`，保留凝练模块业务说明和缺口
- [x] T023 更新 `docs/doc-governance/current-doc-inventory.md`，明确项目文档结构与业务范畴
- [x] T024 对 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*` 做最小必要去重

## Phase 4 - Validation

- [x] T030 运行 `git diff --check`
- [x] T031 验证本轮不触碰 `modules/**`、`src/**`、`scripts/**`、`tests/**`
- [x] T032 检索旧口径与过程性描述残留
- [x] T033 抽样读取项目文档结构表、生命周期表、模块凝练表
