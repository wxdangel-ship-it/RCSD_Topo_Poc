# T06 RCSD Road—Segment 唯一分配任务

## Phase 1：规格与边界

- [x] T001 [产品] 确认普通 Road 唯一归属、特殊内部/连通 Road 可无归属、多归属不是默认业务能力。
- [x] T002 [架构] 区分 `path_corridor_group` 原子事务、carrier 关联与 Road owner。
- [x] T003 [QA] 完成 P02 run08 8 条 Road 的锚点、相对位置、距离、方向拓扑和特殊组逐项审计。
- [x] T004 检查工作区、分支、入口边界与待改源码体量。

## Phase 2：测试先行

- [x] T005 [测试] 增加普通重复 Road 只保留唯一 owner 的测试。
- [x] T006 [测试] 增加特殊路口内部 Road 无 Segment owner 的测试。
- [x] T007 [测试] 增加 connectivity Road 无 Segment owner、relation 独立审计的测试。
- [x] T008 [测试] 增加 final/split Road provenance 单值或空值及多 owner 硬门禁测试。

## Phase 3：实现

- [x] T009 [研发] 扩展 ownership ledger 与特殊路口内部 owner 类型。
- [x] T010 [研发] 实现 final Road/added-road assignment reconciliation。
- [x] T011 [研发] 裁剪 relation 非 owner Road，新增特殊路口 related 字段。
- [x] T012 [研发] 将相同规则接入 surface ownership refresh。
- [x] T013 [架构] 同步 T06 SPEC、architecture 与 INTERFACE_CONTRACT，收紧 path-corridor 多值语义。

## Phase 4：验证与 P02 重跑

- [x] T014 运行 ownership 聚焦测试与 T06 相关回归。
- [x] T015 运行 T06 全模块测试并检查源码体量。
- [x] T016 基于 P02 run08 完整输入生成 run09，不修改 T01/T05/人工关系。
- [x] T017 [QA] 验证 8 条 Road 为 4 唯一、4 无归属、0 多归属。
- [x] T018 [QA] 验证 CRS、方向拓扑、几何、审计、性能和最终多 owner 硬门禁。
- [x] T019 更新 P02 validation report/QGIS 工程与本 SpecKit 验证结论。
