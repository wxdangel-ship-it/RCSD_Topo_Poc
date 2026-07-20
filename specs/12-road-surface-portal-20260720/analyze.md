# Analyze：T12 Road-surface portal 一致性检查

## 1. 已识别冲突

当前项目/T12 正式源事实规定：T07 alias 必须位于唯一标准面内，内部 alias gap 和走廊距离超过阈值时拒绝 semantic carrier。用户本轮已明确授权新的正式业务口径：在 1V1 路口锚定正确时，距离门禁与 T06 一致，仅作后续人工审计参考，不作为拒绝理由，并授权 Road-surface portal。

该冲突已由业务授权解决；实现前必须同步更新项目级源事实、T12 模块源事实与契约，不能仅改代码。

## 2. 一致性约束

- T07 锚点正确与唯一标准面仍是强前提；不反推或改变 T05/T07 字段语义。
- Road-surface evidence 必须包含原始方向正确的物理 Road；一跳 frontier 还必须由 anchor→frontier 且接触标准面的 support Road 证明，整条 carrier 至少一端实际接触标准面。距离 audit-only 不能退化为任意近邻接边。
- 路径长度比例/附加长度仍是等价强门禁。
- 新 evidence 只能排除误报，不能单独确认质量问题。
- 非 T07 锚点继续使用旧规则，T06 实现不在本轮修改范围。
- 无 CLI/入口变更，`entrypoint-registry.md` 无需修改。

## 3. 验收阻断条件

- 任一生产规则含 Case/Segment/Road/Node ID 特判；
- `1026960` 的 10 条 confirmed ID/issue type 冻结集合发生无原始数据解释的变化；
- 输入几何被 snap/repair/截断，或出现未记录的 CRS 变换；
- Road-surface 路径无物理 Road、方向不正确或锚点标准面不唯一；
- 100 KB 源码硬阈值、代码体量登记或入口治理不通过。
