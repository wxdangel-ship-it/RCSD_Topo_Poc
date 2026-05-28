# 04 方案策略

## Tool1

Tool1 使用参数化 SHP / GeoJSON / GPKG 列表作为输入，逐个流式读取、可选重投影，并将输出写回输入目录下追加 `_tool1` 的目标格式文件：SHP / GeoJSON 输出 GPKG，GPKG 输出 GeoJSON。命令脚本会输出单文件开始、定量要素转换进度、结束与失败信息。

GPKG 输出参考 T00 Tool7 的实现方式，采用直接 SQLite GeoPackage 写出路径生成标准 `gpkg_spatial_ref_sys / gpkg_contents / gpkg_geometry_columns` 元数据和几何 BLOB，避免 Fiona 逐要素 sink 写出的主要性能瓶颈。GeoJSON 输出采用流式 JSON 写出，避免反向转换继续经过 Fiona sink。

## Tool2

Tool2 分两步执行：

1. Patch join：按 `road.id = patch_road.road_id` 为 Road 写入 `patch_id`，未命中记录写入 unmatched 图层。
2. Kind enrich：对 Patch join 输出和原始 Kind Road 统一投影到 `EPSG:3857` 后执行空间匹配，写入 `kind`。
3. Event Road split：若 Road `kind` 中任一 `|` 分隔 token 的后两位为 `17`，则从主 Kind 输出删除该 Road，并写入 `event_road_0a_tool2.gpkg`。

Tool2 命令脚本输出 Patch join / Kind enrich 阶段进度；Road / Raw Kind GPKG 优先采用直接 SQLite GeoPackage 快读，无法识别标准 GPKG 元数据时回退 Fiona；Patch join 对 Patch Road 采用属性流式索引，只读取 `road_id / patch_id` 并跳过几何构造与投影；Kind enrich 复用 raw Kind token 缓存与 STRtree 分块批量查询结果，summary 记录阶段耗时、吞吐、空间候选数与事件 Road 删除数；四个 GPKG 输出统一复用 T08 共享直接 SQLite GeoPackage 写出路径。

## Tool3

Tool3 先将 Nodes `kind / grade` 复制到 `kind_2 / grade_2`，再执行环岛拓扑聚合：

1. Roundabout aggregation：参考 T01，使用 `roadtype bit3` Road 连通组识别环岛，组内最小 Node `id` 作为 mainnode。

Tool3 命令脚本输出读取、初始化、环岛聚合与写出进度；Nodes GPKG 输出复用 T08 共享直接 SQLite GeoPackage 写出路径。

## Tool4

Tool4 读取 Tool3 之后的 Nodes 与对应 Roads，按语义路口分组计算入度 / 出度并修复类型错误：

1. `kind_2 = 2048` 的 T 型路口，若入度或出度任一不为 `2`，识别为错误 T 型路口。
2. 若错误 T 型路口入度或出度任一为 `0`，代表 node `kind_2` 写为 `1`；其他错误 T 型路口代表 node `kind_2` 写为 `4`。

入度 / 出度按 Road `direction` 计算：`direction in {0,1}` 视为双向，出度和入度各加 `1`；`direction = 2` 为 `snodeid -> enodeid`；`direction = 3` 为 `enodeid -> snodeid`。若 Road 两端属于同一语义路口，则该 Road 既视为进入该语义路口也视为退出该语义路口，入度和出度各加 `1`。Tool4 copy-on-write 输出完整 Nodes/audit Nodes 与 summary，不回写输入，不重塑 Roads。

Tool4 对 `错误T型路口` 候选增加入出度异常豁免：若当前语义路口存在 `formway bit7 = 128` 的提前右转 Road，或 `road.kind` 任一 `|` 分隔 token 后两位为 `0a` 的辅路 Road，则排除这些 Road 后复算入度 / 出度；复算结果为 `in_degree = 2 / out_degree = 2` 时不输出错误，summary 记录 suppressed 审计。

## Tool5

Tool5 承接原 Tool3 的 Complex divmerge aggregation：参考 T04/T02 连续分歧 / 合流链路，沿 Road 有向拓扑聚合 representative `kind_2 in {8,16}` 候选，聚合主节点写为 `kind_2 = 128`。

Tool5 的错误 1 对多处理先复用 T02 `node_error_2` 生成口径：以输入 `RCSDIntersection` 面反向包含 / 接触 SWSD 语义路口，若一个面对应多组语义路口，则过滤代表 `kind_2 = 1` 的组，过滤后剩余组数大于 `1` 时生成一对多候选。随后复用 T02 离线修复口径，验证剩余组之间具有 Road 连通性后才合并 Nodes，并删除面内合并组之间的内部 Road。Tool5 copy-on-write 输出 Nodes/Roads/audit Nodes 和 summary，不回写输入；audit Nodes 记录复杂分歧 / 合流聚合与错误 1 对多处理实际涉及的 node，并补充处理过程、分组、角色与 source node id。

## Tool6

Tool6 读取 Nodes 与 Roads，按语义路口分组计算入度 / 出度，只输出人工质检候选，不改写输入数据。

1. 连续分歧合流质检：识别 `kind_2 = 16 / in_degree = 1 / out_degree = 2` 的分歧路口，沿退出左侧 road 在 `100m` 内追踪 `kind_2 = 8 / in_degree = 2 / out_degree = 1` 的合流路口，且分歧与合流距离不得超过 `100m`；再校验横方向共线、竖方向同端点或末端距离 `<20m` 且平行夹角 `<=20°`、竖方向位于横方向右侧。关联 road `kind` 后两位为 `17` 时 suppress。
2. 交叉路口质检：识别 `kind_2 = 4` 且 `in_degree = 2 / out_degree = 2` 的语义路口；四个不同角度方向不输出错误；符合右侧 T 型特征输出 `错误交叉路口_T型路口`，其余输出 `错误交叉路口_非交叉路口`。
3. 输出 `node_error_tool6.csv / node_error_tool6.gpkg / node_error_summary_tool6.json`；CSV 最后一列 `是否修复` 默认 `1`，人工确认不需要修复的数据改为 `0` 后由 Tool4 后续修复流程消费。

## 输出策略

- Tool1 输出同目录追加 `_tool1` 的目标格式文件与 summary。
- Tool2 输出四个 GPKG 与三个 summary，summary 包含阶段性能字段。
- Tool3 输出一个追加 `_tool3` 的 copy-on-write Nodes GPKG 与 summary，不输出或改写 Roads，summary 包含阶段性能字段。
- Tool4 输出追加 `_tool4` 的 copy-on-write Nodes/audit Nodes GPKG 与 summary，不输出或改写 Roads。
- Tool5 输出追加 `_tool5` 的 copy-on-write Nodes/Roads/audit Nodes GPKG 与 summary，summary 包含复杂聚合和错误 1 对多处理审计。
- Tool6 输出人工质检 CSV、目视审查 GPKG 与 summary，不输出修复后的 Nodes/Roads。
- 所有路径由命令参数提供。
