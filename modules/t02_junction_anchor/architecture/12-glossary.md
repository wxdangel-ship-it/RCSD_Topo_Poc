# 12 术语表

- `segment`：来自 T01 的双向 Segment 聚合结果，当前 stage1 消费其中的 `id / pair_nodes / junc_nodes / s_grade|sgrade`。
- `junction_id`：从 `pair_nodes / junc_nodes` 解析得到的目标路口标识。
- `mainnode`：业务概念名；在 stage1 正式输入中对应字段是 `mainnodeid`。
- `representative node`：某个 junction group 中唯一承担 `has_evd` 写值的 node。
- `DriveZone gate`：判断某个 junction group 是否拥有有效资料区域的 stage1 规则。
- `has_evd`：当前阶段的资料存在性业务结果，值域为 `yes / no / null`。
- `anchor recognition / anchor existence`：stage2 基于 `RCSDIntersection` 判定代表 node 是否命中稳定锚点的最小闭环。
- `virtual intersection POC`：单 `mainnodeid` 的局部虚拟路口面实验入口，用于复核 own-group nodes、RC 局部组件与路口面的一致性。
- `polygon-support`：用于支撑虚拟路口面几何的局部 RC 组件集合；允许比最终 association 更完整。
- `association`：最终写入 `associated_rcsdroad.gpkg / associated_rcsdnode.gpkg` 的保守 RC 关联结果。
- `must-cover own-group nodes`：当前 `mainnodeid` 组内 node 必须被虚拟路口面覆盖的硬约束。
- `review_mode`：仅用于分析和人工复核的模式，可绕过 anchor gate，并将部分 RC outside DriveZone 从硬失败降为风险记录。
- `anchor_support_conflict`：虚拟路口面无法同时满足 own-group nodes 与局部 RC support 覆盖要求时的明确失败原因。
- `node_component_conflict`：虚拟路口面覆盖了超出 own-group 与 compound auxiliary 的额外 local nodes 时的风险状态。
- `summary bucket`：按 `0-0双 / 0-1双 / 0-2双` 对 stage1 结果做的分桶统计。
- `audit reason`：用于区分业务 `no` 与执行失败的稳定原因枚举。
