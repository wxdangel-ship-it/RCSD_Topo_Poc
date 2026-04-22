# Spec: T04 Step4 正向 RCSD 选择器正式重构（aggregated / polarity / presence）

## 目标

将 Step4 正向 RCSD 的正式链路冻结为：

`pair-local raw observation -> rcsd_candidate_scope -> local_rcsd_unit -> aggregated_rcsd_unit -> polarity normalization -> role mapping -> positive_rcsd_present -> A/B/C -> required_rcsd_node`

并满足：

- `pair-local` 为空时直接 `C / no_support`
- `positive_rcsd_present` 与 `A/B/C` 分层表达
- `axis polarity inverted` 默认在 aggregated 级别识别
- side-label 不得单独把事实存在样本压到 `C`
- `required_rcsd_node` 从 matched local / aggregated unit 独立输出

## 冻结定义

### 1. 作用域层

- `pair-local` 是当前 SWSD unit 的局部语义框架，不是单一 polygon
- `rcsd_candidate_scope` 是软进入范围，不是 `selected_candidate_region` 的硬裁剪
- `local_rcsd_unit` 是事实构件，不是默认最终判级单元
- `aggregated_rcsd_unit` 是默认正式判级单元

### 2. local / aggregated

- `local_rcsd_unit` 只允许：
  - `node-centric local_rcsd_unit`
  - `road-only local_rcsd_unit`
- `road-only local_rcsd_unit` 最高只能到 `B`
- `aggregated_rcsd_unit` 由共享 road / node / forward 锚点的相邻 matched local units 聚合而成
- single-unit 只允许作为 fallback

### 3. 事实层

- 必须显式输出 `positive_rcsd_present = true / false`
- 一旦 `positive_rcsd_present = true`，支持强度下限就是 `B`
- `C` 只允许用于事实层缺失、无法构 unit、或 normalized role mapping 不成立

### 4. 极性归一化层

- 必须显式输出 `axis_polarity_inverted`
- 默认在 `aggregated_rcsd_unit` 级别识别
- single local unit 只作 fallback

### 5. 判级层

- 先比 entering / exiting 角色
- 角色已经成立后，再比方向
- `A/B/C` 必须由 normalized role mapping 产生
- `angle_match` / nearby fallback 不再是正式主规则

### 6. 输出层

Step4 当前正式输出至少包括：

- `selected_rcsdroad_ids`
- `selected_rcsdnode_ids`
- `primary_main_rc_node`
- `positive_rcsd_present`
- `positive_rcsd_support_level`
- `positive_rcsd_consistency_level`
- `required_rcsd_node`
- `aggregated_rcsd_unit_id`
- `aggregated_rcsd_unit_ids`
- `axis_polarity_inverted`
- `required_rcsd_node_source`

## 非目标

- 不进入 Step5-7
- 不做跨 case RCSD 二次闭环
- 不重写 Step1-3
- 不修改 T02 模块正文
