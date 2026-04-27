# 03. Context And Scope

- Tool1：统一 `patch_all` 骨架和 `Vector/` 归位
- Tool2：生成 per-patch `DriveZone_fix.geojson` 并汇总输出 `DriveZone.geojson`
- Tool3：输出全局 `Intersection.geojson`
- Tool4：给 `A200_road` 写入 `patch_id`
- Tool5：给 `A200_road_patch` 写入 SW 原始 `kind`
- Tool6：将 `A200_node.shp` 导出为正式节点矢量结果
- Tool7：将指定目录下顶层 `GeoJSON` 批量导出为同名 `GPKG`
- Tool9：对 `DivStripZone` 做逐 Patch 预处理并汇总输出
- Tool10：将指定 JSON / NDJSON 中的 `data.spots` 上车点导出为单个双图层 `GPKG`

当前不在范围内：

- Tool8
- Tool11+
- Tool3 全量重写
- 复杂 manifest / 数据库治理
