# 01 Introduction And Goals

## 目标

T05 整体分为两个独立阶段：

- Phase 1：路口面融合发布。
- Phase 2：RCSD 打断、预处理与 SWSD-RCSD 关系生产。

当前模块只实现 Phase 1，目标是把已锚定到 SWSD 语义路口的 T02_INPUT / T03 / T04 路口面候选融合成统一发布层 `junction_anchor_surface.gpkg`，并提供可追溯 audit 与 summary 供 Phase 2 消费。

## 成功判据

- 只消费 formal accepted surface candidate。
- 不发布无法解析 `mainnodeid` 的未锚定路口面。
- 输出 CRS 固定为 `EPSG:3857`。
- 主图层字段固定为 7 字段 schema。
- 多源合并规则可解释、可审计。
- 不输出关系表，不打断 RCSDRoad，不新增 RCSDNode。
- 不新增 repo CLI 或长期入口。

## 当前非目标

- 不建立 SWSD-RCSD 最终关系。
- 不处理 RCSD-only / support-only 的拓扑改造。
- 不回头修改 T02/T03/T04 路口面几何生成逻辑。
- 不把 relation evidence 当作本阶段主输入。
