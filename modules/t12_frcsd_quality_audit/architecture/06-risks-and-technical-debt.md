# 06 Risks And Technical Debt

## 1. 数据质量风险

- T04 或 T03/T04 混合 anchor 可能存在端点不确定性；在没有 T07 标准面或双 T03 正式锚点信用时自动排除，不归因 FRCSD。
- SWSD 可能通过其它 Road 形成合法反向替代路径；非预期反向检查必须搜索 SWSD 全图并使用同一几何阈值保守排除。即使未找到替代路径，T03/T03 等弱锚点也只保留候选/排除证据。
- 大裁剪边缘可能制造假断路；Case manifest 存在时使用 500m 内区审计。
- FRCSD main/subnode 的 canonical 折叠可能制造假通路，也可能把同一现实路口拆成 raw 假断裂。只提升选中 `base_id` canonical group 的 raw alias portal membership，禁止递归展开其它 grouped node 的 group；raw endpoint identity 图、方向正确的物理 Road和长度继续作为强门禁，非锚定 spatial/标准面 fallback 不放宽。既有 semantic carrier 保留内部 alias 门禁。双端唯一 T07 标准面可由独立 Road-surface carrier 通过 Road 相交或 anchor→frontier 且接触标准面的单侧一跳 support 排除 node-portal 假断裂，禁止双端任意一跳拼接；其它距离只作审计。T05 selected base、grouped node、canonical group 或 RCSDIntersection 覆盖不完整会降低召回，必须留审计统计。
- 正反向平行 Road 可能在同一空间走廊内高度重合；portal 若只按无向邻接筛选，会把反向端点混入当前方向并产生误报。所有方向必须使用 outgoing/incoming 角色过滤，无向路径只能作为诊断证据。
- 当前 Segment `50m` local graph 可能包含相邻或对向 Segment 的 RCSD Road；局部连通只构成候选召回。反向正式确认必须证明第一/最后 Road 接触当前双端标准面，并在剔除路口面共享几何后逐 Road 获得当前 Segment 唯一最优归属；其它 Segment 更优或并列时保守排除。

## 2. 参数推广风险

默认 50m portal、路径长度和走廊阈值已在 `1026960` 上验证，但不能未经完整数据复核直接固化为所有城市的修复口径。Road-surface 层把距离降为审计项后，必须持续监控绕行、错误大组和过宽标准面风险；不得用距离接边替代 surface/frontier 拓扑证据。反向检查对弱锚点和阈值敏感样例保持保守排除，避免把局部样例参数提升为跨城市强真值。

## 3. 性能风险

完整数据的全图建图、Segment 空间索引、逐 Segment local graph 和逐反向路径 Road 归属查询需要内网实测；当前实现记录阶段耗时，后续可在不改变业务合同的前提下优化索引和并行。

## 4. 入口与兼容风险

T12 只有一个 root script；T10 Case/full 只是参数化调用。新增 CLI 子命令或改变 T10 默认启用状态必须另行授权并同步 registry/contract。

## 5. 非目标债

T12 目前不提供自动修复闭环。确认问题如何反馈给 1V1 FRCSD 生产方属于后续独立任务。
