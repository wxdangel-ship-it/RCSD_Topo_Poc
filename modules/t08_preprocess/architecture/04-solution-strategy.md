# 04 方案策略

## Tool1

Tool1 使用参数化 SHP / GeoJSON / GPKG 列表作为输入，逐个流式读取、可选重投影，并将输出写回输入目录下的同名目标格式文件：SHP / GeoJSON 输出 GPKG，GPKG 输出 GeoJSON。命令脚本会输出单文件开始、定量要素转换进度、结束与失败信息。

GPKG 输出参考 T00 Tool7 的实现方式，采用直接 SQLite GeoPackage 写出路径生成标准 `gpkg_spatial_ref_sys / gpkg_contents / gpkg_geometry_columns` 元数据和几何 BLOB，避免 Fiona 逐要素 sink 写出的主要性能瓶颈。GeoJSON 输出采用流式 JSON 写出，避免反向转换继续经过 Fiona sink。

## Tool2

Tool2 分两步执行：

1. Patch join：按 `road.id = patch_road.road_id` 为 Road 写入 `patch_id`，未命中记录写入 unmatched 图层。
2. Kind enrich：对 Patch join 输出和原始 Kind Road 统一投影到 `EPSG:3857` 后执行空间匹配，写入 `kind`。

Tool2 命令脚本输出 Patch join / Kind enrich 阶段进度；Road / Raw Kind GPKG 优先采用直接 SQLite GeoPackage 快读，无法识别标准 GPKG 元数据时回退 Fiona；Patch join 对 Patch Road 采用属性流式索引，只读取 `road_id / patch_id` 并跳过几何构造与投影；Kind enrich 复用 raw Kind token 缓存与 STRtree 分块批量查询结果，summary 记录阶段耗时、吞吐与空间候选数；三个 GPKG 输出统一复用 T08 共享直接 SQLite GeoPackage 写出路径。

## Tool3

Tool3 先将 Nodes `kind / grade` 复制到 `kind_2 / grade_2`，再执行两类拓扑聚合：

1. Roundabout aggregation：参考 T01，使用 `roadtype bit3` Road 连通组识别环岛，组内最小 Node `id` 作为 mainnode。
2. Complex divmerge aggregation：参考 T04/T02 连续分歧 / 合流链路，沿 Road 有向拓扑聚合 representative `kind_2 in {8,16}` 候选，聚合主节点写为 `kind_2 = 128`。

Tool3 命令脚本输出读取、初始化、环岛聚合、复杂链聚合与写出进度；复杂链 component 组装使用 node-to-component 索引归集边，避免按组件反复全量扫描链路边；Nodes GPKG 输出复用 T08 共享直接 SQLite GeoPackage 写出路径。

## Tool4

Tool4 读取 Tool3 之后的 Nodes 与对应 Roads，按语义路口分组计算入度 / 出度并识别三类类型错误：

1. `kind = 2048` 的 T 型路口，若入度或出度任一不为 `2`，输出为错误 T 型路口。
2. `kind = 4` 的交叉路口，若入度和出度均为 `2`，输出为错误交叉路口。
3. `kind = 16` 分歧与 `kind = 8` 合流在 `100m` 内构成连续分歧合流且符合 T 型拓扑特征时，输出为错误分歧合流路口。

入度 / 出度按 Road `direction` 计算：`direction in {0,1}` 视为双向，出度和入度各加 `1`；`direction = 2` 为 `snodeid -> enodeid`；`direction = 3` 为 `enodeid -> snodeid`。Tool4 不回写 Nodes，不重塑 Roads，只输出 `nodes_error.gpkg` 与 summary。

连续分歧合流的第一版几何判定不引入未确认上游左右字段：以入向 road 与两个退出 road 的夹角最小者作为横向 / 左侧候选，另一条作为竖向 / 右侧候选，并在 summary 中记录相关 road 与角度参数，便于后续如有明确左右字段时替换。

## 输出策略

- Tool1 输出同目录同名目标格式文件与 summary。
- Tool2 输出三个 GPKG 与三个 summary，summary 包含阶段性能字段。
- Tool3 输出一个 copy-on-write Nodes GPKG 与 summary，不输出或改写 Roads，summary 包含阶段性能字段。
- Tool4 输出 `nodes_error.gpkg` 与 summary，不输出修复后 Nodes/Roads。
- 所有路径由命令参数提供。
