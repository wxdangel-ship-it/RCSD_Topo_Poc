# Tasks: T06 上游化替换计划与问题回流

**Input**: `spec.md`、`plan.md`

## Phase 1: Specification And Contract

- [x] T001 建立 SpecKit 工件 `specs/t06-upstream-replacement-planning-20260615/`
- [x] T002 更新 T06 契约，定义 replacement plan 与 problem registry
- [x] T003 更新 T06 history，记录本轮业务逻辑变更时间线

## Phase 2: Replacement Plan

- [x] T004 在 `schemas.py` 增加 Step2 replacement plan/problem registry stem 与字段
- [x] T005 新增 `replacement_plan.py` 构建标准 replaceable、特殊路口组、path-corridor group 的统一计划行
- [x] T006 在 Step2 closeout 写出 `t06_segment_replacement_plan.*`
- [x] T007 在 Step2 summary 记录 plan 输出路径和计数

## Phase 3: Problem Registry

- [x] T008 在 `replacement_plan.py` 构建 failure/covered/resolved 问题注册行
- [x] T009 在 Step2 closeout 写出 `t06_segment_replacement_problem_registry.*`
- [x] T010 在 Step2 summary 记录 registry 输出路径和问题状态分布

## Phase 4: Step3 Consumption

- [x] T011 扩展 Step3 group helper，从 replacement plan 解析 path-corridor group assignment
- [x] T012 扩展 Step3 主 runner，存在 replacement plan 时优先消费 plan，旧 audit 仅作为兼容 fallback
- [x] T013 Step3 summary 记录 replacement plan source 与 plan 计数

## Phase 5: Tests And Regression

- [x] T014 增加 replacement plan/problem registry 单元测试
- [x] T015 增加 Step3 消费 replacement plan 的回归测试
- [x] T016 执行 T06 单元测试
- [x] T017 执行 T10 4 Case 端到端回归，确认既有成功 Segment 不回退
