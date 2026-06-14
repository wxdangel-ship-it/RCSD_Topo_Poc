# 2026-06-14 T05 direct relation 邻近非主 RCSDNode 归组

## 背景

本轮追溯 Case `1885118` 中 `513920625_608228278` 与 `608228278_623846383` 未能正确构建 RCSD Segment 的根因。

T07 已将 SWSD 语义路口 `608228278` 锚定到 RCSD 语义路口 `5395491273775691`，但原始 RCSDNode 中还存在邻近节点 `5395491273775656`：该节点距离 `608228278` 约 `34.963m`，距离 T07 direct surface 约 `3.304m`，但 `mainnodeid = 0`，未被 T05 归入同一个 RCSD 语义路口。

## 根因

T05 原先对 T07 `existing_rcsdintersection_matched` 的成功 evidence 采用 direct relation 发布，只输出 `base_id_candidate = 5395491273775691`。这对 1:1 路口足够，但在 RCSD 分歧/合流通道里，面边缘存在未挂主 `mainnodeid` 的 RCSDNode 时，T06 Step2 无法把经过 `5395491273775656` 的反向通路视为同一 RCSD 语义路口消费。

临时实验只把 T05 copy-on-write `rcsdnode_out.gpkg` 中 `5395491273775656.mainnodeid` 改为 `5395491273775691` 后，`513920625_608228278` 与 `608228278_623846383` 均可进入 replaceable，说明根因在 T05 路口语义落实不完整，而不是 T06 buffer 阈值或最终替换兜底。

## 时间线

1. 审计 T07 evidence：`608228278` 为 `existing_rcsdintersection_matched`，`status_suggested = 0`，`base_id_candidate = 5395491273775691`。
2. 审计原始 RCSDNode/RCSDRoad：`5395491273775656` 没有主 `mainnodeid`，但连接 `5395491273776044` 与 `5395492314677635` 两条通路，是 `608228278` 端分歧/合流 RCSD topology 的必要节点。
3. 审计 T05 输出：旧 T05 只发布 direct relation，没有把 `5395491273775656` 落实为 `5395491273775691` 的同一 RCSD 语义路口成员。
4. 审计 T06 输出：旧 T06 对 `608228278_623846383` 的 full graph 能找到双向关系，但 buffer candidate 只有单向；根因是 required semantic node 未能把 `5656` 与 `5691` 合并消费。
5. 实现 T05 Phase2 规则：对 T07 direct success relation，在 surface 外 `5m` 内、SWSD projection `50m` 内寻找未挂主 RCSDNode，与 direct base 做 copy-on-write 归组。
6. 增加保护条件：其它成功 base、T03/T04 road-only split/endpoint reuse/support/fallback/required road 端点、以及跨 direct base 冲突候选均不归组，避免破坏已可消费的独立路口。

## 业务逻辑变更

T05 Phase2 不再把 T07 direct success relation 视为只能直接发布的一行关系。当 direct surface 附近存在明确属于同一锚定路口空间边缘、但原始 `mainnodeid` 未挂主的 RCSDNode 时，T05 负责在 copy-on-write `RCSDNode` 中补齐 `mainnodeid` 语义，使 T06 消费到完整 RCSD 语义路口。

该变更没有新增输入字段，没有改变 T07/T03/T04 evidence 语义，也没有放宽 T06 的 50m 横向 buffer、方向性或 topology 校验。

## 边界与质量约束

- CRS：本次审计和规则计算均在 EPSG:3857 下完成，距离阈值为米制。
- 拓扑一致性：只写 copy-on-write `mainnodeid`，不原地修改输入，不新增或删除 RCSDRoad/RCSDNode。
- 几何语义：`5m` surface gap 只表达 T07 已锚定路口面的边缘遗漏；`50m` target projection 只约束归组节点仍处于该 SWSD 语义路口局部语义范围内。
- 审计可追溯：成功归组写入 `rcsd_junctionization_audit.csv/json`，reason 为 `existing_rcsdintersection_nearby_nonbase_node_grouping`。
- 性能：Case `1885118` 局部 T05 Phase2 plan 统计 direct target `740`、group-existing target `69`、unique group node candidate `181`，可在当前 T10 Case 链路内完成。

## 验证

- 单测：`tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py`，`31 passed in 108.55s`。
- 局部 Case `1885118` 复跑 T05 + T06 Step1/2：
  - `608228278` T05 audit 为 `scene = group_existing_rcsd_nodes`，`reason = existing_rcsdintersection_nearby_nonbase_node_grouping`，`grouped_node_ids = 5395491273775691|5395491273775656`。
  - T06 replaceable unique 从 `849` 提升到 `852`。
  - 新增 replaceable：`513920625_608228278`、`608164506_613240401`、`608228278_623846383`。
  - 复核 `25109392_620115787` 仍在 replaceable 集合中，没有实际回退。

## 非目标

本次不对单个 Case 写补丁，不基于未知属性反推 RCSD 语义，不把所有 T07 direct relation 周边节点无条件归并，也不跳过 T06 的 buffer、方向性、通行拓扑审计。
