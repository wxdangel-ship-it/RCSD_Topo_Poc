# Research：T12 anchored canonical alias raw portal

## 1. 已确认代码事实

- v5 raw graph 已按 Road `Direction` 建有向边。
- v5 portal 已按 source outgoing / target incoming 过滤。
- `raw_portal_candidates()` 只遍历 `anchor.grouped_node_ids`，没有使用 `NodeCanonicalizer` 展开 canonical group。
- T03/T04 其它 raw node 只能通过 `portal_radius_m` spatial fallback。
- 因而 mainNode 锚定、Road 连接 subNode/alias 且 alias 超出 spatial 半径时，正确方向 Road endpoint 仍可能缺席。
- 初版曾递归展开全部 `grouped_node_ids` 的各自 canonical group；`1026960` 原始数据证明这会把同一复杂路口其它 grouped node 的支路误提升为 raw portal，使 `953923_953936` 从 confirmed 变为 excluded。
- 收紧为只展开 selected `base_id` mainNode canonical group 后，显式 grouped raw node仍保留，`1026960` 的10个确认问题集合恢复且新 mainNode/subNode 测试继续通过。

## 2. 用户确认的业务事实

- Segment/1V1 锚定使用 mainNode ID。
- 正反向跟踪必须落到实际 Road endpoint node ID，并严格按 Road `Direction`。
- 已锚定 alias 的距离门禁只作审计，不是拒绝理由。

## 3. 未在本地声称验证的事实

- 当前会话无法访问用户内网 `D:` 运行目录。
- 目标完整数据中具体 Road 的 endpoint、alias、local graph 和新输出仍需用户内网重跑验证。
- 生产规则不使用这些对象 ID，且不得用本地裁剪样本代替完整内网验收。
