# Research：T12 direction-strict portal

## 1. 已确认事实

- Road `direction=0/1` 双向、`2` 为 `snodeId→enodeId`、`3` 为 `enodeId→snodeId`。
- `candidate_audit.py` 当前为 source 和 target portal 都传入 `local_graph.undirected` 的 node key。
- `raw_portal_candidates()` 的 `direction_role` 当前只写入审计行，不参与资格计算。
- 模块源事实已经要求 start 有出边、end 有入边，当前实现与源事实不一致。
- `1885084_1885086` 输出为 `T03|T07`；正向 semantic directed missing、semantic undirected equivalent，Road-surface 因非双 T07 未运行。
- 用户确认反向 Road 为 `5885111744069974`，对应正向 Road 为 `5885111744069971`，且存在多处类似结果。

## 2. 尚需原始数据确认

- `5885111744069971` 是否位于 T12 manifest 指向的同版本 FRCSD。
- 其 `snodeId/enodeId/direction`、两个 endpoint 的 `mainNodeId/subNodeId`。
- Road 是否进入 `Segment.buffer(50m)` local graph。
- 正向 endpoint 是否进入 source portal，另一端是否与下一条正向 Road canonical/raw 连续。

## 3. 当前判断

方向角色未过滤是确定实现缺口，应立即修复。`5885111744069971` 未进入正向链的最终根因可能位于 local graph、source portal 或 canonical endpoint 三处之一；在取得原始字段前不把任何一种猜测固化为生产规则。
