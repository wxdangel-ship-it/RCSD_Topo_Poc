# Tasks：T12 direction-strict portal

## Phase 1：规格与证据

- [x] T001 建立 spec/plan/tasks，覆盖产品、架构、研发、测试、QA。
- [x] T002 复核现有实现与模块源事实，定位 portal role 未参与资格过滤。
- [ ] T003 获取当前版本目标 Road 的 endpoint/Node alias/portal 证据，定位 `5885111744069971` 未进入正向链的唯一阶段。

## Phase 2：测试与实现

- [x] T004 增加 direction-role portal 单元测试。
- [x] T005 按 outgoing/incoming node 集合修复 raw portal 资格。
- [x] T006 增加正反向平行 Road carrier 回归测试。
- [x] T007 增加方向覆盖根因审计，不使用对象 ID。

## Phase 3：正式源事实

- [x] T008 更新 T12 module SPEC/architecture/contract，明确 direction-role portal 和 undirected 仅诊断。

## Phase 4：回归与 QA

- [x] T009 运行 T12 与 T10+T12 受影响测试。
- [x] T010 回归 `1026960` 冻结计数和集合。
- [x] T011 扫描生产对象 ID、检查文件体量、格式和 `git diff --check`。
- [x] T012 汇总 CRS、拓扑、几何、追溯与性能证据。

## Phase 5：交付

- [x] T013 形成已修改、已验证、待确认三档说明。
