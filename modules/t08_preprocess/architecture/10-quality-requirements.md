# 10 质量要求

## CRS

- Tool1 默认保留输入 CRS；显式传入 `target_epsg` 时必须正确重投影。
- Tool2 必须统一输出 `EPSG:3857`。
- Tool3 必须统一输出 `EPSG:3857`。
- Tool4 必须统一输出 `EPSG:3857`。
- Tool5 必须统一输出 `EPSG:3857`。
- Tool6 的 GPKG 输出必须统一为 `EPSG:3857`。
- T08 所有成果输出文件名必须在扩展名前以 `_toolX` 结尾。

## 拓扑

- Tool1 只转换格式或显式重投影，不做几何拓扑修复。
- Tool2 只做属性关联、空间匹配和 `17` 主辅路出入口事件 Road 删除，不改写 Road 几何拓扑。
- Tool3 只在 copy-on-write Nodes 输出中改写类型聚合字段，不修复几何，不输出或改写 Roads。
- Tool4 只修复错误 T 型路口代表 node 的 `kind_2`，不重塑 Road/Node 拓扑，不输出或改写 Roads。
- Tool5 只在 copy-on-write Nodes/Roads/audit Nodes 输出中执行复杂路口和错误 1 对多处理，不修改输入文件；错误 1 对多必须先基于输入 `RCSDIntersection` 识别候选，Road 删除必须来自 T02 `node_error_2` 面内连通合并逻辑，不允许 silent fix。
- Tool6 只输出人工质检候选 CSV/GPKG/summary，不改写 Nodes/Roads；连续分歧合流与交叉路口候选必须可追溯入出度、相关 Road 与 suppress 原因，不允许 silent fix。

## 审计

summary 必须记录输入、输出、参数、字段解析、CRS、要素计数、匹配计数与失败原因。

## 性能

Tool1 的 GPKG 输出必须使用直接 SQLite GeoPackage 写出路径；GeoJSON 输出必须使用流式 JSON 写出路径。summary 必须记录要素数、耗时与吞吐，命令脚本必须输出进度信息。
Tool2 Road / Raw Kind GPKG 读取应优先使用直接 SQLite GeoPackage 快读，并保留 Fiona 回退兼容；Patch join 必须避免读取无用 Patch Road 几何；Kind enrich 必须使用空间索引，并记录空间匹配候选计数、分块查询大小与阶段耗时。
Tool2 必须记录 `event_road_0a_count`，事件 Road 输出必须可追溯被删除 Road 的 `id / patch_id / kind` 与几何。
Tool2 / Tool3 / Tool4 / Tool5 / Tool6 命令脚本必须输出阶段进度，并在 summary 记录耗时与吞吐；GPKG 输出必须复用共享直接 SQLite GeoPackage 写出路径。
Tool5 复杂分歧 / 合流聚合必须使用 Road 拓扑链路搜索，并记录候选数、链路数、聚合组与更新节点数；复杂链 component 组装不得按组件反复全量扫描链路边。Tool5 必须输出 audit Nodes，覆盖复杂分歧 / 合流聚合与错误 1 对多处理实际涉及的 node。
Tool4 命令脚本必须输出阶段进度，summary 必须记录语义路口数、错误数、修复数、错误类型分布、方向异常数、提前右转 / 辅路 Road 计数、suppressed degree exception、audit Nodes 数量、阶段耗时、吞吐与 Road 读取模式；Road GPKG 优先走只读取必要字段的 SQLite 轻量读取，拓扑阶段不得长期持有完整 Road 几何对象。
Tool5 错误 1 对多处理必须记录 `node_error_2_detection`、参与 intersection、合并组、忽略 `kind_2 = 1` 组、连通性跳过原因与删除 Road。
Tool6 必须记录 `错误分歧合流路口 / 错误交叉路口_T型路口 / 错误交叉路口_非交叉路口` 计数、CSV `是否修复` 默认值、连续分歧合流 suppressed 候选、交叉路口外侧角度分组判定、字段解析与参数阈值。
