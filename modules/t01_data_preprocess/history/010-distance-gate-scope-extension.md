# 010 - Distance Gate Scope Extension

## 为什么要把 50m gate 从 Step2 扩展到 Step4 / Step5
- 当前模块的 Step4 / Step5 仍在做双向道路路段构建。
- 只在 Step2 生效 50m gate，会出现：
  - Step2 已拒绝的过宽双线闭环，在 Step4 / Step5 又被重新接纳
  - Step2 已挡住的远侧旁路，在 Step4 / Step5 又被重新吸入
- 因此两个 `50m` gate 必须跟着“双向构段内核”一起生效，而不是停留在 Step2 局部。

## 当前作用范围
- 适用：
  - `Step2`
  - `Step4`
  - `Step5A`
  - `Step5B`
  - `Step5C`
- 不适用：
  - working layer 初始化
  - 环岛预处理
  - generic Node / Road refresh
  - 单向 Segment
  - Step6（当前未纳入本轮）

## 当前接入方式
- Step2 直接实现 trunk / side component 的距离 gate。
- Step4 / Step5 不再各自实现一套新 gate，而是复用共享的 `run_step2_segment_poc` 双向构段内核。
- 因此：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
  在 Step2 / Step4 / Step5 使用同一参数源。

## 当前已接入阶段
- `Step2`：已接入 dual gate 与 side gate
- `Step4`：通过共享 Step2 kernel 已接入 dual gate 与 side gate
- `Step5A`：通过共享 Step2 kernel 已接入 dual gate 与 side gate
- `Step5B`：通过共享 Step2 kernel 已接入 dual gate 与 side gate
- `Step5C`：通过共享 Step2 kernel 已接入 dual gate 与 side gate

## 当前证明方式
- 代码路径：
  - `Step4` 调用 `run_step2_segment_poc`
  - `Step5A / Step5B / Step5C` 调用 `run_step2_segment_poc`
- 审计输出：
  - 各阶段 `segment_summary.json` 都携带
    - `dual_carriageway_separation_gate_limit_m`
    - `side_access_distance_gate_limit_m`
  - official runner 额外写出 `distance_gate_scope_check.json`

## 本轮未扩展内容
- 不新增新的距离阈值
- 不把 gate 扩到单向 Segment
- 不引入新的环岛特例 gate
