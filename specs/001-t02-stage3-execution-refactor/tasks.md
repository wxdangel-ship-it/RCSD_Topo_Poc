# Tasks: T02 Stage3 Execution-Layer Refactor

## Phase 0 - Baseline Freeze

- [x] T001 冻结 `round_15` 为“结构未完成”基线
- [x] T002 停止继续围绕 `724123 / 769081 / 851884` 直接追加 late-pass patch
- [x] T003 建立 spec-kit 分支 `001-t02-stage3-execution-refactor`

## Phase 1 - Planning Artifacts

- [x] T010 产出 `spec.md`
- [x] T011 产出 `plan.md`
- [x] T012 产出 `research.md`
- [x] T013 产出 `data-model.md`
- [x] T014 产出 `quickstart.md`
- [x] T015 产出 `contracts/stage3-step-boundaries.md`
- [x] T016 收集 PM / 架构 / QA / 测试 / 目视审查 多 Agent 计划输入

## Phase 2 - Contract Extraction

- [x] T020 新增 `stage3_execution_contract.py`
- [x] T021 新增 `stage3_audit_assembler.py`
- [x] T022 在 `virtual_intersection_poc.py` 中接入 `Step7Result` 与 `Stage3AuditRecord` 的 legacy bridge
- [x] T023 给 `status.json` 增加 `stage3_execution_contract_version / step7_result / stage3_audit_record`
- [x] T024 为 Step3~6 增补更原生的 establish flags 与 decision basis
- [x] T025 提炼 `Stage3Context` 实例化入口，减少主流程直接拼接上下文

## Phase 3 - Step7 Extraction

- [x] T030 提取 Step7 输入对象，收拢 `_effect_success_acceptance()` 的参数矩阵
- [x] T031 提取 Step7 唯一终裁封装，禁止 Step7 之后继续改几何
- [x] T032 将 `root_cause_layer / root_cause_type / visual_review_class` 的导出切换为 step-result 优先
- [x] T033 为 Step7 增加结构验收测试：唯一终裁、后置不反写

## Phase 4 - Step4 / Step5 / Step6 Extraction

- [x] T040 抽取 `Step4RCSemantics` 结果对象与 builder
- [x] T041 抽取 `Step5ForeignModel` 结果对象与 builder
- [x] T042 抽取 `Step6GeometrySolve` 结果对象与 bounded optimizer 分层
- [x] T043 将 selected-node hard/soft 边界上收到 Step4/5，不再由 late pass 决定
- [x] T044 将 `late_*cleanup* / late_*trim*` 降级为 bounded optimizer 或删除

## Phase 5 - Orchestrator Shrink

- [x] T050 将 `virtual_intersection_poc.py` 缩回 orchestrator
- [x] T051 引入 `stage3_context_builder.py`
- [x] T052 引入 `stage3_step3_legal_space.py`
- [x] T053 引入 `stage3_step4_rc_semantics.py`
- [x] T054 引入 `stage3_step5_foreign_model.py`
- [x] T055 引入 `stage3_step6_polygon_solver.py`
- [x] T056 引入 `stage3_step7_acceptance.py`
- [x] T057 引入 `stage3_audit_assembler.py` 的结构结果装配优先路径

## Phase 6 - Structural Acceptance

- [x] T060 QA 结构验收：Step3~7 结果对象齐全
- [x] T061 QA 结构验收：Step7 为唯一终裁
- [x] T062 QA 结构验收：审计链不再靠字符串推断
- [x] T063 QA 结构验收：无新增承担主语义的 late pass

## Phase 7 - Regression Reentry

- [ ] T070 恢复焦点回归：保护锚点不回退
- [ ] T071 恢复 `Anchor 61` 正常准出正确性回归
- [ ] T072 恢复 `Anchor 61` 目视分类正确性回归
- [ ] T073 重新进入 `V4` 优化
- [ ] T074 单列恢复 `520394575` 工作流
