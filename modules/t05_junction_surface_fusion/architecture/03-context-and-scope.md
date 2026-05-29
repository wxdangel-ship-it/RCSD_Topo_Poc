# 03 Context And Scope

## 上下文

T05 Phase 1 位于既有 RCSDIntersection / T03 / T04 surface 成果之后，Phase 2 之前；T05 Phase 2 位于统一路口面发布之后，消费 T07/T03/T04 relation evidence，为 T06 等下游模块提供 SWSD-RCSD 语义路口关系与 copy-on-write RCSD 网络成果。

上游来源：

- T02_INPUT：外部既有 `RCSDIntersection` 面，需可锚定到 SWSD `mainnodeid`。
- T03：`virtual_intersection_polygons.gpkg`，来源于 T03 Step7 accepted 聚合面，需可锚定到 SWSD `mainnodeid`。
- T04：`divmerge_virtual_anchor_surface.gpkg`，来源于 T04 Step7 `final_state = accepted` 发布层，需可锚定到 SWSD `mainnodeid`。

Phase 1 下游：

- Phase 2 使用 `junction_anchor_surface.gpkg` 作为统一路口面基础。
- Phase 2 才讨论 RCSD residual、打断、预处理和关系表。

Phase 2 下游：

- `intersection_match_all.geojson` 提供 SWSD `target_id` 到 RCSD 语义路口主 node `base_id` 的关系。
- `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 提供 copy-on-write 后的 RCSD 通行网络。

## 当前范围

- 读取三类输入面。
- 将输入统一到 `EPSG:3857`。
- 反查 `nodes.gpkg` 中的 `mainnodeid / kind_2 / patch_id`。
- 跳过未锚定到 SWSD 语义路口的来源面。
- 按 `mainnodeid` 分组。
- 执行单源发布、多源 union 或 primary 选择。
- 写出主图层、audit、summary。
- Phase 2 读取 Phase 1 surface、fusion audit、final nodes、原始 RCSDRoad/RCSDNode 与 T07/T03/T04 relation evidence；旧 T02 evidence 仅兼容旧批次。
- Phase 2 执行场景分流、RCSDNode grouping、必要的 RCSDRoad split、关系发布、blocking error 与 summary 输出。

## 当前范围外

- Phase 1 不输出 `intersection_match_all.geojson`。
- Phase 1 不生成最终关系表。
- Phase 1 不修改原始 `RCSDRoad / RCSDNode / nodes`。
- Phase 1 不对 RCSDRoad 做 split / cut / break。
- Phase 1 不新增 RCSDNode。
- Phase 1 不判断 support-only RCSD 是否构成路口。
- Phase 2 不重新融合路口面，不回改 Phase 1 结果，不原地修改输入文件。
- 不新增 repo 级执行入口。
