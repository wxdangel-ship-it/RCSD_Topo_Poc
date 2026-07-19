# 06 Risks And Technical Debt

## 1. 数据质量风险

- T04 或 T03/T04 混合 anchor 可能存在端点不确定性；在没有 T07 标准面或双 T03 正式锚点信用时自动排除，不归因 FRCSD。
- 大裁剪边缘可能制造假断路；Case manifest 存在时使用 500m 内区审计。
- FRCSD main/subnode 的 canonical 折叠可能制造假通路；正式 verdict 必须使用 raw endpoint 图。T05 grouped node 或 RCSDIntersection 覆盖不完整会降低召回，必须留审计统计。

## 2. 参数推广风险

默认 50m portal、路径长度和走廊阈值已在 `1026960` 上验证，但不能未经完整数据复核直接固化为所有城市的修复口径。

## 3. 性能风险

完整数据的全图建图、空间索引和逐 Segment local graph 需要内网实测；当前实现记录阶段耗时，后续可在不改变业务合同的前提下优化索引和并行。

## 4. 入口与兼容风险

T12 只有一个 root script；T10 Case/full 只是参数化调用。新增 CLI 子命令或改变 T10 默认启用状态必须另行授权并同步 registry/contract。

## 5. 非目标债

T12 目前不提供自动修复闭环。确认问题如何反馈给 1V1 FRCSD 生产方属于后续独立任务。
