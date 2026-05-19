# 03 Context And Scope

## 上下文

T05 Phase 1 位于 T02/T03/T04 surface 成果之后，Phase 2 之前。

上游来源：

- T02_INPUT：外部既有 `RCSDIntersection` 面，需可锚定到 SWSD `mainnodeid`。
- T03：`virtual_intersection_polygons.gpkg`，来源于 T03 Step7 accepted 聚合面，需可锚定到 SWSD `mainnodeid`。
- T04：`divmerge_virtual_anchor_surface.gpkg`，来源于 T04 Step7 `final_state = accepted` 发布层，需可锚定到 SWSD `mainnodeid`。

下游：

- Phase 2 使用 `junction_anchor_surface.gpkg` 作为统一路口面基础。
- Phase 2 才讨论 RCSD residual、打断、预处理和关系表。

## 当前范围

- 读取三类输入面。
- 将输入统一到 `EPSG:3857`。
- 反查 `nodes.gpkg` 中的 `mainnodeid / kind_2 / patch_id`。
- 跳过未锚定到 SWSD 语义路口的来源面。
- 按 `mainnodeid` 分组。
- 执行单源发布、多源 union 或 primary 选择。
- 写出主图层、audit、summary。

## 当前范围外

- 不输出 `intersection_match_all.geojson`。
- 不生成最终关系表。
- 不修改原始 `RCSDRoad / RCSDNode / nodes`。
- 不对 RCSDRoad 做 split / cut / break。
- 不新增 RCSDNode。
- 不判断 support-only RCSD 是否构成路口。
- 不新增 repo 级执行入口。
