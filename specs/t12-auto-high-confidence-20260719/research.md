# Research：35 个候选的通用可分性

## 1. 数据与事实

- 回归数据：`E:\TestData\POC_QA\T10\1026960`。
- 现有 T12 结果：35 个候选；冻结真值为 10 confirmed、25 excluded。
- 输入 CRS 全部为 `EPSG:3857`；无效几何、缺失 Road endpoint 均为 0；`silent_fix=false`。
- `RCSDIntersection` 为 909 个 Polygon，且是 T07/T10 标准输入。

## 2. 根因

现有 T12 的正式 portal 检查仍使用 canonical node graph，并把 SWSD portal 50m 内任意角色相容 FRCSD Node 加入多源最短路。该逻辑能修复单节点锚定误报，但存在两个过宽假设：

1. `mainNodeId/subNodeId` 被折叠为零成本图连接，即使原始 Road endpoint 之间没有物理连接；
2. T07 标准路口也允许采用标准路口面之外的任意邻近 node，可能跨到相邻路口或道路。

因此 canonical/spatial portal 适合作为候选宽召回和解释证据，不足以直接证明最终通行等价。

## 3. 对比实验

对 35 个候选在同一输入上比较四类 raw endpoint portal 策略：

| 策略 | 真值检出 | 额外 raw 失败 | 结论 |
|---|---:|---:|---|
| 仅 T05 group | 10/10 | 24 | 召回高但误报过多。 |
| 所有 endpoint 均采用 50m spatial portal | 8/10 | 5 | 两个真值仍被邻近节点掩盖。 |
| T07 仅 group，其它 endpoint 采用 spatial portal | 10/10 | 10 | T07 召回过窄，仍有复合路口误报。 |
| T07 group + 对应 RCSDIntersection 面内 raw node；其它 endpoint 采用 spatial portal | 10/10 | 5 | 形成可解释的最小候选集。 |

最后 5 个额外 raw 失败均不含 T07，anchor 组合为 T03/T04、T04/T03 或 T04/T04；它们存在复合端点或多锚点不确定性，不能高置信归因于 FRCSD。10 个真值中 9 个至少一端为 T07，另 1 个为 T03/T03；应用正式锚点门禁后结果为 10/25/0。

## 4. 决策

采用两层图：

- canonical graph：保持现状，只负责宽召回候选和 T06 交叉解释；
- raw endpoint graph：负责最终 carrier verdict，不引入隐式节点折叠。

采用两层 portal：

- T07：T05 显式 group + 对应 `RCSDIntersection` 标准面内 raw node；
- T03/T04：T05 显式 group + SWSD 实际接入侧 50m 内角色相容 raw node。

采用准确率优先门禁：

- 至少一端具有唯一标准面关联的 T07，或 T03/T03，允许自动确认；
- 其它 raw 失败只记录并排除，不进入最终问题。

## 5. 未推广事实

- `50m`、路径比例、附加长度和走廊偏离仍是正式可参数化配置，不因单 Case 变成不可变城市规则。
- T04 场景不是“永远不能确认”，而是当前缺少足以从复杂锚点唯一归因 FRCSD 的通用证据；后续可通过正式契约增加更强 surface/anchor 证据。
