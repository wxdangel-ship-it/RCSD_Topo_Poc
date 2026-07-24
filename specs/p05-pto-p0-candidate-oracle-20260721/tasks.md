# Tasks: P05-PTO-P0

## Specify / Plan

- [x] T001 [产品] 冻结 P0 目标、51 Case 范围、排除项、非生产边界和两道门禁。
- [x] T002 [架构] 冻结候选/label 分层、策略 replay lineage、R2 edit 复用与通用约束白名单。
- [x] T003 [测试/QA] 冻结精确计数、F1/拓扑、最优性、确定性、资源与 GIS 验收。
- [x] T004 [架构] 同步项目/P05 source-of-truth 和 callable 接口。

## Implement

- [x] T005 [测试] 编写 lineage/leakage/exclusion 破坏测试。
- [x] T006 [研发] 实现策略 replay descriptor 与候选 lineage 验证。
- [x] T007 [测试] 编写 candidate union/dedupe/action/pointer 测试。
- [x] T008 [研发] 实现 base+strategy 候选构建与不可变 candidate run。
- [x] T009 [测试] 编写 Oracle cost、最优证书与通用约束 hard-failure 测试。
- [x] T010 [研发] 实现 label-only cost/coverage、exact solver 与 R2 materializer/evaluator adapter。
- [x] T011 [测试] 编写端到端 fixture 与重复运行确定性测试。

## Validate

- [x] T012 [QA] 独立重放登记策略版本并审计 commit/input/output/hash/性能。
- [x] T013 [QA] 对 51 Case 运行 Gate 1 candidate reachability。
- [x] T014 [QA] 对 51 Case 运行 Gate 2 Oracle-cost solve、物化与 M0 evaluator。
- [x] T015 [QA] 第二次运行并核对候选、选择、RoadGraph 与指标 signature。
- [x] T016 [QA] 完成 CRS、拓扑、几何语义、追溯、性能和资源审计。
- [x] T017 [研发] 完成单元/集成/回归测试、依赖、入口、code-size 审计。
- [x] T018 [产品/架构/研发/测试/QA] 形成 validation summary 与 PTO-P1 go/no-go 结论。
