# 02 约束

## 业务约束

- 范围限定为 P01-A1 / P01-A2 / P01-Final。
- P01-A3 正式跨源 Movement 空间、P01-B、禁行迁移与通行能力最终裁决不由本模块实现。
- `InitialArm` 保留原始 trace 终端归并事实；`FinalArm` 默认等同 `InitialArm`，也可在 `LocalArmCandidate` 完整覆盖碎片化 InitialArm 时采用局部趋势兜底聚合。
- 右转专用道 / 渠化右转只有字段明确可识别时才排除。
- 特殊转向使用 `formway` bit 运算：bit7 = 提前右转，bit8 = 提前左转。
- `kind` 可参与追溯停止判断；T 型判断必须结合拓扑、追溯方向与 Arm 结构，不能由 `kind` 单独裁决。
- `grade / grade_2` 不进入 P01 主规则。
- A2 读取 A1 run root，不重新实现 A1，不自动修复 A1 输出。
- A2 不能仅凭几何最近输出 high confidence 配准。
- A2 不自动拆分 over-merged Arm，只输出 ArmBuildFeedback。
- RoadNextRoad 在 A1 ArmMovement 阶段只表达 allowed evidence；缺失不等于禁止。
- RoadNextRoad 在 P01-Final 生成阶段先抽象为源侧 Arm 级通行规则；源侧规则缺失或判断不通时不生成 F-RCSD RoadNextRoad。
- `turnType / turntype` 只作为 raw audit 字段，不得用于 `movement_type` 判定。
- P01-Final 不得把 `F-RCSD:Road.Source + CRS 归一化 rounded exact geometry` 精确源 Road 映射作为生成前提；该映射只作为 audit / confidence evidence，且不得用空间接近或最近邻替代。
- F-RCSD Arm 可以混源；`Source` 只能在 Road 级解释。
- `full_allowed` 必须生成到目标 Arm 所有退出 Road；主干道路 / 平行支路部分目标覆盖必须进入 `data_error_partial_target_coverage`，advance-left 与 uturn 的明确特殊范围除外。
- 混源进入 Arm 规则源选择顺序为 SWSD 结构匹配、RCSD 结构匹配、SWSD basic rule 兜底。

## 工程约束

- 文档在 `modules/p01_arm_build/`。
- 实现在 `src/rcsd_topo_poc/modules/p01_arm_build/`。
- 测试在 `tests/modules/p01_arm_build/`。
- 仓库不提供 P01 repo 官方 CLI、`scripts/` 常驻命令、Makefile 目标、模块 `__main__.py` 或模块 `run.py`。
- 源码文件写入前必须做字节数自检。

## GIS / 拓扑约束

- CRS 必须写入 preflight 与输出审计。
- trace 必须保持拓扑连续，不做 silent fix。
- 几何只用于 review、辅助证据和 CRS-normalized rounded exact source mapping 审计，不用于右转反推、Arm 主构建或单独 high confidence 配准。
- 输出必须记录输入、参数、run id、case id、trace、decision、ArmSourceProfile、SourceArmPassRule、source mapping、generation audit 与 issue。
- A2 必须记录 candidate score、selection reason、LogicalArmGroup、source_extra 与 feedback。
