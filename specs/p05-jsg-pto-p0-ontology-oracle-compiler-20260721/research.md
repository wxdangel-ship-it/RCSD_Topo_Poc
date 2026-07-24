# P05-JSG-PTO-P0 研究记录

## 1. 已复用事实

- 正式范围为 51 个 RoadGraph Case，排除 `T10-Error / 1213556_1263661`。
- T01 Segment 当前提供 `pair_nodes`、`junc_nodes`、`roads`、`sgrade`、`segment_type`。
- 51 Case 中共有 8,863 个 T01 Segment，其中 474 个 `advance_right`。
- 未观察到 `pair_nodes` 两端相同的真实闭环样本；loop 需要合成合同测试，不能声明真实正例已验证。
- 已观察到同一附属 Junction 被两个 Segment 声明贯穿的冲突；必须进入 `REVIEW`，不得自动选择。
- R2 Oracle 已能以 label-only edit IR 精确重建 51 Case T06 Road/Node，可作为 JSG compiler 的冻结后端真值。

以上计数必须在正式运行中重新由 manifest 计算并写入证据，本文不替代运行结果。

## 2. 关键决策

### RD-001：P0 不推断新的上游字段语义

保留 T01 raw 值与 evidence refs；只使用已有文档明确语义。无法确定 `road_grade`、Terminal 子类型、Connector access 或 Movement 时，输出 `UNSPECIFIED/REVIEW`，不按局部几何猜测。

### RD-002：方向来自 carrier 图

Segment 的 `ENTER/EXIT/BOTH` 必须由 T01 Road 的有向 carrier 及已有 direction 合同推导，不使用 `pair_nodes` 顺序。

### RD-003：多贯穿是 Review，不是 hard failure

本体允许 Junction 处存在冲突候选，但自动发布状态最多一个 THROUGH。Oracle truth 保留全部证据并将该 Junction/关系标为 `REVIEW`；自动选中计数必须为零。

### RD-004：P0 compiler 复用 R2 Oracle

JSG truth 持有带 lineage 的 `carrier_realization_ref`，compiler 验证其 Case、manifest、hash 与语义归属后读取对应 R2 edit IR。这样验证 JSG 到既有 RoadGraph 后端的可编译性，同时明确它是 label-only Oracle proof。

### RD-005：Movement 与 TrafficRule 分离

P0 只从物理 carrier topology 形成 PhysicalMovement。T09 不作为删除 Movement 的输入；若未来需要规则合法性，作为独立 overlay。

## 3. 不确定项处理

- 真实 loop：零实例，单独报告。
- `advance_right` source/target access：只有唯一、可追溯关联时发布，否则 `REVIEW`。
- Terminal 子类型：证据不充分时为 `TERMINAL_UNKNOWN`。
- 高等级/生长层级：保存 `sgrade` 原值和显式映射来源；不把道路业务等级与构图顺序合并。
