# 任务清单

## Phase 1：Specify / Plan / Tasks

- [x] T001 固化三组七类、T07 Step2 来源和兼容边界。
- [x] T002 覆盖产品、架构、研发、测试、QA 五类职责视角。
- [x] T003 完成现状研究、数据模型、输出合同和实施计划。

## Phase 2：Tests First

- [x] T004 增加 taxonomy 七类、状态映射和旧类型兼容测试。
- [x] T005 增加 T07 Step2 fail1/fail2、fail2 优先与证据一致性测试。
- [x] T006 增加 Step3 cardinality 不导入和旧参数定位兼容测试。
- [x] T007 更新 T10 Case/full handoff 测试，证明不依赖 Step3。

## Phase 3：Implement

- [x] T008 实现集中式 taxonomy 与 Segment 发布迁移。
- [x] T009 实现 T07 Step2 source loader 和强一致性审计。
- [x] T010 实现 J01-J04 新分类、统一字段和 summary 统计。
- [x] T011 扩展 T12 既有 CLI/callable 与 T10 handoff。
- [x] T012 更新 T12/T10 模块源事实、项目事实、入口登记和体量台账。
- [x] T013 更新 T12-only 内网脚本，不新增入口。

## Phase 4：Validate

- [x] T014 跑 T12 与 T10/T12 自动测试、compile 和 shell syntax。
- [x] T015 验证 `1026960` Segment `63/10/53/0` 及 confirmed ID 集合。
- [x] T016 验证 T03 4 正 16 负和 J01/J02 分布。
- [x] T017 验证 `764857`、`26981804` 在所有 Junction 结果为 0。
- [x] T018 验证 Step2 `O_J03=E_J03`、`O_J04=E_J04` 和 Step3 导入数 0。
- [x] T019 生成/刷新 QGIS 工程并完成 CRS、拓扑、几何、追溯、性能五项检查。
- [x] T020 完成双跑稳定性、性能、体量、diff 和工作树终检。
- [x] T021 提交、推送、合并主干并核验远端指针。
