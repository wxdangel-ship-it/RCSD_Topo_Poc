# 04 方案策略

本文件是 T08 的详细版需求 / 落地策略说明。凝练版业务需求见 `../SPEC.md`，稳定输入输出、工具入口和参数契约见 `../INTERFACE_CONTRACT.md`。

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

1. Roundabout aggregation：参考 T01，使用 `roadtype bit3` Road 连通组识别环岛，组内最小 Node `id` 作为 mainnode；多 node 环岛组才将 mainnode 写为 `kind_2 = 64`，单 node 环岛组保留初始化后的原 `kind / grade` 到 `kind_2 / grade_2`。

Tool3 命令脚本输出读取、初始化、环岛聚合与写出进度；Nodes GPKG 输出复用 T08 共享直接 SQLite GeoPackage 写出路径。

## Tool4

Tool4 读取 Tool3 之后的 Nodes 与对应 Roads，按语义路口分组计算入度 / 出度并修复类型错误；Tool6 质检成果可不输入，未输入时跳过人工确认修复：

1. `kind_2 = 2048` 的 T 型路口，若入度或出度任一不为 `2`，识别为错误 T 型路口。
2. 若错误 T 型路口入度或出度任一为 `0`，代表 node `kind_2` 写为 `1`；其他错误 T 型路口代表 node `kind_2` 写为 `4`。
3. `kind_2 in {8,16}` 且 `in_degree = 1 / out_degree = 1` 的分歧、合流路口，代表 node `kind_2` 写为 `1`。
4. 可选消费 Tool6 `node_error_tool6.csv / node_error_tool6.gpkg`：仅处理 `是否修复 = 1` 的记录；`错误分歧合流路口` 将分歧 node 作为 mainnode 写 `kind_2 = 2048`、合流 node 写 `kind_2 = 0 / grade_2 = 0` 并删除两者之间直连 Road；`错误交叉路口_T型路口` 写 `kind_2 = 2048`；`错误交叉路口_非交叉路口` 写 `kind_2 = 1`。

入度 / 出度按 Road `direction` 计算：`direction in {0,1}` 视为双向，出度和入度各加 `1`；`direction = 2` 为 `snodeid -> enodeid`；`direction = 3` 为 `enodeid -> snodeid`。若 Road 两端属于同一语义路口，则该 Road 既视为进入该语义路口也视为退出该语义路口，入度和出度各加 `1`。Tool4 copy-on-write 输出完整 Nodes/audit Nodes、可选 Roads 与 summary，不回写输入。

Tool4 对 `错误T型路口` 候选增加入出度异常豁免：若当前语义路口存在 `formway bit7 = 128` 的提前右转 Road，或 `road.kind` 任一 `|` 分隔 token 后两位为 `0a` 的辅路 Road，则排除这些 Road 后复算入度 / 出度；复算结果为 `in_degree = 2 / out_degree = 2` 时不输出错误，summary 记录 suppressed 审计。

## Tool5

Tool5 承接原 Tool3 的 Complex divmerge aggregation：参考 T04/T02 连续分歧 / 合流链路，沿 Road 有向拓扑聚合 representative `kind_2 in {8,16}` 候选，聚合主节点写为 `kind_2 = 128`。

Tool5 的错误 1 对多处理先复用 T02 `node_error_2` 生成口径：以输入 `RCSDIntersection` 面反向包含 / 接触 SWSD 语义路口，若一个面对应多组语义路口，则过滤代表 `kind_2 = 1` 的组，过滤后剩余组数大于 `1` 时生成一对多候选。随后复用 T02 离线修复口径，验证剩余组之间具有 Road 连通性后才合并 Nodes，并删除面内合并组之间的内部 Road。对 T02 判定为 `not_all_groups_connected` 的候选，Tool5 增加 T-pair 虚拟连通补充：两个 `kind_2 = 2048` 的 T 型路口若横方向一进一出 Road 的 `kind` 一致、各自横向夹角 `<=35°`、两组横向行驶方向相反且平行夹角 `<=20°`，则作为虚拟连通边参与本面剩余组连通判定，连通后按同一 1 对多口径合并。Tool5 copy-on-write 输出 Nodes/Roads/audit Nodes 和 summary，不回写输入；audit Nodes 记录复杂分歧 / 合流聚合与错误 1 对多处理实际涉及的 node，并补充处理过程、分组、角色与 source node id。

## Tool6

Tool6 读取 Nodes 与 Roads，按语义路口分组计算入度 / 出度，只输出人工质检候选，不改写输入数据。

1. 连续分歧合流质检：识别 `kind_2 = 16 / in_degree = 1 / out_degree = 2` 的分歧路口，沿退出左侧 road 在 `100m` 内追踪 `kind_2 = 8 / in_degree = 2 / out_degree = 1` 的合流路口，且分歧与合流距离不得超过 `100m`；再校验横方向共线、竖方向同端点或末端距离 `<20m` 且平行夹角 `<=20°`、竖方向位于横方向右侧。关联 road `kind` 后两位为 `17`，或竖方向为单向 road 且忽略二度连接后连通分歧 / 合流时 suppress。
2. 交叉路口质检：识别所有 `kind_2 = 4` 的语义路口，若关联 Road 数为 `1` 或 `2`，优先输出 `错误交叉路口_非交叉路口`；其余候选继续要求 `in_degree = 2 / out_degree = 2`，忽略道路方向后四个外侧角度方向不输出错误，仅两条双向 road 输出 `错误交叉路口_非交叉路口`，两个外侧角度方向均一进一出且为平行路关系时输出 `错误交叉路口_非交叉路口`，剩余候选符合右侧 T 型特征时输出 `错误交叉路口_T型路口`，否则不输出。
3. 输出 `node_error_tool6.csv / node_error_tool6.gpkg / node_error_summary_tool6.json`；CSV 最后一列 `是否修复` 默认 `1`，人工确认不需要修复的数据改为 `0` 后由 Tool4 后续修复流程消费。

## Tool7

Tool7 读取 SW C 表、SW Node 与 SW Road。C 表可以是非空间 GPKG 表；Tool7 只使用 C 表业务字段，不继承 GPKG 内部 `fid / geom` 字段。

1. 筛选 `CondType = 1` 的 C 表记录。
2. 校验 `inLinkID / outLinkID` 均存在于 SW Road 输入。
3. 将 inLink 几何定向到与 outLink 的最短端点连接处，将 outLink 从该连接处向外定向；端点重叠时去重拼接，端点不重叠时在两个端点之间追加直线连接。
4. 输出 `sw_restriction_tool7.gpkg / sw_restriction_summary_tool7.json`，不修改输入 C 表、SW Node 或 SW Road。

## Tool8

Tool8 读取 SW Laneinfo、SW Node 与 SW Road。Laneinfo 可以是非空间 GPKG 表；Tool8 只使用 Laneinfo 业务字段，不继承 GPKG 内部 `fid / geom` 字段。

1. 筛选 `LinkID` 存在于 SW Road 输入中的 Laneinfo 记录。
2. 按 `LinkID + Lane_Dir` 分组并按 `Seq_Nm` 升序处理，将每条记录的 `Arrow_Dir` 按英文逗号拆分为车道级 arrow 值，并重新以英文逗号拼接到同一 Road 方向输出记录的 `arrow` 字段。
3. 基于 SW Road `direction` 与 Laneinfo `Lane_Dir` 定向 Link 几何：`direction in {0,1,2}` 且 `Lane_Dir = 2` 使用原方向，`Lane_Dir = 3` 使用反向；`direction = 3` 时二者相反。
4. 输出 `sw_arrow_tool8.gpkg / sw_arrow_summary_tool8.json`，不修改输入 Laneinfo、SW Node 或 SW Road。

## Tool9

Tool9 读取 RCSDNode、RCSDRoad 与道路面 GPKG，并统一投影到 `EPSG:3857` 后执行清理。

1. RCSDNode 按 `mainnodeid` 聚合语义路口；`mainnodeid` 为空或 `0` 时按单 node 组处理。
2. 默认使用 `covers` 判定 node 是否被道路面覆盖，保留道路面边界上的 node；需要严格内部包含时可切换为 `contains`。
3. 语义路口组只有在组内所有 node 均被道路面覆盖 / 包含时整组保留，否则整组删除。
4. RCSDRoad 先按几何与道路面相交过滤，再按 `snodeid / enodeid` 是否均属于最终保留 node 集合过滤。
5. 输出 `rcsdnode_clean_tool9.gpkg / rcsdroad_clean_tool9.gpkg / rcsd_clean_summary_tool9.json`，不修改输入 RCSDNode、RCSDRoad 或道路面。

## 输出策略

- Tool1 输出同目录追加 `_tool1` 的目标格式文件与 summary。
- Tool2 输出四个 GPKG 与三个 summary，summary 包含阶段性能字段。
- Tool3 输出一个追加 `_tool3` 的 copy-on-write Nodes GPKG 与 summary，不输出或改写 Roads，summary 包含阶段性能字段。
- Tool4 输出追加 `_tool4` 的 copy-on-write Nodes/audit Nodes GPKG 与 summary；可选输出 Roads GPKG，且仅删除 Tool6 已确认连续分合流修复的直连 Road。
- Tool5 输出追加 `_tool5` 的 copy-on-write Nodes/Roads/audit Nodes GPKG 与 summary，summary 包含复杂聚合和错误 1 对多处理审计。
- Tool6 输出人工质检 CSV、目视审查 GPKG 与 summary，不输出修复后的 Nodes/Roads。
- Tool7 输出追加 `_tool7` 的显性 restriction GPKG 与 summary，不输出或改写 Nodes/Roads。
- Tool8 输出追加 `_tool8` 的 Road 方向级显性 arrow GPKG 与 summary，不输出或改写 Laneinfo/Nodes/Roads。
- Tool9 输出追加 `_tool9` 的清理后 RCSDNode / RCSDRoad GPKG 与 summary，不输出或改写输入道路面。
- 所有路径由命令参数提供。
