# 04 Evidence And Audit

## 1. 证据分层

T00 证据分为派生输出、summary 和 log 三层。派生输出用于人工查看或历史比较；summary 用于机器可读审计；log 用于定位执行过程。

## 2. formal 支撑成果

- Tool1：`patch_all` 目录骨架与 `Vector/` 归位。
- Tool2：per-patch `DriveZone_fix.geojson` 与根目录 `DriveZone.geojson`。
- Tool3：根目录 `Intersection.geojson`。
- Tool4：`A200_road_patch.geojson` 与 `A200_road_patch_unmatched.geojson`。
- Tool5：`A200_road_patch_kind.geojson`。
- Tool6：`nodes.geojson`。
- Tool7：指定目录下每个顶层 GeoJSON 的同名 GPKG。
- Tool9：per-patch `DivStripZone_fix.geojson` 与根目录 `DivStripZone.gpkg`。
- Tool10：双图层 GPKG。
- Tool11：每个输入 MIF 的同名 GeoJSON 与 GPKG。

这些成果是 T00 工具成果，不是项目主链正式业务成果。

## 3. 工具级审计

- 每个工具必须记录输入路径、输出路径、运行 ID、summary 路径和 log 路径。
- 批量工具必须记录总数、成功数、失败数、跳过数和失败原因。
- 空间工具必须记录输入 CRS、输出 CRS 和 CRS 来源。
- 几何修复必须记录修复数、失败数和失败原因。

## 4. review-only 证据

当前 T00 无稳定 review-only 输出。人工检查依赖工具输出文件、summary 和 log。

## 5. internal / recovery 证据

summary 和 log 同时承担 internal / recovery 证据角色。复跑或排查时应优先查看 summary 中的输入、输出、失败原因和写出引擎。

## 6. 下游交接证据

T00 没有稳定业务 handoff。若某项 T00 输出被 T08 或其它正式模块吸收，必须由对应模块文档重新定义输入语义、字段和验收口径。
