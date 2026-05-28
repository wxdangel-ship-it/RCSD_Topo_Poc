# 12. Glossary

- `Tool1`：Patch 数据整理脚本
- `Tool2`：DriveZone per-patch fix + 全局聚合输出工具
- `Tool3`：Intersection 逐 Patch 预处理与汇总工具
- `Tool4`：A200 road 增加 `patch_id` 工具
- `Tool5`：A200 road 增加 SW 原始 `kind` 工具
- `Tool6`：A200 node shp 导出 GeoJSON 工具
- `Tool7`：目录级 GeoJSON 批量转 GPKG 工具
- `Tool9`：DivStripZone 逐 Patch 预处理与全局 GPKG 汇总工具
- `Tool10`：指定 JSON / NDJSON 上车点导出双图层 GPKG 工具
- `Tool11`：MIF 转 GeoJSON 与 GPKG 工具
- `patch_all`：Tool1 产出的统一 Patch 目录根
- `patch_id`：Tool4 写入一层路网的 Patch 标识字段
- `kind`：Tool5 写入一层路网的 SW 原始种别字段
- `nodes.geojson`：Tool6 输出的节点 GeoJSON 文件
- `.gpkg`：Tool7 为每个顶层 GeoJSON 生成的同名 GeoPackage 文件
- `.mif` / `.mid`：MapInfo MIF/MID 文本矢量数据文件组，Tool11 以 `.mif` 为扫描入口
- `MIF 目录`：Tool11 默认扫描的内网目录 `D:\TestData\POC_Data\first_layer_road_net_v0\SW\MIF`
