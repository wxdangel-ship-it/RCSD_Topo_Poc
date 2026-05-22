# 10 质量要求

## CRS

- Tool1 默认保留输入 CRS；显式传入 `target_epsg` 时必须正确重投影。
- Tool2 必须统一输出 `EPSG:3857`。
- Tool3 必须统一输出 `EPSG:3857`。

## 拓扑

- Tool1 只转换格式或显式重投影，不做几何拓扑修复。
- Tool2 只做属性关联与空间匹配，不改写 Road 几何拓扑。
- Tool3 只在 copy-on-write Nodes 输出中改写类型聚合字段，不修复几何，不输出或改写 Roads。

## 审计

summary 必须记录输入、输出、参数、字段解析、CRS、要素计数、匹配计数与失败原因。

## 性能

Tool1 的 GPKG 输出必须使用直接 SQLite GeoPackage 写出路径；GeoJSON 输出必须使用流式 JSON 写出路径。summary 必须记录要素数、耗时与吞吐，命令脚本必须输出进度信息。
Tool2 Kind enrich 必须使用空间索引，并记录空间匹配候选计数。
Tool2 / Tool3 命令脚本必须输出阶段进度，并在 summary 记录耗时与吞吐；GPKG 输出必须复用共享直接 SQLite GeoPackage 写出路径。
Tool3 复杂分歧 / 合流聚合必须使用 Road 拓扑链路搜索，并记录候选数、链路数、聚合组与更新节点数；复杂链 component 组装不得按组件反复全量扫描链路边。
