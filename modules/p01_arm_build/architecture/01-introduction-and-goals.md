# 01 引言与目标

## 状态

- 当前状态：P01-A 模块源事实
- 模块：`p01_arm_build`
- 阶段：`P01-A / Arm 构建`

## 目标

本模块为 P01 POC 验证链路提供 Arm 构建基础：在已知 SWSD / RCSD / F-RCSD 对应路口 ID 的前提下，分别对三套数据构建当前语义路口 Arm，并产出可自动检查、可人工目视审查、可追溯的审计结果。

## 成功标准

- 多组路口输入可批处理。
- 三套数据各自输出 Arm 构建结果。
- 每条 seed road 有归属或 issue。
- through 判断输出业务状态。
- review PNG / compare PNG / review GPKG 可用于人工判断。
- summary / review index 可支持批量筛查。
