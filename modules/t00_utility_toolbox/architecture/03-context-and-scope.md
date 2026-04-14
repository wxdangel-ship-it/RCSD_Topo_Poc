# 03. Context And Scope

- Tool1：统一 `patch_all` 骨架和 `Vector/` 归位
- Tool2：生成 per-patch `DriveZone_fix.geojson` 并输出全局 `DriveZone.geojson`
- Tool3：输出全局 `Intersection.geojson`
- Tool4：给 `A200_road` 写入 `patch_id`
- Tool5：给 `A200_road_patch` 写入 SW 原始 `kind`
- Tool6：将 `A200_node.shp` 导出为 `nodes.geojson`
- Tool7：将指定目录下顶层 `GeoJSON` 批量导出为同名 `GPKG`
- Tool10：将超大 JSON 点记录流式导出为点状 `GPKG`

当前不在范围内：

- Tool8
- Tool3 全量重写
- 复杂 manifest / 数据库治理
