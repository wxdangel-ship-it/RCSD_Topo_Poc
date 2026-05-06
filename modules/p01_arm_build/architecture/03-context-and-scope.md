# 03 上下文与范围

## 上下文

P01 的最终目标是为 F-RCSD 重建路口级 movement 通行能力。P01-A 只解决第一层结构基础：分别在 SWSD、RCSD、F-RCSD 中构建当前路口 Arm。

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

## 当前范围外

- 三套数据之间的 Arm 配准。
- Movement 建模。
- 禁行信息迁移。
- F-RCSD 通行能力裁决。
- 复杂兜底合并。
- Lane 级能力。
