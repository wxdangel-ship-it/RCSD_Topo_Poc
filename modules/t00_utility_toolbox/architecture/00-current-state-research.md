# 00. Current State Research

- 当前阶段：`active / Tool1-7, Tool9-11 increment`
- 当前正式范围：Tool1-Tool7、Tool9、Tool10、Tool11（当前未登记 Tool8）
- Tool6 为新增 shp -> GeoJSON 导出工具
- Tool7 为新增目录级 GeoJSON -> GPKG 导出工具
- Tool9 为 DivStripZone 逐 Patch 预处理与全局 GPKG 汇总工具
- Tool10 为指定 JSON / NDJSON 上车点双图层 GPKG 导出工具
- Tool11 为 MIF -> GeoJSON / GPKG 同目录转换工具
- Tool6 当前约定输出 `EPSG:3857` GeoJSON，并在摘要中显式标注项目内约定说明
- 所有工具沿用“固定脚本 + src 模块 + 根目录日志摘要”风格
