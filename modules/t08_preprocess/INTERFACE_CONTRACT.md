# T08 - INTERFACE_CONTRACT

## 定位

`t08_preprocess` 是项目正式预处理模块。模块内部以工具形式提供能力，但这些工具属于项目正式组成部分，不是一次性实验脚本。

## 0. 成果输出命名约束

除输入文件本身外，T08 所有成果输出文件名必须在扩展名前以 `_toolX` 结尾，`X` 为工具编号。例如 Tool2 的事件 Road 输出为 `event_road_0a_tool2.gpkg`。

## 1. 当前工具

### Tool1：基础矢量格式转换

- 输入：一个或多个 `.shp / .geojson / .json / .gpkg` 文件，全部通过参数提供。
- 支持转换：
  - `.shp -> <input_dir>/<input_stem>_tool1.gpkg`
  - `.geojson / .json -> <input_dir>/<input_stem>_tool1.gpkg`
  - `.gpkg -> <input_dir>/<input_stem>_tool1.geojson`
- 输出边界：所有输出均写回输入文件所在目录下，并在输入 stem 后追加 `_tool1`；不合并多个输入，不提供输出目录参数，不提供逐文件自定义输出路径参数；若同一轮输入会导致重复输出或输出覆盖本轮任一输入，必须报错停止。
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

- 输入一：Nodes GPKG，依赖字段 `id / kind / grade`，可选字段 `mainnodeid / has_evd / is_anchor / subnodeid`。
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`；环岛聚合使用可选字段 `roadtype`。
- 输出：
  - `t08_nodes_type_aggregation_tool3.gpkg`
  - `t08_nodes_type_aggregation_summary_tool3.json`
- 输出 CRS：`EPSG:3857`。
- 类型初始化：新增或覆盖 `kind_2 / grade_2`，初始值分别复制自 `kind / grade`，原始 `kind / grade` 不改写。
- 环岛聚合：参考 T01 环岛构建，按 `roadtype bit3` 的 Road 连通组聚合；组内最小 Node `id` 为 `mainnode`，mainnode 写 `grade_2 = 1 / kind_2 = 64`，成员写 `grade_2 = 0 / kind_2 = 0`，全组 `mainnodeid` 写为 mainnode。
- 输出边界：Tool3 只输出 copy-on-write Nodes，不修改输入文件，不输出或改写 Roads。
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
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`。
- 输入三：`RCSDIntersection` GPKG，可选；启用错误 1 对多识别与处理时必填。
- 输入四：`node_error_2` GPKG，可选兼容输入，依赖字段 `id / junction_id`；未提供时 Tool5 按 T02 `node_error_2` 生成口径基于 `RCSDIntersection` 即时识别。
- 输出：
  - `t08_complex_junction_nodes_tool5.gpkg`
  - `t08_complex_junction_roads_tool5.gpkg`
  - `t08_complex_junction_audit_nodes_tool5.gpkg`
  - `t08_complex_junction_preprocess_summary_tool5.json`
- 输出 CRS：`EPSG:3857`。
- 复杂分歧 / 合流聚合：从 Tool3 移出，参考 T04 full-input 候选与连续链路口口径，对 representative node 的 `kind_2 in {8, 16}` 候选沿 Road 有向拓扑识别连续链，聚合后 mainnode 写 `kind_2 = 128`，成员写 `grade_2 = 0 / kind_2 = 0`，全组 `mainnodeid` 写为 mainnode。若输入存在 `has_evd / is_anchor` 字段，则候选需满足 `has_evd = yes / is_anchor = no`。
- 错误 1 对多路口处理：参考 T02 `node_error_2` 生成逻辑，先用 `RCSDIntersection` 反向包含 / 接触 SWSD 语义路口；若一个面对应不止一组语义路口，则忽略代表 `kind_2 = 1` 的组，过滤后剩余组数大于 `1` 时生成一对多候选；随后复用 T02 离线修复逻辑，只有剩余组之间具备 Road 连通性时才合并，选择最小 junction group 作为 mainnode，mainnode 写 `kind_2 = 4`，成员写 `kind_2 = 0 / grade_2 = 0`，删除 intersection 面内被合并组之间的内部 Road。
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
  - 识别 `kind_2 = 4` 且 `in_degree = 2 / out_degree = 2` 的语义路口。
  - 若进入和退出 road 在路口处忽略道路方向后形成四个不同外侧角度方向，则视为真实交叉路口，不输出错误。
  - 若关联 road 只有两条双向 road，则输出 `error_type = 错误交叉路口_非交叉路口`。
  - 若忽略道路方向后只有两个外侧角度方向，且每个角度方向均具备一进一出关系（双向 road 同时视为一进一出；单向进入 / 退出 road 连接至同一外侧节点时可归为同一角度方向），则输出 `error_type = 错误交叉路口_非交叉路口`。
  - 若符合 T 型路口特征：横方向为一条单向进入 road 与一条单向退出 road，竖方向为双向平行单向 road 或一条双向 road，且竖方向 road 位于横方向前进方向右侧，则输出 `error_type = 错误交叉路口_T型路口`。
  - 其余 `kind_2 = 4 / in_degree = 2 / out_degree = 2` 候选输出 `error_type = 错误交叉路口_非交叉路口`。
- summary 必须记录输入、输出、参数、字段解析、CRS、错误类型计数、suppressed 连续分合流候选与性能字段。
- 所有输入、输出路径必须通过参数提供。

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

## 3. Tool1 Params

- `--input-shp`：可重复传入多个 Shapefile，输出为输入目录下 `<input_stem>_tool1.gpkg`。
- `--input-geojson`：可重复传入多个 GeoJSON，输出为输入目录下 `<input_stem>_tool1.gpkg`。
- `--input-gpkg`：可重复传入多个 GPKG，输出为输入目录下 `<input_stem>_tool1.geojson`。
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
- GPKG 输出写出：复用 T08 共享直接 SQLite GeoPackage 写出路径，避免 Fiona 逐要素 sink 写出。

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

## 9. Acceptance

1. Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，所有输出均为输入目录下追加 `_tool1` 的目标格式文件。
2. Tool2 只接受 GPKG 输入。
3. Tool2 主输出与 `event_road_0a_tool2.gpkg` 均为 GPKG 且 CRS 为 `EPSG:3857`。
4. Tool2 `patch_id` 多值按逗号拼接。
5. Tool2 `kind` 多值按 `|` 去重拼接；具有 `17` 主辅路出入口属性的 Road 必须从主 Kind 输出删除，并写入事件 Road 输出。
6. Tool3 输出 Nodes GPKG 且 CRS 为 `EPSG:3857`。
7. Tool3 保留原始 `kind / grade`，只在 copy-on-write 输出中写入 `kind_2 / grade_2 / mainnodeid / subnodeid`。
8. Tool3 summary 可追溯环岛组、更新节点数、CRS、字段解析与阶段性能；Tool3 不再构造复杂分歧 / 合流路口。
9. Tool4 输出完整 Nodes / audit Nodes GPKG 且 CRS 为 `EPSG:3857`；提供 `--roads-output` 时 Roads 输出也必须为 `EPSG:3857`。
10. Tool4 识别错误 T 型路口与 `kind_2 in {8,16}` 一入一出分合流路口，并按规则写回代表 node `kind_2`。
11. Tool4 对提前右转与辅路 Road 执行入出度异常豁免；候选错误被豁免时不写入 audit Nodes，必须写入 summary `degree_exceptions`。
12. Tool4 可选消费 Tool6 质检成果；只处理 `是否修复 = 1` 的 `错误分歧合流路口 / 错误交叉路口_T型路口 / 错误交叉路口_非交叉路口`，并在 summary 中记录 Tool6 修复、跳过和删除 Road。
13. Tool5 输出 Nodes / Roads / audit Nodes GPKG 且 CRS 为 `EPSG:3857`。
14. Tool5 summary 可追溯复杂分歧 / 合流组、`node_error_2_detection`、错误 1 对多合并组、删除 Road、audit node 数量、CRS、字段解析与阶段性能。
15. Tool6 输出 `node_error_tool6.csv / node_error_tool6.gpkg` 且 GPKG CRS 为 `EPSG:3857`。
16. Tool6 CSV 最后一列为 `是否修复`，默认值为 `1`；人工确认不需要修复的数据改为 `0`；Tool6 不修改输入 Nodes/Roads。
17. Tool6 可追溯 `错误分歧合流路口 / 错误交叉路口_T型路口 / 错误交叉路口_非交叉路口`、入出度、相关 Road、suppressed 原因、CRS 与性能 summary。
18. 所有路径均由参数提供，不写死内网目录。
19. 所有 T08 成果输出文件名均以 `_toolX` 结尾。
20. summary 可追溯输入、输出、参数、字段解析、CRS 与计数。
