# Validation Summary：T12 anchored canonical alias raw portal

## 自动化回归

- T10 + T12：`119 passed`，存在 `2` 条既有 pyproj/NumPy deprecation warning。
- 覆盖远距离 anchored alias、source outgoing / target incoming Direction role、正反向使用不同 alias/Road、非锚定 spatial fallback 继续执行 hard radius，以及只扩展 selected `base_id` canonical group。

## `1026960` 原始数据基线

- 输入：`E:\TestData\POC_QA\T10\1026960` 及其 manifest 指向的既有 T01/T05/T06 证据。
- schema：`2026-07-27.t12_frcsd_quality_audit.v6`。
- Segment：`1267`；FRCSD Road：`4289`；FRCSD Node：`4762`。
- 候选：`35`；确认质量问题：`10`；排除：`25`；人工复核：`0`。
- 冻结的 10 个确认 Segment 集合保持完全一致。

初版曾扩展所有 `grouped_node_ids` 各自的 canonical group，导致复杂路口旁支 alias 被误提升为 raw portal，使确认数从 `10` 降为 `9`。原始 Road 链审计证明该放宽越过了 selected mainNode 锚定边界。正式实现因此收紧为：

1. 保留全部显式 `grouped_node_ids` raw node；
2. 只扩展 T05 已选中 `base_id` 所属 canonical group；
3. source 仅接受当前方向存在 outgoing Road 的 raw node；
4. target 仅接受当前方向存在 incoming Road 的 raw node；
5. carrier 必须在 raw identity endpoint 图中沿 Road `Direction` 成立。

## GIS 与审计门禁

- CRS：全部输入和处理 CRS 均为 `EPSG:3857`，本次没有坐标转换。
- 拓扑：FRCSD Road endpoint 缺失数为 `0`；没有 canonical 零成本折叠替代物理 Road。
- 几何：各输入 invalid geometry 数均为 `0`；anchored alias 距离仅审计，非锚定 spatial fallback 仍受原 hard radius/标准面门禁。
- 可追溯性：summary/manifest 记录输入路径与哈希、schema、portal policy、运行环境、对象规模、阶段耗时和输出路径。
- 性能：总耗时 `5.319s`，其中 candidate audit `2.452s`；canonical groups 全图只构建一次。
- 修复边界：`silent_fix=false`，T12 只发布质检结论，不修改 FRCSD。

## 内网待确认

当前会话无法访问用户内网运行目录，因此尚未对内网全图结果作本机复验。内网重跑必须使用包含本变更的代码，并确认 summary 中：

- `schema_version=2026-07-27.t12_frcsd_quality_audit.v6`；
- `quality.portal_direction_policy.anchored_alias_membership=selected_base_canonical_group`；
- `quality.portal_direction_policy.road_direction_required=true`。
