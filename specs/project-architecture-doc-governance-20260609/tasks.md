# Tasks: Project Architecture Documentation Governance

## Phase 1 - Scope

- [x] T001 确认当前分支不是 `main`
- [x] T002 审计 `docs/architecture/` 当前文件结构
- [x] T003 审计 `docs/architecture/` 与 `docs/doc-governance/`、`docs/repository-metadata/` 的重复耦合
- [x] T004 创建本轮 SpecKit 工件

## Phase 2 - Architecture Restructure

- [x] T010 重写 `docs/architecture/01-introduction-and-goals.md`
- [x] T011 新建 `docs/architecture/02-data-and-domain-model.md`
- [x] T012 新建 `docs/architecture/03-solution-strategy.md`
- [x] T013 新建 `docs/architecture/04-evidence-and-audit.md`
- [x] T014 新建 `docs/architecture/05-quality-requirements.md`
- [x] T015 新建 `docs/architecture/06-risks-and-technical-debt.md`
- [x] T016 删除旧 architecture 低价值拆分与空壳 ADR 目录

## Phase 3 - Repository Documentation Cleanup

- [x] T020 将旧 `docs/ARTIFACT_PROTOCOL.md` 归档为历史参考
- [x] T021 收编 `docs/metadata-cleanup/` 与 `docs/archive/nonstandard/`
- [x] T022 同步 repo root `README.md`
- [x] T023 同步 `SPEC.md` 与 `docs/PROJECT_BRIEF.md`
- [x] T024 同步 `docs/doc-governance/README.md`
- [x] T025 同步 `docs/doc-governance/current-doc-inventory.md`
- [x] T026 同步 `docs/repository-metadata/repository-structure-metadata.md`
- [x] T027 同步 `docs/repository-metadata/entrypoint-registry.md` 的历史文本协议描述口径

## Phase 4 - Validation

- [x] T030 运行 `git diff --check`
- [x] T031 验证本轮不触碰 `modules/**`、`src/**`、`scripts/**`、`tests/**`
- [x] T032 检索旧 architecture 文件名、旧协议和被收编目录残留引用
- [x] T033 抽样读取目标文档结构和关键索引
