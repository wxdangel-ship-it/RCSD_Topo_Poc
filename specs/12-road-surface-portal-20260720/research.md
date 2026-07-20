# Research：T07 Road-surface portal 原始证据

## 1. 当前实现缺口

当前 T12 的正式 semantic carrier 以 node portal 为入口：T07 非 exact alias 必须落在对应唯一 `RCSDIntersection` 标准面内，内部 alias gap 与走廊距离也作为拒绝条件。该规则没有表达两类现实 Road 语义：

1. Road 几何已经穿越标准路口面，但 Road endpoint/alias 在面外；
2. Road 链已到达一个 frontier，该 frontier 可由锚点组的一跳物理 Road 明确连接，但当前搜索仍继续驶离路口。

因此 node portal 缺失会被误写成“必需方向无 carrier”。

## 2. 三条原始链路审计

### `1623512_508276240`

- 两端均为唯一 T07 标准面锚点。
- 有向物理 Road 链：`5846232894805637 → 5846235376255196 → 5846062370914501 → 5846062370914538 → 5846062370914539 → 5846062370914482 → 5846062370914532 → 5846062370914533 → 5846318893236852`。
- 首、末 Road 几何分别与 source/target 标准面相交。
- path length ratio `1.0190`，max corridor distance `17.748m`；方向、长度和走廊均可解释。
- 旧规则未从 Road surface portal 启动，属于误判。

### `1921739_1921764`

- 两端均为唯一 T07 标准面锚点。
- 最终正式重放的有向物理 Road 链：`5846239336988730 → 5846239336988881 → 5846239336988871 → 5846081866170510 → 5846081866170519 → 5846079383279186`。
- terminal Road 与目标标准面相交；source alias 虽在面外，但入口 Road 具有标准面接触证据。
- path length ratio `1.0041`，max corridor distance `2.748m`。
- 旧规则仅以 `t07_alias_outside_standard_surface` 拒绝，属于误判。

### `500636195_505415445`

- T05/T07 锚定关系正确：SWSD `500636195` 映射 RCSDIntersection `5388050881452080`，再映射 FRCSD mainNode `5844526046380357`；mainNode 与标准面关系受信。
- 正确反向有向 Road 链：`5844526046380212 → 5844526046380039 → 5844526046380222 → 5844526046380213 → 5844524169041622`。
- Road `5844524169041622` 到达 raw frontier Node `5844524169041675`；目标锚点组的一跳物理 Road `5844524169041952` 同样连接该 frontier，因此应在 Road `5844524169041622` 停止 carrier 跟踪。
- terminal Road 到标准面最小 gap 约 `2.985m`；full-road 走廊最大距离约 `53.422m`。这些距离仅表明人工审计风险，不推翻已经由锚点和物理 Road 拓扑证明的 surface access。
- 旧规则继续从 frontier 跟踪至 Road `5844526046380107`，造成假缺失/错误链路，属于误判。

## 3. 泛化规则结论

仅对两端均为受信唯一 T07 标准面的方向增加 Road-surface portal carrier：

1. source/target access 优先使用有向 Road 几何与对应标准面相交；
2. 若 terminal frontier 与目标锚点组存在 anchor→frontier 一跳物理 Road，且 support Road 与标准面相交或位于 `1m` 拓扑容差内，可作为 `anchor_one_hop_frontier`；source 端按对称规则处理，整条 carrier 至少一端必须有实际 Road-surface contact；
3. 路径必须包含物理 Road且方向正确；路径长度比例/附加长度继续硬门禁；
4. Road-surface gap、SWSD portal gap、内部 alias gap 与走廊距离输出为审计指标，不作为该规则的单独拒绝原因；
5. 该规则只能排除 candidate，不能确认质量问题；生产实现不得包含对象 ID。

`1026960` 冻结回归曾暴露一个过宽候选：`1019779_1026330` 仅凭双端一跳邻接可构造路径，但 source support Road 的方向为 frontier→anchor，不能证明从路口面向外的 surface portal。规则因此收紧为上述 anchor→frontier、有 surface contact 的通用门禁；收紧后 35/10/25/0 及 10 条 confirmed ID/issue type 集合恢复完全一致，没有修改冻结真值。

## 4. GIS 边界

- 所有距离计算使用显式 metre-based projected CRS。
- 不修改几何，不执行 snap/repair，不创建虚拟 Road。
- 标准面关系、Road 序列、frontier 和参数必须可追溯。
- 当前三条 Segment 证据来自本地可重放包；完整城市性能仍需正式数据验证。
