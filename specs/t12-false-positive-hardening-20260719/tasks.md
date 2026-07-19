# Tasks：T12 误判审计与高置信规则收敛

## Phase 1：规格与现状

- [x] T001 建立 spec/plan/tasks，覆盖产品、架构、研发、测试、QA。
- [x] T002 核对 11 个 Segment 包完整性、CRS、200m 范围和拓扑依赖摘要。
- [x] T003 核对正式 T10 Case 重建入口、T12 decision 实现和 `1026960` 冻结基线。

## Phase 2：数据端到端审计

- [x] T004 逐包重建 T01→T07→T03→T04→T05→T06→T12；损坏或边界不足项标记 `not_assessable`。
- [x] T005 导出 11 个 Segment 的 required direction、anchor/portal、raw/canonical carrier 与几何阈值证据。
- [x] T006 逐条形成真实问题/误判/不可判断结论及原始数据依据。

## Phase 3：通用修复

- [x] T007 汇总误判共因，确认是否属于实现缺陷或正式规则缺口。
- [x] T008 写失败测试并完成源码体量前置检查。
- [x] T009 实现最小可泛化修复及输出审计扩展，不使用对象 ID。

## Phase 4：回归与 QA

- [x] T010 回归 11 个 Segment，验证误判消除且真实问题不被掩盖。
- [x] T011 从原始数据回归 `1026960` 的 35/10/25/0 和冻结集合。
- [x] T012 运行 T12/T10 测试、源码 ID 扫描、体量审计和 `git diff --check`。
- [x] T013 汇总 CRS、拓扑、几何语义、审计追溯和性能证据。

## Phase 5：交付

- [x] T014 输出逐 Segment 结论、误判根因、修改文件、验证结果与待确认边界。
