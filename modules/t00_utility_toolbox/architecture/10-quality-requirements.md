# 10. Quality Requirements

- Tool1-Tool7、Tool9、Tool10、Tool11 的范围与非范围必须能从文档直接读出
- 所有工具都必须允许复跑
- 日志与摘要必须可追溯
- Tool2-Tool7、Tool9、Tool10、Tool11 必须提供阶段级与 Patch / 文件 / 记录级进度输出
- CRS、几何修复与字段兼容规则必须可审计
- Tool11 GeoJSON / GPKG 写出优先采用 `ogr2ogr` 原生转换路径，不得以 Fiona 逐要素 sink 作为主路径，summary 必须记录写出引擎、耗时与吞吐
