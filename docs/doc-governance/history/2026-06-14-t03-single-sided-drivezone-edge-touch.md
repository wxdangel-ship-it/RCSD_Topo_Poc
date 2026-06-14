# 2026-06-14 T03 single-sided DriveZone edge-touch 履历

## 变更背景

T10 Case `1885118` 中，SWSD Segment `513920625_608228278` 的上游路口 `513920625` 未能被 T03 构建为可被 T05/T06 消费的虚拟路口面。审计显示该 case 为 `single_sided_t_mouth`，Step3 原状态为 `not_established / allowed_space_empty`，后续 Step4/Step6/Step7 只能以 `association_step3_not_established` 拒绝。

## 根因

原始数据量化后，两个 SWSD 目标节点到 DriveZone 边界距离约 `1.02m`，两条纵向 selected road 在 DriveZone 内的长度占比约 `99.47%`，且近邻 RCSD 语义桥节点位于 DriveZone 内。T03 Step3 旧逻辑使用固定 `1.0m` target reference buffer 判断候选组件是否触达目标，导致已经被 DriveZone 正确裁剪且位于 DriveZone 内的候选组件因 `~0.02m` 的边界差被 `_component_touching_target` 丢弃。

这不是 T06 Segment 构建问题，也不是降低 retained RCSDRoad overlap 阈值的问题；根因在 T03 Step3 对单侧 T 口的 DriveZone 边界微偏移缺少可审计处理。

## 业务逻辑变更

1. T03 Step3 新增 `single_sided_t_mouth` 目标触达容差：
   - 默认组件触达容差仍为 `1.0m`。
   - 仅当目标节点到 DriveZone 的最大距离不超过小容差，且每个目标节点均有 incident road 进入 DriveZone 并提供支撑时，组件触达容差提升到 `1.5m`。
   - 该规则只影响“候选组件是否触达目标”的判断，不允许最终 `allowed_space` 越过 DriveZone。
2. Step3 status/audit 新增 `target_edge_touch_*` 证据字段：
   - `target_edge_touch_enabled`
   - `target_edge_touch_reason`
   - `target_edge_touch_tolerance_m`
   - `target_drivezone_distances_m`

## 复测结论

单元复测：

- `tests/modules/t03_virtual_junction_anchor/test_step3_single_sided_two_node_bridge.py`
- `tests/modules/t03_virtual_junction_anchor/test_step3_rule_d_stays_inside_drivezone.py`
- `tests/modules/t03_virtual_junction_anchor/test_step3_case_584141_regression.py`
- `tests/modules/t03_virtual_junction_anchor/test_step3_case_584253_regression.py`

结果：`5 passed`。

Case `1885118` 重跑到 T06 Step3 后：

- `513920625` 的 T03 Step3 由 `not_established / allowed_space_empty` 变为 `established / step3_established`。
- `allowed_area_m2=1079.330986`，`allowed_outside_drivezone_area_m2=0.0`，`drivezone_containment_passed=true`。
- T03 Step7 由 rejected 变为 accepted，`association_class=B`，`reason=step7_accepted_after_support_only_convergence`。

## 后续发现

`513920625_608228278` 仍未进入 T06 replaceable。新的失败原因已从上游 T03 锚定失败转移为 T06 Step2 `retained_road_buffer_overlap_insufficient`。进一步审计显示 T06 为满足双向 corridor 纳入了远端 RCSD 路口 `5395491273775715` 相关 road，该路口距 SWSD endpoint `608228278` 约 `139m`，不应通过降低 overlap 阈值放行。后续应继续追溯 `608228278` 在 T07/T05 中为何只形成 `5395491273775691` 的 1V1 direct relation，以及该端 RCSD 分离通道是否需要上游构造可消费的多点路口。
