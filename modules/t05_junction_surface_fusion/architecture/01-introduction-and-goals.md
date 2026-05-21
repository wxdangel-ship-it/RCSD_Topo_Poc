# 01 Introduction And Goals

## 目标

T05 整体分为两个独立阶段：

- Phase 1：路口面融合发布。
- Phase 2：RCSD 打断、预处理与 SWSD-RCSD 关系生产。

当前模块实现 Phase 1 与 Phase 2。Phase 1 把已锚定到 SWSD 语义路口的 T02_INPUT / T03 / T04 路口面候选融合成统一发布层 `junction_anchor_surface.gpkg`，并提供可追溯 audit 与 summary；Phase 2 消费 Phase 1 成果、final nodes、原始 RCSDRoad/RCSDNode 与 T02/T03/T04 relation evidence，输出 `intersection_match_all.geojson`、copy-on-write RCSD 网络成果与 junctionization audit。

## 成功判据

- 只消费 formal accepted surface candidate。
- 不发布无法解析 `mainnodeid` 的未锚定路口面。
- 输出 CRS 固定为 `EPSG:3857`。
- 主图层字段固定为 7 字段 schema。
- 多源合并规则可解释、可审计。
- Phase 1 不输出关系表，不打断 RCSDRoad，不新增 RCSDNode；Phase 2 的 RCSDRoad / RCSDNode 变化只通过 copy-on-write 输出表达。
- 不新增 repo CLI 或长期入口。

## 当前非目标

- 不在 Phase 1 建立 SWSD-RCSD 最终关系。
- 不在 Phase 1 处理 RCSD-only / support-only 的拓扑改造。
- 不回头修改 T02/T03/T04 路口面几何生成逻辑。
- 不把 relation evidence 当作 Phase 1 主输入。
- Phase 2 不重新融合路口面，不修改 Phase 1 成果，不原地修改输入 RCSDRoad / RCSDNode / nodes。
