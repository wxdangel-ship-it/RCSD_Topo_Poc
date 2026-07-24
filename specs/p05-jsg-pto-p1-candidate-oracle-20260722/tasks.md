# P05-JSG-PTO-P1 任务清单

## T001 源事实与合同

- [x] 统一 P05 当前阶段和历史路线状态。
- [x] 建立 SpecKit、数据模型和输出合同。
- [x] 同步项目/P05 source-of-truth 与接口 callable。

## T002 Candidate model 与 EvidenceGraph

- [x] 实现 candidate/config/canonical signature。
- [x] 实现 truth-free input loader 和 manifest/hash gate。
- [x] 实现 Case-local EvidenceGraph。

## T003 PTO-A 候选

- [x] 生成 Junction/Segment/Relation/Movement/Connector/Review 候选。
- [x] 实现有限分解、去重和 dependency。
- [x] 输出 candidate/group/lineage/case index。

## T004 PTO-A/PTO-B Oracle

- [x] candidate 冻结后加载 P0 truth。
- [x] 实现 PTO-A Oracle cost、solve 和 certificate。
- [x] 复用 RoadGraph candidate/solver 完成 PTO-B。
- [x] 验证 Unit carrier/access feasibility。

## T005 Compiler 与评价

- [x] 编译选中 JSG/R2 IR 到 Road/Node。
- [x] 使用 P0/M0 evaluator 完成 hard gate。

## T006 测试

- [x] 单元、泄漏、破坏、infeasible 和确定性测试。
- [x] 完整 P05 回归测试。

## T007 正式验收

- [x] candidate run A/B。
- [x] solve run A/B。
- [x] signature、GIS、性能与证据审计。
- [x] validation summary 和最终 go/no-go。
