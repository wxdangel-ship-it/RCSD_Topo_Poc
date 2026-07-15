# T08 - INTERFACE_CONTRACT

## 定位

`t08_preprocess` 是项目正式预处理模块。模块内部以工具形式提供能力，但这些工具属于项目正式组成部分，不是一次性实验脚本。

## 0. 成果输出命名约束

除输入文件本身外，T08 成果输出文件名默认必须在扩展名前以 `_toolX` 结尾，`X` 为工具编号。例如 Tool2 的事件 Road 输出为 `event_road_0a_tool2.gpkg`。Tool1 是格式转换特例：转换成果使用输入文件同 stem、不同格式后缀；Tool10 是用户指定的 Patch 落盘特例：聚合成果固定为 `<Patch>/Traj/raw_dat_pose.gpkg`。Tool1 / Tool10 summary 仍分别按 `_tool1 / _tool10` 命名。

## 1. 当前工具

### Tool1：基础矢量格式转换

- 输入：一个或多个 `.shp / .geojson / .json / .gpkg` 文件，全部通过参数提供。
- 支持转换：
  - `.shp -> <input_dir>/<input_stem>.gpkg`
  - `.geojson / .json -> <input_dir>/<input_stem>.gpkg`
  - `.gpkg -> <input_dir>/<input_stem>.geojson`
- 输出边界：所有转换成果均写回输入文件所在目录下，使用输入文件同 stem、不同格式后缀；不合并多个输入，不提供输出目录参数，不提供逐文件自定义输出路径参数；若同一轮输入会导致重复输出或输出覆盖本轮任一输入，必须报错停止。
- CRS：
  - 默认保留输入 CRS。
  - 如传入 `--target-epsg`，则输出投影到该 EPSG。
  - 输入缺失 CRS 时，必须通过 `--default-crs` 提供 CRS。
- 输出摘要：JSON summary，记录输入、输出、CRS、图层名、要素数与失败原因。
- 性能口径：SHP / GeoJSON 转 GPKG 使用直接 SQLite GeoPackage 写出路径，GPKG 转 GeoJSON 使用流式 JSON 写出路径；转换过程不得依赖 Fiona 逐要素 sink 写出作为主路径。

### Tool2：Road 数据预处理

- 输入一：一层 Road GPKG，依赖字段 `id`。
- 输入二：Patch Road GPKG，依赖字段 `road_id / patch_id`。
- 输入三：原始 Road Kind GPKG，依赖字段 `Kind` 或 `kind`。
- 输出：
  - `t08_road_patch_tool2.gpkg`
  - `t08_road_patch_unmatched_tool2.gpkg`
  - `t08_road_patch_kind_tool2.gpkg`
  - `event_road_0a_tool2.gpkg`
  - `t08_road_patch_summary_tool2.json`
  - `t08_road_kind_summary_tool2.json`
  - `t08_road_preprocess_summary_tool2.json`
- 输出 CRS：`EPSG:3857`。
- 删除规则：Kind enrich 后，若 Road `kind` 任一 `|` 分隔 token 的后两位为 `17`，则从 `t08_road_patch_kind_tool2.gpkg` 删除该 Road，并将被删除 Road 输出到 `event_road_0a_tool2.gpkg`。
- 所有输入、输出路径必须通过参数提供。

### Tool3：Nodes 类型聚合

- 输入一：Nodes GPKG，依赖字段 `id / kind / grade`，可选字段 `mainnodeid / has_evd / is_anchor / subnodeid / closed_con / closed_connect`。`closed_connect` 是 `closed_con` 的正式输入别名；仅存在别名时 copy-on-write 新增 `closed_con`，两字段同时存在且值不一致时失败，原始字段不删除。
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`；环岛聚合使用可选字段 `roadtype`。
- 输出：
  - `t08_nodes_type_aggregation_tool3.gpkg`
  - `t08_nodes_type_aggregation_summary_tool3.json`
- 输出 CRS：`EPSG:3857`。
- 类型初始化：新增或覆盖 `kind_2 / grade_2`，初始值分别复制自 `kind / grade`，原始 `kind / grade` 不改写；同时执行 `closed_connect -> closed_con` 规范化。
- 环岛聚合：参考 T01 环岛构建，按 `roadtype bit3` 的 Road 连通组聚合；组内最小 Node `id` 为 `mainnode`，全组 `mainnodeid` 写为 mainnode。若聚合后环岛语义路口包含多个 node，mainnode 写 `grade_2 = 1 / kind_2 = 64`，成员写 `grade_2 = 0 / kind_2 = 0`；若聚合后环岛语义路口只有一个 node，则该 node 继承初始化后的原 `kind / grade` 到 `kind_2 / grade_2`，不变更为环岛类型。
- 输出边界：Tool3 只输出 copy-on-write Nodes，不修改输入文件，不输出或改写 Roads。
- 输入 Road 引用不存在的端点 Node 时，Tool3 不得删除 Road、补造 Node 或终止整个批次；该 Road 只从环岛拓扑计算中跳过，并在 summary `roundabout.topology_missing_endpoint_*` 与 `roadtype_issue_rows.action=ignored_for_roundabout_topology_only` 中审计。`counts.road_feature_count` 仍统计完整 Road 输入。
- 所有输入、输出路径必须通过参数提供。

### Tool4：路口类型修复

- 输入一：Nodes GPKG，依赖字段 `id / kind_2`，可选字段 `mainnodeid`。
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`，可选字段 `formway / kind`。
- 输入三：Tool6 `node_error` CSV/GPKG，可选；未输入时仅执行 Tool4 自身识别与修复。
- 输出：
  - `t08_junction_type_repair_nodes_tool4.gpkg`
  - `t08_junction_type_repair_roads_tool4.gpkg`（可选；Tool6 连续分合流修复删除 Road 时必须提供）
  - `t08_junction_type_repair_audit_nodes_tool4.gpkg`
  - `t08_junction_type_repair_summary_tool4.json`
- 输出 CRS：`EPSG:3857`。
- 入度 / 出度定义：
  - `direction in {0,1}` 表示双向 road，对两端语义路口分别 `in_degree + 1 / out_degree + 1`。
  - `direction = 2` 表示 `snodeid -> enodeid`，source 语义路口 `out_degree + 1`，target 语义路口 `in_degree + 1`。
  - `direction = 3` 表示 `enodeid -> snodeid`，source 语义路口 `out_degree + 1`，target 语义路口 `in_degree + 1`。
  - 若 Road 两端属于同一语义路口，则该 Road 既视为进入该语义路口也视为退出该语义路口，`in_degree + 1 / out_degree + 1`；双向 Road 同样只按该 Road 对入度和出度各加 `1`。
- 错误识别：
  - `kind_2 = 2048`：若入度或出度任一不为 `2`，识别为 `error_type = 错误T型路口`。
  - `kind_2 in {8,16}`：若入度和出度均为 `1`，识别为 `error_type = 错误分歧合流路口_一入一出`。
- 修复策略：
  - 对识别出的错误 T 型路口代表 node，若入度或出度任一为 `0`，`kind_2` 写为 `1`。
  - 其他错误 T 型路口代表 node，`kind_2` 写为 `4`。
  - 对识别出的 `错误分歧合流路口_一入一出` 代表 node，`kind_2` 写为 `1`。
  - 若输入 Tool6 成果中 `error_type = 错误分歧合流路口` 且同组记录 `是否修复 = 1`，将分歧和合流涉及 node 的 `mainnodeid` 写为原分歧 node id，原分歧 node `kind_2 = 2048`，原合流 node `kind_2 = 0 / grade_2 = 0`，并从 Roads 输出中删除原分歧与合流语义路口之间的直连 Road。
  - 若输入 Tool6 成果中 `error_type = 错误交叉路口_T型路口` 且 `是否修复 = 1`，对应 mainnode `kind_2 = 2048`。
  - 若输入 Tool6 成果中 `error_type = 错误交叉路口_非交叉路口` 且 `是否修复 = 1`，对应 mainnode `kind_2 = 1`。
  - 若输入 Tool6 成果中 `error_type = 错误交叉路口_分歧路口` 且 `是否修复 = 1`，对应 mainnode `kind_2 = 16`。
  - 若输入 Tool6 成果中 `error_type = 错误交叉路口_合流路口` 且 `是否修复 = 1`，对应 mainnode `kind_2 = 8`。
- 异常豁免：
  - 若语义路口存在提前右转 Road，Tool4 对该语义路口执行入度 / 出度复算时不计入提前右转 Road；提前右转 Road 以 `formway bit7 = 128` 判定。
  - 若语义路口存在辅路 Road，Tool4 对该语义路口执行入度 / 出度复算时不计入辅路 Road；辅路 Road 以 `road.kind` 任一 `|` 分隔 token 的后两位为 `0a` 判定，大小写不敏感。
  - 对原本将输出的 `错误T型路口` 候选，若排除提前右转 / 辅路后 `in_degree = 2 / out_degree = 2`，则不输出错误，并在 summary `degree_exceptions` 中记录 suppressed 审计。
- 审计 Nodes 输出：将被修复的语义路口代表 node 输出为 audit Nodes GPKG，保留最终 Nodes 属性并补充 `audit_id / audit_process / audit_group_id / audit_role / audit_mainnodeid / audit_source_node_id`；修复前后 `kind_2` 与入出度记录在 summary `repairs / errors`，Tool6 触发的修复记录在 `repairs / tool6_skipped / deleted_road_ids`。
- 输出边界：Tool4 copy-on-write 输出完整 Nodes 与 audit Nodes；仅当提供 `--roads-output` 时输出 copy-on-write Roads，且只删除 Tool6 连续分合流修复确认的直连 Road；不修改输入 Nodes/Roads。
- 性能口径：Tool4 Road GPKG 优先使用直接 SQLite 轻量读取，只读取 `id / snodeid / enodeid / direction / formway / kind / geometry`，进入拓扑前仅保留 road 长度、方向向量与异常豁免标记，不长期持有完整 Road 几何；无法识别标准 GPKG 元数据时回退共享 `read_vector`。
- 所有输入、输出路径必须通过参数提供。

### Tool5：复杂路口预处理

- 输入一：Nodes GPKG，依赖字段 `id / kind / grade / mainnodeid / subnodeid`，可选字段 `kind_2 / grade_2 / has_evd / is_anchor`；若 `kind_2 / grade_2` 缺失，则先从 `kind / grade` 初始化。
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`，可选字段 `kind`；错误 1 对多 T-pair 虚拟连通补充判定依赖 `kind`，缺失时不执行该补充判定。
- 输入三：`RCSDIntersection` GPKG，可选；启用错误 1 对多识别与处理时必填。
- 输入四：`node_error_2` GPKG，可选兼容输入，依赖字段 `id / junction_id`；未提供时 Tool5 按 T02 `node_error_2` 生成口径基于 `RCSDIntersection` 即时识别。
- 输出：
  - `t08_complex_junction_nodes_tool5.gpkg`
  - `t08_complex_junction_roads_tool5.gpkg`
  - `t08_complex_junction_audit_nodes_tool5.gpkg`
  - `t08_complex_junction_preprocess_summary_tool5.json`
- 输出 CRS：`EPSG:3857`。
- 复杂分歧 / 合流聚合：从 Tool3 移出，参考 T04 full-input 候选与连续链路口口径，对 representative node 的 `kind_2 in {8, 16}` 候选沿 Road 有向拓扑识别连续链，聚合后 mainnode 写 `kind_2 = 128`，成员写 `grade_2 = 0 / kind_2 = 0`，全组 `mainnodeid` 写为 mainnode。若输入存在 `has_evd / is_anchor` 字段，则候选需满足 `has_evd = yes / is_anchor = no`。
- 错误 1 对多路口处理：参考 T02 `node_error_2` 生成逻辑，先用 `RCSDIntersection` 反向包含 / 接触 SWSD 语义路口；若一个面对应不止一组语义路口，则忽略代表 `kind_2 = 1` 的组，过滤后剩余组数大于 `1` 时生成一对多候选；随后复用 T02 离线修复逻辑，只有剩余组之间具备 Road 连通性时才合并，选择最小 junction group 作为 mainnode，mainnode 写 `kind_2 = 4`，成员写 `kind_2 = 0 / grade_2 = 0`，删除 intersection 面内被合并组之间的内部 Road。若 T02 连通性判定为 `not_all_groups_connected`，Tool5 额外对候选中任意两个 `kind_2 = 2048` 的 T 型路口执行横方向 Road 判定：两者横向一进一出 Road 的 `kind` 规范化后相同、各自横向夹角 `<=35°`、两组横向行驶方向相反且平行夹角 `<=20°` 时，将该 T-pair 视为虚拟连通边；虚拟连通边与真实 Road 连通性共同使剩余组全连通时，按同一 1 对多修复口径合并。
- 审计 Nodes 输出：将复杂分歧 / 合流聚合与错误 1 对多处理实际涉及的 node 输出为 audit Nodes GPKG，保留最终 Nodes 属性并补充 `audit_id / audit_process / audit_group_id / audit_role / audit_mainnodeid / audit_source_node_id`。
- 输出边界：Tool5 copy-on-write 输出 Nodes 与 Roads，不修改输入文件；若未传入 `RCSDIntersection`，只执行复杂分歧 / 合流聚合并复制输出 Roads。
- 所有输入、输出路径必须通过参数提供。

### Tool6：Nodes 数据类型质检

- 输入一：Nodes GPKG，依赖字段 `id / kind_2`，可选字段 `mainnodeid`；字段名固定使用小写 `kind_2`，不兼容 `Kind_2`。
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`，可选字段 `kind`。
- 输出：
  - `node_error_tool6.csv`
  - `node_error_tool6.gpkg`
  - `node_error_summary_tool6.json`
- 输出 CRS：`EPSG:3857`。
- 输出边界：Tool6 只输出质检候选，不改写输入 Nodes/Roads，不执行修复；CSV 最后一列为 `是否修复`，默认值为 `1`，人工确认不需要修复的数据改为 `0` 后供 Tool4 后续修复流程消费。
- 下游边界：Tool4 可消费 Tool6 人工确认结果；Tool6 本身不执行修复。
- 入度 / 出度定义：
  - `direction in {0,1}` 表示双向 road，对两端语义路口分别 `in_degree + 1 / out_degree + 1`。
  - `direction = 2` 表示 `snodeid -> enodeid`，source 语义路口 `out_degree + 1`，target 语义路口 `in_degree + 1`。
  - `direction = 3` 表示 `enodeid -> snodeid`，source 语义路口 `out_degree + 1`，target 语义路口 `in_degree + 1`。
  - 若 Road 两端属于同一语义路口，则该 Road 既视为进入该语义路口也视为退出该语义路口，`in_degree + 1 / out_degree + 1`；双向 Road 同样只按该 Road 对入度和出度各加 `1`。
- 连续分歧合流类型质检：
  - 识别 `kind_2 = 16` 且 `in_degree = 1 / out_degree = 2` 的分歧语义路口。
  - 以进入分歧路口 road 的方向为参考，将两个退出 road 分为左侧 road 与右侧 road；沿左侧 road 前进方向跟踪，忽略二度连接，`100m` 内找到 `kind_2 = 8` 且 `in_degree = 2 / out_degree = 1` 的合流语义路口时形成连续分合流候选；分歧与合流路口之间距离不得超过 `100m`。
  - 进入分歧 road、分歧左侧退出 road、合流退出 road 需构成横方向；默认横向夹角阈值为 `35°`。
  - 沿分歧右侧退出 road 前进方向跟踪，并沿合流右侧进入 road 的退出方向反向跟踪；若两者跟踪至相同语义路口，或两者末端距离小于起点距离、末端距离 `<20m` 且平行夹角 `<=20°`，则视为具备 T 型竖方向。
  - 若关联 road 的 `road.kind` 任一 `|` 分隔 token 后两位为 `17`，则 suppress，不输出错误。
  - 若竖方向道路不在横方向前进方向右侧，则 suppress，不输出错误。
  - 若 T 型竖方向为单向道路，且忽略二度连接后该竖方向直接连通分歧与合流语义路口，则 suppress，不输出错误。
  - 命中输出 `error_type = 错误分歧合流路口`，同一组连续分合流默认输出 diverge/merge 两条 node 质检记录并共享 `error_group_id`。
- 交叉路口类型质检：
  - 识别所有 `kind_2 = 4` 的语义路口；若该语义路口关联 Road 数为 `1` 或 `2`，优先输出 `error_type = 错误交叉路口_非交叉路口`。
  - 若候选关联 Road 均为单向 Road，且 `in_degree = 1 / out_degree >= 2`，则输出 `error_type = 错误交叉路口_分歧路口`；若 `out_degree = 1 / in_degree >= 2`，则输出 `error_type = 错误交叉路口_合流路口`。
  - 未命中低关联、分歧路口或合流路口规则的其余交叉候选，继续要求 `in_degree = 2 / out_degree = 2` 才进入后续交叉 / T 型模式判定。
  - 若进入和退出 road 在路口处忽略道路方向后形成四个不同外侧角度方向，则视为真实交叉路口，不输出错误。
  - 若关联 road 只有两条双向 road，则输出 `error_type = 错误交叉路口_非交叉路口`。
  - 若忽略道路方向后只有两个外侧角度方向，两个角度方向均具备一进一出关系，且两组方向为平行路关系，则输出 `error_type = 错误交叉路口_非交叉路口`。
  - 若符合 T 型路口特征：横方向为一条单向进入 road 与一条单向退出 road，竖方向为双向平行单向 road 或一条双向 road，且竖方向 road 位于横方向前进方向右侧，则输出 `error_type = 错误交叉路口_T型路口`。
  - 对 `kind_2 = 4 / in_degree = 2 / out_degree = 2` 且端点 20m 外侧角度只聚成两个方向组的候选，若存在一进一出的竖方向 Road 指向同一远端语义路口，且基于 Road 全长方向向量满足竖方向平行、剩余横方向一进一出近似共线、竖方向在横方向右侧，则同样输出 `error_type = 错误交叉路口_T型路口`；该 fallback 仅用于处理路口端点短距离弯出导致的 T 型漏判，audit 中以 `t_pattern_source = same_remote_semantic_full_road_vector` 标识。
  - 三个外侧角度方向的候选只能输出 `错误交叉路口_T型路口` 或不输出；两个外侧角度方向的候选只能在上述明确条件下输出 `错误交叉路口_T型路口 / 错误交叉路口_非交叉路口`，否则不输出。
  - 交叉路口错误输出的 `audit_json` 必须包含 `outward_angle_group_count / outward_angle_threshold_degrees / outward_vector_source / outward_vector_trace_distance_m / angle_groups`；角度方向使用 road 几何在路口端点向外延伸 `20m` 的局部向量，不直接使用进入 / 退出通行方向；每个 angle group 必须记录 `road_ids / has_in / has_out / members / merge_reasons`，用于追溯角度方向合并原因。
- summary 必须记录输入、输出、参数、字段解析、CRS、错误类型计数、suppressed 连续分合流候选与性能字段。
- 所有输入、输出路径必须通过参数提供。

### Tool7：交通限制显性化

- 输入一：SW C 表 GPKG，依赖字段 `CondType / inLinkID / outLinkID`；C 表可以是非空间 GPKG 表。
- 输入二：SW Node GPKG，用于输入审计与 CRS / 计数追溯。
- 输入三：SW Road GPKG，依赖字段 `id` 或 `linkid / LinkID`，必须包含 Link 几何。
- 输出：
  - `sw_restriction_tool7.gpkg`
  - `sw_restriction_summary_tool7.json`
- 输出 CRS：`EPSG:3857`。
- 处理规则：
  - 仅处理 C 表中 `CondType = 1` 的记录。
  - `inLinkID / outLinkID` 必须同时存在于 SW Road 输入中，否则跳过并写入 summary 计数。
  - restriction 输出记录全量继承 C 表业务字段，不继承 GPKG 内部 `fid / geom` 字段。
  - restriction 几何基于 `inLinkID` 与 `outLinkID` 对应 Road 几何构建 LineString；按两条 Link 端点最短距离确定连接端点，将 inLink 定向到连接端点、outLink 从连接端点向外，端点不重叠时在两端点之间追加直线连接。
- 输出边界：Tool7 只输出显性 restriction GPKG 与 summary，不修改输入 C 表 / SW Node / SW Road。
- summary 必须记录输入、输出、参数、字段解析、CRS、C 表记录数、`CondType=1` 记录数、Road 命中 / 缺失计数、无效几何计数、restriction 输出计数与性能字段。
- 所有输入、输出路径必须通过参数提供。

### Tool8：Laneinfo 箭头显性化

- 输入一：SW Laneinfo GPKG，依赖字段 `LinkID / Seq_Nm / Arrow_Dir / Lane_Dir`；Laneinfo 可以是非空间 GPKG 表。
- 输入二：SW Node GPKG，用于输入审计与 CRS / 计数追溯。
- 输入三：SW Road GPKG，依赖字段 `id` 或 `linkid / LinkID`、`direction`，必须包含 Link 几何。
- 输出：
  - `sw_arrow_tool8.gpkg`
  - `sw_arrow_summary_tool8.json`
- 输出 CRS：`EPSG:3857`。
- 处理规则：
  - 仅处理 `Laneinfo.LinkID` 存在于 SW Road 输入中的 Lane 记录；缺失 Link 写入 summary 计数并跳过。
  - 按 `LinkID + Lane_Dir` 分组后以 `Seq_Nm` 升序处理；每条 Lane 记录的 `Arrow_Dir` 按英文逗号 `,` 分割为车道级 arrow 值，同一组只输出一条 LineString 要素。
  - `arrow` 字段按 `Seq_Nm` 顺序记录该 Road 方向的全部车道级 arrow 值，中间用英文逗号 `,` 分隔。
  - Tool8 不解释或改写 `Arrow_Dir` 字母大小写；下游 T09 消费 `arrow` 字段时按大小写不敏感方式归一到小写箭头码表，已确认 `A` 等同于 `a`。
  - arrow 输出字段至少包含 `linkid / lane_dir / road_direction / arrow / lane_count / seq_start / seq_end / source_arrow_dir`。
  - Link 为单向顺行（`direction = 2`）时，`Lane_Dir = 2` 按 Link 几何方向输出，`Lane_Dir = 3` 按 Link 几何反向输出。
  - Link 为单向逆向（`direction = 3`）时，`Lane_Dir = 2` 按 Link 几何反向输出，`Lane_Dir = 3` 按 Link 几何方向输出。
  - Link 为双向（`direction in {0,1}`）时，`Lane_Dir = 2` 按 Link 几何方向输出，`Lane_Dir = 3` 按 Link 几何反向输出。
- 输出边界：Tool8 只输出显性 arrow GPKG 与 summary，不修改输入 Laneinfo / SW Node / SW Road。
- summary 必须记录输入、输出、参数、字段解析、CRS、Lane 记录数、SW Road id 索引规模、缺失 Link 数、无效方向 / 几何 / 空 arrow 计数、arrow 输出计数与性能字段。
- 所有输入、输出路径必须通过参数提供。

### Tool9：RCSD 数据清理

- 输入一：RCSDNode GPKG，依赖字段 `id`，可选字段 `mainnodeid`。
- 输入二：RCSDRoad GPKG，依赖字段 `id / snodeid / enodeid`。
- 输入三：道路面 GPKG，必须包含 Polygon / MultiPolygon 几何。
- 输出：
  - `rcsdnode_clean_tool9.gpkg`
  - `rcsdroad_clean_tool9.gpkg`
  - `rcsd_clean_summary_tool9.json`
- 输出 CRS：`EPSG:3857`。
- 处理规则：
  - RCSDNode 默认使用 `covers` 判定是否被道路面覆盖，因此位于道路面边界上的 node 默认保留；如需严格内部包含，可通过 `--node-predicate contains` 切换。
  - 若 node 的 `mainnodeid` 为空或 `0`，按该 node 自身作为单节点组判定。
  - 若 node 的 `mainnodeid` 非空且非 `0`，按 `mainnodeid` 聚合为语义路口组；只有该组所有 node 均被道路面覆盖 / 包含时，整组 node 才保留，否则整组删除。
  - RCSDRoad 先按几何与道路面相交判定候选；不相交的 Road 删除。
  - 相交候选 Road 继续校验 `snodeid / enodeid`：只有起终点 node 均在最终保留 node 集合内时，该 Road 才保留。
- 输出边界：Tool9 copy-on-write 输出清理后的 RCSDNode / RCSDRoad 与 summary，不修改输入 RCSDNode / RCSDRoad / 道路面。
- summary 必须记录输入、输出、参数、字段解析、CRS、node 覆盖计数、语义组保留 / 删除计数、Road 相交计数、端点过滤计数、输出 bounds 与性能字段。
- 所有输入、输出路径必须通过参数提供。

### Tool10：Patch 轨迹聚合

- 输入：一个具体 Patch 目录，固定扫描 `<Patch>/Traj/*/raw_dat_pose.geojson`。
- 输出：
  - `<Patch>/Traj/raw_dat_pose.gpkg`，仅包含 `raw_dat_pose` 图层；
  - `<Patch>/Traj/raw_dat_pose_summary_tool10.json`。
- 输出 CRS / 几何：`EPSG:3857 LineStringZ`；同一 Patch 的全部轨迹段聚合在一个 GPKG、一个图层中。
- 输入约束：
  - 输入必须为 GeoJSON FeatureCollection，所有要素必须为非空 Point；
  - 每个 Point 必须有有限 X/Y/Z；缺 Z 或非有限 Z 整批失败，不补零、不跳过；
  - GeoJSON 必须显式声明 CRS；仅当调用方提供 `default_crs_text / --default-crs` 时允许补充缺失 CRS，不允许按坐标范围推断；
  - 每条源轨迹至少包含 2 个点。
- 排序：逐点按 `seq -> frame_id -> idx -> index -> timestamp -> feature index` 的优先级获得排序值并稳定排序；summary 记录实际排序来源。
- 断点：XY 转换到 `EPSG:3857` 后，相邻点距离大于 `10m`、可解析时间间隔大于 `1s`、序号间隔大于 `20,000,000` 时切段；时间不可解析且序号连续时，距离阈值放宽为 `25m`。阈值可由 callable / 脚本参数显式覆盖。
- 点数守恒：每个输出段至少 2 点；若切分产生单点段，该点不写入 `LineStringZ` 图层，也不得与相邻段跨断点拼接或复制成退化线，必须在 summary 中逐点记录来源、XYZ、排序信息、前后断点原因和排除原因。输出前必须验证 `output_point_count + discarded_single_point_count = input_point_count`。
- Z 语义：只转换 X/Y；Z 按输入浮点值原样写入 LineStringZ，不平滑、不插值、不做垂向坐标变换。
- 输出段字段：`traj_id / source_traj_id / segment_index / point_count / split_applied / order_source / start_seq / end_seq / start_timestamp / end_timestamp / drive_ids / split_reason_before / source_path`。
- 写入边界：先完成全部输入校验，再写同目录临时 GPKG / summary，成功后替换正式成果；默认拒绝已有输出，只有 `overwrite=True / --overwrite` 才允许替换。任何失败必须清理临时文件且保留已有正式成果。
- summary 必须记录输入文件及大小、CRS 与来源、点数、Z 范围、排序来源、断点原因、被排除单点段明细、点数守恒、参数、输出、运行环境、阶段耗时和 points/s。

## 2. EntryPoints

运行前先在 repo root 执行：

```bash
make env-sync
make doctor
```

Tool1：

```bash
.venv/bin/python scripts/t08_tool1_vector_convert.py \
  --input-shp /mnt/d/TestData/POC_Data/input/A.shp \
  --input-shp /mnt/d/TestData/POC_Data/input/B.shp \
  --input-geojson /mnt/d/TestData/POC_Data/input/C.geojson \
  --input-gpkg /mnt/d/TestData/POC_Data/input/D.gpkg
```

Tool2：

```bash
.venv/bin/python scripts/t08_tool2_road_preprocess.py \
  --road-gpkg /mnt/d/TestData/POC_Data/input/road.gpkg \
  --patch-road-gpkg /mnt/d/TestData/POC_Data/input/patch_road.gpkg \
  --raw-kind-road-gpkg /mnt/d/TestData/POC_Data/input/raw_kind_road.gpkg \
  --road-patch-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_tool2.gpkg \
  --road-patch-unmatched-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_unmatched_tool2.gpkg \
  --road-patch-kind-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_kind_tool2.gpkg \
  --event-road-0a-output /mnt/d/TestData/POC_Data/t08_preprocess/road/event_road_0a_tool2.gpkg
```

Tool3：

```bash
.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/input/nodes.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/input/roads.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_nodes_type_aggregation_tool3.gpkg
```

Tool4：

```bash
.venv/bin/python scripts/t08_tool4_junction_type_repair.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_nodes_type_aggregation_tool3.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/input/roads.gpkg \
  --tool6-node-error-csv /mnt/d/TestData/POC_Data/t08_preprocess/nodes/node_error_tool6.csv \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_junction_type_repair_nodes_tool4.gpkg \
  --roads-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_junction_type_repair_roads_tool4.gpkg \
  --audit-nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_junction_type_repair_audit_nodes_tool4.gpkg
```

Tool5：

```bash
.venv/bin/python scripts/t08_tool5_complex_junction_preprocess.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_junction_type_repair_nodes_tool4.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/input/roads.gpkg \
  --intersection-gpkg /mnt/d/TestData/POC_Data/input/RCSDIntersection.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_nodes_tool5.gpkg \
  --roads-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_roads_tool5.gpkg \
  --audit-nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_audit_nodes_tool5.gpkg
```

Tool6：

```bash
.venv/bin/python scripts/t08_tool6_nodes_type_qc.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_nodes_tool5.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_complex_junction_roads_tool5.gpkg \
  --csv-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/node_error_tool6.csv \
  --error-nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/node_error_tool6.gpkg
```

Tool7：

```bash
.venv/bin/python scripts/t08_tool7_traffic_restriction.py \
  --condition-gpkg /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/MIF/Cguangdong1.gpkg \
  --swnode-gpkg /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/A200-2025M12-node.gpkg \
  --swroad-gpkg /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/A200-2025M12-road.gpkg \
  --restriction-output /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/sw_restriction_tool7.gpkg
```

Tool8：

```bash
.venv/bin/python scripts/t08_tool8_lane_arrow.py \
  --lane-gpkg /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/MIF/Laneguangdong1.gpkg \
  --swnode-gpkg /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/A200-2025M12-node.gpkg \
  --swroad-gpkg /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/A200-2025M12-road.gpkg \
  --arrow-output /mnt/d/TestData/POC_Data/first_layer_road_net_v0/SW/sw_arrow_tool8.gpkg
```

Tool9：

```bash
.venv/bin/python scripts/t08_tool9_rcsd_cleaning.py \
  --rcsdnode-gpkg /mnt/d/TestData/POC_Data/input/RCSDNode.gpkg \
  --rcsdroad-gpkg /mnt/d/TestData/POC_Data/input/RCSDRoad.gpkg \
  --road-surface-gpkg /mnt/d/TestData/POC_Data/input/road_surface.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/rcsd/rcsdnode_clean_tool9.gpkg \
  --roads-output /mnt/d/TestData/POC_Data/t08_preprocess/rcsd/rcsdroad_clean_tool9.gpkg
```

Tool10：

```bash
.venv/bin/python scripts/t08_tool10_trajectory_aggregation.py \
  --patch-dir /mnt/d/TestData/POC_Data/patch_all/00000009
```

Tool10 内网多 Patch 参数化批处理：

```bash
bash scripts/t08_tool10_run_patches_innernet.sh \
  PATCH_DIR_1 PATCH_DIR_2 [PATCH_DIR_3 ...]
```

批处理脚本不内置 Patch 目录；所有 Patch 均从位置参数读取。参数可以是 WSL 路径，也可以是在 WSL shell 中以单引号包裹的 Windows 路径。脚本逐 Patch 调用 `t08_tool10_trajectory_aggregation.py`，单 Patch 失败不阻止其余 Patch，最终以非零退出码和汇总清单报告整批失败。

## 3. Tool1 Params

- `--input-shp`：可重复传入多个 Shapefile，输出为输入目录下 `<input_stem>.gpkg`。
- `--input-geojson`：可重复传入多个 GeoJSON，输出为输入目录下 `<input_stem>.gpkg`。
- `--input-gpkg`：可重复传入多个 GPKG，输出为输入目录下 `<input_stem>.geojson`。
- `--summary-output`：可选 summary JSON 输出路径；默认写入首个输入文件所在目录，文件名以 `_tool1` 结尾。
- `--target-epsg`：可选输出 EPSG；不提供时保留输入 CRS。
- `--default-crs`：当输入缺失 CRS 时使用。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次；单文件开始、结束、失败与总完成状态均输出进度信息。
- 覆盖口径：目标输出已存在时先删除再重建。

## 4. Tool2 Params

- `--road-gpkg`：一层 Road 输入 GPKG。
- `--patch-road-gpkg`：Patch Road 输入 GPKG。
- `--raw-kind-road-gpkg`：原始 Road Kind 输入 GPKG。
- `--road-layer / --patch-road-layer / --raw-kind-road-layer`：可选图层名。
- `--road-patch-output`：PatchID 输出 GPKG。
- `--road-patch-unmatched-output`：PatchID 未匹配输出 GPKG。
- `--road-patch-kind-output`：Kind 补充输出 GPKG。
- `--event-road-0a-output`：`kind` 包含 `17` 主辅路出入口属性的删除 Road 事件输出 GPKG。
- `--patch-summary-output / --kind-summary-output / --summary-output`：可选 summary 输出路径。
- `--buffer-distance-meters`：Kind 空间匹配缓冲距离，默认 `1.0`。
- `--spatial-predicate`：Kind 空间匹配谓词，默认 `covers`。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次；Patch join / Kind enrich 开始、读取、处理、写出与完成状态均输出进度信息。
- summary 性能字段：总 summary 写入 `performance.elapsed_seconds / roads_per_second / patch_join_elapsed_seconds / kind_enrich_elapsed_seconds / spatial_candidate_count`；阶段 summary 写入阶段耗时与吞吐，并在 `stage_timings` 中细分读取、属性索引、空间查询、事件 Road 删除与写出耗时。
- 读取性能：Road / Raw Kind GPKG 优先使用直接 SQLite GeoPackage 快读；无法识别标准 GPKG 元数据时回退 Fiona 读取。
- GPKG 输出写出：复用 T08 共享直接 SQLite GeoPackage 写出路径，避免 Fiona 逐要素 sink 写出；必须写入 `gpkg_ogr_contents` 与增删触发器，以兼容 QGIS 旧版 OGR provider filter 后的要素计数。

## 5. Tool3 Params

- `--nodes-gpkg`：Nodes 输入 GPKG。
- `--roads-gpkg`：Roads 拓扑参考输入 GPKG。
- `--nodes-output`：Nodes 类型聚合输出 GPKG。
- `--nodes-layer / --roads-layer`：可选图层名。
- `--summary-output`：可选 summary JSON 输出路径。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--nodes-default-crs / --roads-default-crs`：输入缺失 CRS 时使用。
- `--skip-roundabout`：跳过环岛聚合，仅初始化 `kind_2 / grade_2`。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次；读取、字段初始化、环岛聚合、写出与完成状态均输出进度信息。
- summary 性能字段：写入 `performance.elapsed_seconds / nodes_per_second / stage_timings`，用于定位读取、初始化、环岛聚合与写出耗时。
- GPKG 输出写出：复用 T08 共享直接 SQLite GeoPackage 写出路径，避免 Fiona 逐要素 sink 写出。

## 6. Tool4 Params

- `--nodes-gpkg`：Nodes 输入 GPKG。
- `--roads-gpkg`：Roads 拓扑参考输入 GPKG。
- `--nodes-output`：修复后的完整 Nodes 输出 GPKG。
- `--roads-output`：可选修复后 Roads 输出 GPKG；当 Tool6 连续分合流修复会删除 Road 时必填。
- `--audit-nodes-output`：语义路口审计 Nodes 输出 GPKG。
- `--tool6-node-error-csv / --tool6-node-error-gpkg`：可选 Tool6 质检成果输入；均不提供时跳过 Tool6 人工确认修复；两者不可同时提供。
- `--nodes-layer / --roads-layer`：可选图层名。
- `--summary-output`：可选 summary JSON 输出路径。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--nodes-default-crs / --roads-default-crs`：输入缺失 CRS 时使用。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个语义路口输出一次。
- summary 性能字段：写入 `performance.elapsed_seconds / semantic_nodes_per_second / stage_timings / road_read_mode`，用于定位读取、拓扑构建、错误识别、修复与写出耗时，并记录 Road 读取模式；summary 还必须记录 `repairs`、`degree_exceptions`、提前右转 / 辅路 Road 计数与 degree suppressed 计数。
- GPKG 输出写出：复用 T08 共享直接 SQLite GeoPackage 写出路径。

## 7. Tool5 Params

- `--nodes-gpkg`：Nodes 输入 GPKG。
- `--roads-gpkg`：Roads 输入 GPKG。
- `--nodes-output`：Nodes 输出 GPKG。
- `--roads-output`：Roads 输出 GPKG。
- `--audit-nodes-output`：审计 Nodes 输出 GPKG，记录 Tool5 两个处理过程实际涉及的 node。
- `--intersection-gpkg`：可选 `RCSDIntersection` 输入 GPKG；提供时 Tool5 先识别一对多候选再处理。
- `--node-error2-gpkg`：可选预生成 `node_error_2` 输入 GPKG；提供时作为兼容输入使用，但仍需同时提供 `--intersection-gpkg`。
- `--nodes-layer / --roads-layer / --node-error2-layer / --intersection-layer`：可选图层名。
- `--summary-output`：可选 summary JSON 输出路径。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--nodes-default-crs / --roads-default-crs / --node-error2-crs / --intersection-crs`：输入缺失 CRS 或需覆盖 CRS 时使用。
- `--skip-complex-divmerge`：跳过复杂分歧 / 合流聚合。
- `--skip-one-to-many`：跳过错误 1 对多处理。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次。
- summary 性能字段：写入 `performance.elapsed_seconds / nodes_per_second / stage_timings`，用于定位读取、复杂聚合、错误 1 对多识别 / 处理与写出耗时；summary 还必须记录 `node_error_2_detection`。

## 8. Tool6 Params

- `--nodes-gpkg`：Nodes 输入 GPKG，字段固定使用小写 `kind_2`。
- `--roads-gpkg`：Roads 输入 GPKG。
- `--csv-output`：人工质检 CSV 输出路径，文件名必须以 `_tool6.csv` 结尾，最后一列为 `是否修复`。
- `--error-nodes-output`：目视审查 GPKG 输出路径，文件名必须以 `_tool6.gpkg` 结尾。
- `--nodes-layer / --roads-layer`：可选图层名。
- `--summary-output`：可选 summary JSON 输出路径。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--nodes-default-crs / --roads-default-crs`：输入缺失 CRS 时使用。
- `--divmerge-search-distance-m`：连续分合流左侧追踪与竖方向追踪距离阈值，默认 `100`。
- `--vertical-parallel-angle-degrees`：竖方向相对平行夹角阈值，默认 `20`。
- `--vertical-endpoint-distance-m`：竖方向末端距离阈值，默认 `20`。
- `--horizontal-angle-degrees`：横方向共线夹角阈值，默认 `35`。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次。

## 9. Tool7 Params

- `--condition-gpkg`：SW C 表输入 GPKG。
- `--swnode-gpkg`：SW Node 输入 GPKG，用于审计。
- `--swroad-gpkg`：SW Road 输入 GPKG，用于 Link 存在性校验与 restriction 几何构建。
- `--restriction-output`：显性 restriction 输出 GPKG，文件名必须以 `_tool7.gpkg` 结尾。
- `--condition-layer / --swnode-layer / --swroad-layer`：可选输入图层名；C 表为多表 GPKG 且无法按文件 stem 自动定位时必须提供 `--condition-layer`。
- `--summary-output`：可选 summary JSON 输出路径，文件名必须以 `_tool7.json` 结尾。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--condition-default-crs / --swnode-default-crs / --swroad-default-crs`：输入缺失 CRS 时使用；C 表非空间时仅作为审计字段记录。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 条输出 restriction 记录输出一次。

## 10. Tool8 Params

- `--lane-gpkg`：SW Laneinfo 输入 GPKG，字段固定使用 `LinkID / Seq_Nm / Arrow_Dir / Lane_Dir`，大小写不敏感。
- `--swnode-gpkg`：SW Node 输入 GPKG，用于审计。
- `--swroad-gpkg`：SW Road 输入 GPKG，用于 Link 存在性校验、方向字段读取与 arrow 几何构建。
- `--arrow-output`：显性 arrow 输出 GPKG，文件名必须以 `_tool8.gpkg` 结尾。
- `--lane-layer / --swnode-layer / --swroad-layer`：可选输入图层名；Laneinfo 为多表 GPKG 且无法按文件 stem 自动定位时必须提供 `--lane-layer`。
- `--summary-output`：可选 summary JSON 输出路径，文件名必须以 `_tool8.json` 结尾。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--swnode-default-crs / --swroad-default-crs`：输入缺失 CRS 时使用；Laneinfo 非空间时不需要 CRS。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 条输出 Road 方向 arrow 记录输出一次。

## 11. Tool9 Params

- `--rcsdnode-gpkg`：RCSDNode 输入 GPKG。
- `--rcsdroad-gpkg`：RCSDRoad 输入 GPKG。
- `--road-surface-gpkg`：道路面输入 GPKG。
- `--nodes-output`：清理后的 RCSDNode 输出 GPKG，文件名必须以 `_tool9.gpkg` 结尾。
- `--roads-output`：清理后的 RCSDRoad 输出 GPKG，文件名必须以 `_tool9.gpkg` 结尾。
- `--rcsdnode-layer / --rcsdroad-layer / --road-surface-layer`：可选输入图层名。
- `--summary-output`：可选 summary JSON 输出路径，文件名必须以 `_tool9.json` 结尾。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--rcsdnode-default-crs / --rcsdroad-default-crs / --road-surface-default-crs`：输入缺失 CRS 时使用。
- `--node-predicate`：node 与道路面空间关系判定，默认 `covers`，可选 `contains`。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 条 Road 记录输出一次。

## 12. Tool10 Params

- `--patch-dir`：必填，具体 Patch 目录；输入固定从其 `Traj/*/raw_dat_pose.geojson` 发现，输出固定写入该 `Traj` 根目录。
- `--default-crs`：可选，仅在 GeoJSON 未声明 CRS 时显式指定所有缺失输入采用的 CRS。
- `--max-distance-gap-m`：距离断点阈值，默认 `10.0`。
- `--max-time-gap-s`：时间断点阈值，默认 `1.0`。
- `--max-seq-gap`：序号断点阈值，默认 `20000000`。
- `--overwrite`：可选；未提供时，任一正式输出已存在即失败；提供时采用临时文件成功后替换。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个输入点输出一次。
- `scripts/t08_tool10_run_patches_innernet.sh PATCH_DIR [PATCH_DIR ...]`：内网多 Patch 批处理；Patch 目录全部通过位置参数传入，禁止写死业务目录。
- 批处理环境变量：`OVERWRITE=1` 显式覆盖已有结果；`DEFAULT_CRS / MAX_DISTANCE_GAP_M / MAX_TIME_GAP_S / MAX_SEQ_GAP / PROGRESS_INTERVAL` 覆盖同名 Tool10 参数；`PYTHON / REPO_ROOT / LOG_ROOT` 可显式覆盖运行环境与日志根目录。

## 13. Acceptance

1. Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，转换成果均为输入目录下同 stem、不同格式后缀的目标格式文件；summary 仍按 `_tool1` 命名。
2. Tool2 只接受 GPKG 输入。
3. Tool2 主输出与 `event_road_0a_tool2.gpkg` 均为 GPKG 且 CRS 为 `EPSG:3857`。
4. Tool2 `patch_id` 多值按逗号拼接。
5. Tool2 `kind` 多值按 `|` 去重拼接；具有 `17` 主辅路出入口属性的 Road 必须从主 Kind 输出删除，并写入事件 Road 输出。
6. Tool3 输出 Nodes GPKG 且 CRS 为 `EPSG:3857`。
7. Tool3 保留原始 `kind / grade`，只在 copy-on-write 输出中写入 `kind_2 / grade_2 / mainnodeid / subnodeid`。
8. Tool3 summary 可追溯环岛组、单节点环岛保留数量、缺失端点 Road/Node、更新节点数、CRS、字段解析与阶段性能；Tool3 不再构造复杂分歧 / 合流路口，缺失端点 Road 只跳过环岛拓扑计算且不从输入删除。
9. Tool4 输出完整 Nodes / audit Nodes GPKG 且 CRS 为 `EPSG:3857`；提供 `--roads-output` 时 Roads 输出也必须为 `EPSG:3857`。
10. Tool4 识别错误 T 型路口与 `kind_2 in {8,16}` 一入一出分合流路口，并按规则写回代表 node `kind_2`。
11. Tool4 对提前右转与辅路 Road 执行入出度异常豁免；候选错误被豁免时不写入 audit Nodes，必须写入 summary `degree_exceptions`。
12. Tool4 可选消费 Tool6 质检成果；只处理 `是否修复 = 1` 的 `错误分歧合流路口 / 错误交叉路口_T型路口 / 错误交叉路口_非交叉路口`，并在 summary 中记录 Tool6 修复、跳过和删除 Road。
13. Tool5 输出 Nodes / Roads / audit Nodes GPKG 且 CRS 为 `EPSG:3857`。
14. Tool5 summary 可追溯复杂分歧 / 合流组、`node_error_2_detection`、错误 1 对多合并组、Tool5 T-pair 虚拟连通边、删除 Road、audit node 数量、CRS、字段解析与阶段性能。
15. Tool6 输出 `node_error_tool6.csv / node_error_tool6.gpkg` 且 GPKG CRS 为 `EPSG:3857`。
16. Tool6 CSV 最后一列为 `是否修复`，默认值为 `1`；人工确认不需要修复的数据改为 `0`；Tool6 不修改输入 Nodes/Roads。
17. Tool6 可追溯 `错误分歧合流路口 / 错误交叉路口_T型路口 / 错误交叉路口_非交叉路口`、入出度、相关 Road、suppressed 原因、CRS 与性能 summary。
18. Tool7 输出 `sw_restriction_tool7.gpkg` 且 GPKG CRS 为 `EPSG:3857`。
19. Tool7 仅输出 `CondType = 1` 且 in/out Link 均存在于 SW Road 的 restriction，输出记录继承 C 表业务字段，几何能解释 Link 端点重叠与非重叠连接。
20. Tool8 输出 `sw_arrow_tool8.gpkg` 且 GPKG CRS 为 `EPSG:3857`。
21. Tool8 仅输出 `LinkID` 存在于 SW Road 的 Laneinfo 记录；同一 `LinkID + Lane_Dir` 只输出一条记录，`Arrow_Dir` 按 `Seq_Nm` 顺序拆分并重新用逗号拼接为 `arrow` 字段，几何方向必须符合 `direction / Lane_Dir` 映射规则。
22. Tool9 输出 `rcsdnode_clean_tool9.gpkg / rcsdroad_clean_tool9.gpkg` 且 GPKG CRS 为 `EPSG:3857`。
23. Tool9 对普通 node 按道路面覆盖 / 包含判定保留；对 `mainnodeid` 非空且非 `0` 的语义路口组，必须整组所有 node 均满足道路面覆盖 / 包含才保留。
24. Tool9 仅保留与道路面相交且 `snodeid / enodeid` 均在最终保留 node 集合内的 RCSDRoad。
25. Tool10 扫描一个 Patch 的全部 `Traj/*/raw_dat_pose.geojson`，将所有连续轨迹段聚合写入单个 `<Patch>/Traj/raw_dat_pose.gpkg` 的 `raw_dat_pose` 图层。
26. Tool10 输出必须为 `EPSG:3857 LineStringZ`，且所有输出坐标 Z 与对应输入点 Z 数值相等；缺 Z、非有限 Z、非法 Point 或未知 CRS 必须整批失败。切分形成的单点段必须从线图层排除并逐点审计，不得跨断点拼接、复制点或整批失败。
27. Tool10 必须先投影 XY 再应用米制距离阈值，并验证 `output_point_count + discarded_single_point_count = input_point_count`；不得静默跳过文件、要素或点。
28. Tool10 默认拒绝覆盖；显式覆盖时任何校验或临时写入失败不得替换已有正式成果。
29. 所有路径均由参数提供或按 contract 从 `--patch-dir` 确定，不写死内网目录。
30. 除 Tool1 转换成果与 Tool10 `Traj/raw_dat_pose.gpkg` 两个已登记特例外，所有 T08 成果输出文件名均以 `_toolX` 结尾。
31. summary 可追溯输入、输出、参数、字段解析、CRS、Z、断点、计数、运行环境与性能。
32. Tool10 内网批处理入口支持任意数量 Patch 位置参数，不得内置具体 Patch 目录；必须逐 Patch 留存日志并在结束时汇总成功/失败。
