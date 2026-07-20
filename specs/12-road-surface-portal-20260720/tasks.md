# Tasks：T12 Road-surface portal

## Phase 1：规格与原始证据

- [x] T001 建立 spec/research/plan/tasks，覆盖产品、架构、研发、测试、QA。
- [x] T002 审计三条目标 Segment 的 T07 锚定、方向 Road 链、标准面和距离指标。
- [x] T003 确认 `1026960` 当前 35/10/25/0 与 10 条冻结集合。

## Phase 2：正式口径

- [x] T004 更新项目级 T12 质量规则与 T12 模块源事实。
- [x] T005 更新 T12 输出契约，明确 distance audit-only 与 Road-surface evidence。

## Phase 3：测试与实现

- [x] T006 编写 surface intersection、one-hop frontier、距离审计及拒绝边界测试。
- [x] T007 实现通用 T07 Road-surface portal carrier，不使用对象 ID。
- [x] T008 将新 evidence 接入 candidate、decision 和正式输出。

## Phase 4：回归与 QA

- [x] T009 重放三条目标 Segment，核对 Road 序列和 false-positive 排除。
- [x] T010 原始数据回归 `1026960` 冻结计数和集合。
- [x] T011 运行测试、源码 ID 扫描、体量审计和 `git diff --check`。
- [x] T012 汇总 CRS、拓扑、几何语义、追溯与性能证据。

## Phase 5：交付

- [x] T013 形成已修改、已验证、待确认三档交付说明。
