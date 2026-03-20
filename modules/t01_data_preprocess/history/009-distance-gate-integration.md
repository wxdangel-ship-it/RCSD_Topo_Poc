# 009 - Distance Gate Integration

## 背景
- 当前模块只处理双向道路路段构建。
- 仅靠拓扑闭合会把“上下行过远的伪双线路段”或“远离主路的旁路”也吸入合法结果。
- 因此本轮新增两个显式距离 gate，用于补强双向道路语义，但不替代既有 Step2 强规则 A/B/C。

## Gate 1：上下行最大垂距 50m

### 目的
- 防止 A→B 与 B→A 虽然拓扑上可闭合，但上下行空间分离过大时仍被误判为合法双线路段。

### 常量
- `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`

### 作用阶段
- Step2 trunk / 最小闭环 validation
- 后续复用 Step2 trunk 内核的 residual graph 轮次

### 当前实现口径
- 对 trunk candidate 的 forward path 与 reverse path 分别构造 polyline geometry
- 在 `EPSG:3857` 米制坐标下，计算两方向 polyline 的最大最近距离
- 若该值大于 `50m`，则拒绝该 candidate

### 审计表现
- reject reason：`dual_carriageway_separation_exceeded`
- support info：
  - `dual_carriageway_separation_gate_limit_m`
  - `dual_carriageway_max_separation_m`
- summary：
  - `dual_carriageway_separation_reject_count`

## Gate 2：侧向旁路最大距离 50m

### 目的
- 防止 side component / 旁路虽然拓扑上可挂接 trunk，但空间上已经远离主路时仍被吸入 `segment_body`。

### 常量
- `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`

### 作用阶段
- Step2 side component / segment 收敛阶段

### 当前实现口径
- 对 trunk geometry 与每个 non-trunk component geometry 计算最大最近距离
- 若该值大于 `50m`，则该 component 不再吸入 `segment_body`
- 改为进入 `step3_residual`

### 审计表现
- component decision reason：`side_access_distance_exceeded`
- component / residual info：
  - `side_access_distance_m`
  - `side_access_gate_passed`
- summary：
  - `side_access_distance_block_count`

## 与既有规则的关系
- 两个 distance gate 是新增保护，不覆盖也不替代：
  - Step2 强规则 A
  - Step2 强规则 B
  - Step2 强规则 C
- 既有拓扑 / branch / 历史边界规则仍然先执行；distance gate 只处理空间约束补强。

## 已知局限
- 当前“最大最近距离”实现优先追求清晰、稳定、可解释，不是更复杂的车道级几何理论。
- 对极端复杂 geometry，后续仍可继续细化：
  - 更精确的采样策略
  - 更稳定的 lane corridor 度量
  - 更细的 side component 方向区分
- 本轮先保证：
  - 阈值集中定义
  - 审计输出可追溯
  - 与现有 accepted baseline 语义兼容
