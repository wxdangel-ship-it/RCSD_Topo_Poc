# 03 上下文与范围

## 上下文

P01 的最终目标是为 F-RCSD 重建路口级 movement 通行能力。P01-A 解决 Movement 前的结构基础：A1 分别在 SWSD、RCSD、F-RCSD 中构建当前路口 Arm；A2 在 A1 输出之上构建跨三源 LogicalArmGroup。

## 当前范围

- 基础数据读取。
- 多 junction group 批处理。
- 语义路口组装。
- seed road 识别。
- 右转专用道 / 渠化右转字段排除。
- Arm trace。
- InitialArm / FinalArm 输出。
- through decision audit。
- issue report。
- review PNG / compare PNG / review GPKG。
- summary / review index。
- A2 读取 A1 run root。
- A2 构建 ArmProfile、candidate edge、RawArmAlignment、LogicalArmGroup、ArmBuildFeedback、source_extra。
- A2 输出配准 review PNG / compare PNG / review GPKG / summary / review index。

## 当前范围外

- Movement 建模。
- 禁行信息迁移。
- F-RCSD 通行能力裁决。
- 复杂兜底合并。
- Lane 级能力。
