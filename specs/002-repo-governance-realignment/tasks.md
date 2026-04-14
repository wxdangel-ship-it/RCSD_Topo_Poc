# Tasks: Repository Governance Realignment

## Phase 0 - Preflight

- [x] T001 记录 `pwd / repo root / branch / git status --short`
- [x] T002 确认当前分支不是 `main`
- [x] T003 记录未提交改动与 T02 保护区改动
- [x] T004 建立输出目录 `outputs/_work/repo_governance_realign_20260414_142216/`

## Phase 1 - SpecKit

- [x] T010 创建 `specs/002-repo-governance-realignment/spec.md`
- [x] T011 创建 `specs/002-repo-governance-realignment/plan.md`
- [x] T012 创建 `specs/002-repo-governance-realignment/tasks.md`

## Phase 2A - AGENTS 与阅读链路修复

- [ ] T020 修正 `AGENTS.md`，补强冲突停机、排除路径、入口治理、结构债、范围保护
- [ ] T021 修正 `docs/doc-governance/README.md`，恢复治理主入口定位并消除循环
- [ ] T022 修正 `docs/repository-metadata/README.md`，改为按需结构入口而非并列 day-0 主入口

## Phase 2B - 项目级 source-of-truth 一致化

- [ ] T030 修正 `SPEC.md` 的项目阶段和模块口径
- [ ] T031 修正 `docs/PROJECT_BRIEF.md` 的项目级摘要口径
- [ ] T032 修正 `docs/architecture/*` 中“无正式模块 / 禁止具体模块”旧叙述
- [ ] T033 修正 `docs/doc-governance/module-lifecycle.md`
- [ ] T034 修正 `docs/doc-governance/current-module-inventory.md`
- [ ] T035 修正 `docs/doc-governance/current-doc-inventory.md`
- [ ] T036 修正 `docs/doc-governance/module-doc-status.csv`

## Phase 2C - 模板与非 T02 模块修复

- [ ] T040 修正 `modules/_template/README.md` 与 `modules/_template/INTERFACE_CONTRACT.md` 的旧入口示意
- [ ] T041 修正 `modules/_template/AGENTS.md`，明确 day-0 文档最少集与职责边界
- [ ] T042 修正 `modules/t00_utility_toolbox/*`，收敛为“工具集合模块 / 非业务生产模块”口径
- [ ] T043 修正 `modules/t01_data_preprocess/*`，对齐模板职责边界与仓库入口方式

## Phase 2D - 元数据与入口注册修复

- [ ] T050 修正 `repository-structure-metadata.md`
- [ ] T051 修正 `code-boundaries-and-entrypoints.md`
- [ ] T052 依据真实 `cli.py` / `scripts/` 刷新 `entrypoint-registry.md`
- [ ] T053 刷新 `code-size-audit.md`

## Phase 3 - 验证与审计

- [ ] T060 检查修改文件是否全部在允许路径内
- [ ] T061 检查禁止路径是否无改动
- [ ] T062 运行 `python -m rcsd_topo_poc --help`
- [ ] T063 运行 `python -m rcsd_topo_poc doctor`
- [ ] T064 生成 `EXEC_SUMMARY.md`
- [ ] T065 生成 `FILE_CHANGE_MAP.md`
- [ ] T066 生成 `VALIDATION_REPORT.md`
- [ ] T067 生成 `OPEN_DECISIONS.md`
