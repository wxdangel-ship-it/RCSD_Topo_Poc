# 03. Context And Scope

- Tool1：统一 `patch_all` 骨架和 `Vector/` 归位
- Tool2：生成 per-patch `DriveZone_fix.geojson` 并输出全局 `DriveZone.geojson`
- Tool3：输出全局 `Intersection.geojson`
- Tool4：给 `A200_road` 写入 `patch_id`
- Tool5：给 `A200_road_patch` 写入 SW 原始 `kind`

当前不在范围内：

- Tool6+
- Tool3 全量重写
- 复杂 manifest / 数据库治理
