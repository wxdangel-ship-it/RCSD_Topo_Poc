# T08 Tool11 Patch 级数据整理任务

## Phase 1 - 产品 / 架构冻结

- [x] T001 确认 Tool11 正式入口、业务文件命名特例和独立实验根授权。
- [x] T002 复核 T08 源事实、入口治理、文件体量和现有 Tool10 发布模式。
- [x] T003 建立产品、架构、研发、测试、QA 五职责 SpecKit 规格。
- [x] T004 冻结 CLI、数据模型、覆盖语义、失败 summary 和验证顺序。

## Phase 2 - 稳定契约

- [x] T005 更新 `modules/t08_preprocess` 的 SPEC、INTERFACE_CONTRACT、README、AGENTS 和架构 02-06。
- [x] T006 在 `docs/repository-metadata/entrypoint-registry.md` 登记唯一 Tool11 脚本。

## Phase 3 - 研发

- [x] T007 写入每个 `.py` 前记录当前字节数。
- [x] T008 实现 `patch_data_organization.py` 的预检、计划、复制、哈希和 summary。
- [x] T009 实现双输出根暂存发布、覆盖保护与回滚。
- [x] T010 在 T08 `__init__.py` 导出 Tool11 callable/artifacts/error/default experiment IDs。
- [x] T011 实现 `scripts/t08_tool11_patch_data_organization.py` 参数、进度和退出码。

## Phase 4 - 测试 / QA

- [x] T012 增加 Tool11 合成测试，覆盖全量目录、FRCSD 白名单和默认 6 Patch 实验集。
- [x] T013 覆盖缺失项聚合、符号链接/特殊文件/边界、冲突保护、覆盖替换和失败不发布。
- [x] T014 覆盖 CLI stdout/stderr、退出码、summary 命名和参数化路径。
- [x] T015 运行 Tool11 聚焦测试与 T08 全量测试。
- [x] T016 验证 CRS、拓扑、几何语义、审计和性能五项 QA。

## Phase 5 - 交付审计

- [x] T017 运行 `git diff --check`、入口一致性和变更文件体量检查。
- [x] T018 逐项核对 FR-001 至 FR-022、SC-001 至 SC-006。
- [x] T019 更新任务勾选和 validation report，区分已修改、已验证、待确认。
