# Feature Specification: T10 FRCSD 质量检查专用流水线

**Feature Branch**: `codex/003-t12-frcsd-quality-audit`
**Created**: 2026-07-18
**Status**: Implemented and locally validated
**Input**: 在 T10 内新增面向原始 1V1 FRCSD 质量检查的完整独立流水线，顺序固定为 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T11 -> T12 -> T09`。

## User Scenarios & Testing

### User Story 1 - 一条命令运行完整 FRCSD 质检链

作为内网质量工程师，我希望使用一个独立脚本运行从 SWSD 预处理到 FRCSD 质量审计和 restriction 恢复的完整链路，不必手工拼接 T10 各阶段。

**Acceptance**:

1. 新入口固定运行 `T01/T07/T03/T04/T05/T06/T11/T12/T09`，不运行 T08。
2. T11 完成后才运行 T12，T12 完成后才运行 T09。
3. T12 检查调用方显式提供的原始 1V1 FRCSD，不检查 T06 Step3 输出。

### User Story 2 - 保持既有 T10/T06 业务效果

作为现有流程维护者，我希望专用质检链不会改变默认 T10 v1，也不会改变 T06 到 T09 的正式数据 handoff。

**Acceptance**:

1. 不启用专用入口时，默认 T10 仍为 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T11 -> T09`。
2. 专用链中 T09 继续消费 T06 F-RCSD Road/Node/relation；T11/T12 均为 audit-only。
3. T06 源码、接口、参数和替换结果不修改。

## Functional Requirements

- **FR-001**: 必须新增正式入口 `scripts/t10_run_frcsd_quality_pipeline.sh`。
- **FR-002**: 专用入口的有效 stage 顺序必须是 `t01,t07_step12,t03,t04,t05,t06_step12,t06_step3,t11,t12,t09`。
- **FR-003**: 专用入口必须复用 `t10_run_innernet_full_pipeline.sh`，不得复制 T01~T12 模块算法或另建第二套编排实现。
- **FR-004**: 专用入口必须强制 `RUN_T08=0`、`RUN_T12=1`；与专用语义冲突的显式环境变量必须前置阻断。
- **FR-005**: 必须显式要求 `FRCSD_1V1_ROADS_PATH` 与 `FRCSD_1V1_NODES_PATH`，不得借用 `RCSDROAD_PATH/RCSDNODE_PATH`。
- **FR-006**: T12 必须位于 T11 后、T09 前；T12 不得消费或改写 T11 业务结果。
- **FR-007**: T09 必须继续消费 T06 Step3 F-RCSD 输出，不得改为消费 T12 输出。
- **FR-008**: 默认 T10 v1 stage order、chain metadata 和现有入口默认值必须保持不变。
- **FR-009**: 新入口必须沿用 full runner 的 run root、manifest、summary、resume、失败退出和稀疏进度能力，并在启动日志中标记专用 profile 和完整链路。
- **FR-010**: 新入口、T10/T12 合同、项目源事实、生命周期和入口登记必须同轮一致。
- **FR-011**: GIS QA 必须继续显式记录 CRS、拓扑、几何语义、审计追溯、性能和 `silent_fix=false`。
- **FR-012**: 不得声称内网完整数据已运行，除非实际获得执行能力。
- **FR-013**: 裁剪 Case 验收必须允许显式传入 `T12_CASE_MANIFEST` 做边界排除；全图运行必须留空，不得推断或静默生成边界。

## Success Criteria

- **SC-001**: 自动化断言专用 Case/full 顺序均为 `T06 -> T11 -> T12 -> T09`。
- **SC-002**: 默认 T10 顺序中不存在 T12，既有 T10 测试全部通过。
- **SC-003**: `1026960` 专用链运行通过，T12 仍输出 35/10/25/0。
- **SC-004**: T06/T11/T09 业务工件与既有兼容运行保持语义一致。
- **SC-005**: 新脚本 shell syntax、前置阻断、环境转发、入口登记和文件体量审计全部通过。
- **SC-006**: `1026960` 裁剪验收显式传入 Case manifest 后，`crop_edge_excluded_count=19`，不得把这些边界对象发布为质量问题。

## Non-goals

- 不修改 T06、T11、T12、T09 的业务算法。
- 不把 T12 结果作为 T09 输入。
- 不把 T08 纳入本专用链。
- 不自动修复原始 1V1 FRCSD。
