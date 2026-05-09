# 02 约束

## 业务约束

- 只做 P01-A1 / P01-A2 / P01-Final，不扩展 P01-B。
- A1 允许输出 ArmMovement 候选与 RoadNextRoad evidence 审计；P01-Final 允许生成最终 F-RCSD RoadNextRoad。
- 不实现 P01-A3 正式跨源 Movement 空间、禁行迁移或通行能力裁决。
- `InitialArm` 保留原始 trace 终端归并；`FinalArm` 默认等于 `InitialArm`，但允许在 trace 过度切碎且 `LocalArmCandidate` 完整覆盖时采用局部趋势兜底聚合。
- 右转专用道 / 渠化右转只有字段明确可识别时才排除。
- `kind` 参与追溯停止主口径：非 `4` 类型原则继续，`2048` 按 T 型横/竖裁决，`4` 先评估 T 型特征后再决定停止或继续。
- `grade / grade_2` 不进入 Arm 构建主规则。
- A2 读取 A1 run root，不重新实现 A1，不自动修复 A1 输出。
- A2 不能仅凭几何最近输出 high confidence 配准。
- A2 不自动拆分 over-merged Arm，只输出 ArmBuildFeedback。
- P01-Final 只能用 `F-RCSD:Road.Source + 几何完全一致` 做源 Road 强匹配，不得用空间接近替代。
- `turnType / turntype` 只作为 raw audit 字段，不得用于 movement_type 判定。

## 工程约束

- 文档在 `modules/p01_arm_build/`。
- 实现在 `src/rcsd_topo_poc/modules/p01_arm_build/`。
- 测试在 `tests/modules/p01_arm_build/`。
- 本轮不新增正式 CLI、scripts、Makefile 目标、模块 `__main__.py` 或模块 `run.py`。
- 源码文件写入前必须做字节数自检。

## GIS / 拓扑约束

- CRS 必须写入 preflight 与输出审计。
- trace 必须保持拓扑连续，不做 silent fix。
- 几何只用于 review 和辅助定位，不用于右转反推、Arm 主构建或单独 high confidence 配准。
- 输出必须记录输入、参数、run id、case id、trace、decision、issue。
- A2 必须记录 candidate score、selection reason、LogicalArmGroup、source_extra 与 feedback。
