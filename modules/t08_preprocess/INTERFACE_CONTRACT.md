# T08 - INTERFACE_CONTRACT

## 定位

`t08_preprocess` 是项目正式预处理模块。模块内部以工具形式提供能力，但这些工具属于项目正式组成部分，不是一次性实验脚本。

## 1. 当前工具

### Tool1：基础矢量格式转换

- 输入：一个或多个 `.shp / .geojson / .json / .gpkg` 文件，全部通过参数提供。
- 支持转换：
  - `.shp -> <input_dir>/<input_stem>.gpkg`
  - `.geojson / .json -> <input_dir>/<input_stem>.gpkg`
  - `.gpkg -> <input_dir>/<input_stem>.geojson`
- 输出边界：所有输出均写回输入文件所在目录下的同名目标格式文件；不合并多个输入，不提供输出目录参数，不提供逐文件自定义输出路径参数；若同一轮输入会导致重复输出或输出覆盖本轮任一输入，必须报错停止。
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
  - `t08_road_patch.gpkg`
  - `t08_road_patch_unmatched.gpkg`
  - `t08_road_patch_kind.gpkg`
  - `t08_road_patch_summary.json`
  - `t08_road_kind_summary.json`
  - `t08_road_preprocess_summary.json`
- 输出 CRS：`EPSG:3857`。
- 所有输入、输出路径必须通过参数提供。

### Tool3：Nodes 类型聚合

- 输入一：Nodes GPKG，依赖字段 `id / kind / grade`，可选字段 `mainnodeid / has_evd / is_anchor / subnodeid`。
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`；环岛聚合使用可选字段 `roadtype`。
- 输出：
  - `t08_nodes_type_aggregation.gpkg`
  - `t08_nodes_type_aggregation_summary.json`
- 输出 CRS：`EPSG:3857`。
- 类型初始化：新增或覆盖 `kind_2 / grade_2`，初始值分别复制自 `kind / grade`，原始 `kind / grade` 不改写。
- 环岛聚合：参考 T01 环岛构建，按 `roadtype bit3` 的 Road 连通组聚合；组内最小 Node `id` 为 `mainnode`，mainnode 写 `grade_2 = 1 / kind_2 = 64`，成员写 `grade_2 = 0 / kind_2 = 0`，全组 `mainnodeid` 写为 mainnode。
- 复杂分歧 / 合流聚合：参考 T04 full-input 候选与连续链路口口径，对 representative node 的 `kind_2 in {8, 16}` 候选沿 Road 有向拓扑识别连续链，聚合后 mainnode 写 `kind_2 = 128`，成员写 `grade_2 = 0 / kind_2 = 0`，全组 `mainnodeid` 写为 mainnode。若输入存在 `has_evd / is_anchor` 字段，则候选需满足 `has_evd = yes / is_anchor = no`。
- 输出边界：Tool3 只输出 copy-on-write Nodes，不修改输入文件，不输出或改写 Roads。
- 所有输入、输出路径必须通过参数提供。

### Tool4：路口类型错误识别

- 输入一：Nodes GPKG，依赖字段 `id / kind`，可选字段 `mainnodeid`。
- 输入二：Roads GPKG，依赖字段 `id / snodeid / enodeid / direction`。
- 输出：
  - `nodes_error.gpkg`
  - `t08_junction_type_repair_summary.json`
- 输出 CRS：`EPSG:3857`。
- 入度 / 出度定义：
  - `direction in {0,1}` 表示双向 road，对两端语义路口分别 `in_degree + 1 / out_degree + 1`。
  - `direction = 2` 表示 `snodeid -> enodeid`，source 语义路口 `out_degree + 1`，target 语义路口 `in_degree + 1`。
  - `direction = 3` 表示 `enodeid -> snodeid`，source 语义路口 `out_degree + 1`，target 语义路口 `in_degree + 1`。
- 错误识别：
  - `kind = 2048`：若入度或出度任一不为 `2`，输出 `error_type = 错误T型路口`。
  - `kind = 4`：若入度和出度均为 `2`，输出 `error_type = 错误交叉路口`。
  - `kind = 16`：若出度为 `2`，沿横向 / 左侧候选 road 忽略二度连接，在 `100m` 内找到 `kind = 8` 且入度为 `2` 的合流路口，并满足横向与竖向 T 型特征，则分歧与合流代表 node 均输出 `error_type = 错误分歧合流路口`。
- 连续分歧合流左右候选：
  - 当前输入字段未提供显式 left/right road 标识，第一版使用“入向 road 与两个退出 road 的夹角最小者”为横向 / 左侧候选，另一条为竖向 / 右侧候选。
  - 若后续上游正式提供左右字段，必须在本契约同轮更新后才能替换该代理规则。
- 输出字段至少包含 `id / semantic_node_id / source_node_id / kind / error_type / error_reason / error_group_id / in_degree / out_degree / related_node_ids / related_road_ids / audit_json`。
- 输出边界：Tool4 只输出错误识别结果，不修改输入 Nodes/Roads，不输出修复后 Nodes/Roads。
- 性能口径：Tool4 Road GPKG 优先使用直接 SQLite 轻量读取，只读取 `id / snodeid / enodeid / direction / geometry`，进入拓扑前仅保留 road 长度与方向向量，不长期持有完整 Road 几何；无法识别标准 GPKG 元数据时回退共享 `read_vector`。
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
  --road-patch-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch.gpkg \
  --road-patch-unmatched-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_unmatched.gpkg \
  --road-patch-kind-output /mnt/d/TestData/POC_Data/t08_preprocess/road/t08_road_patch_kind.gpkg
```

Tool3：

```bash
.venv/bin/python scripts/t08_tool3_nodes_type_aggregation.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/input/nodes.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/input/roads.gpkg \
  --nodes-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_nodes_type_aggregation.gpkg
```

Tool4：

```bash
.venv/bin/python scripts/t08_tool4_junction_type_repair.py \
  --nodes-gpkg /mnt/d/TestData/POC_Data/t08_preprocess/nodes/t08_nodes_type_aggregation.gpkg \
  --roads-gpkg /mnt/d/TestData/POC_Data/input/roads.gpkg \
  --nodes-error-output /mnt/d/TestData/POC_Data/t08_preprocess/nodes/nodes_error.gpkg
```

## 3. Tool1 Params

- `--input-shp`：可重复传入多个 Shapefile，输出为输入目录下同名 `.gpkg`。
- `--input-geojson`：可重复传入多个 GeoJSON，输出为输入目录下同名 `.gpkg`。
- `--input-gpkg`：可重复传入多个 GPKG，输出为输入目录下同名 `.geojson`。
- `--summary-output`：可选 summary JSON 输出路径；默认写入首个输入文件所在目录。
- `--target-epsg`：可选输出 EPSG；不提供时保留输入 CRS。
- `--default-crs`：当输入缺失 CRS 时使用。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次；单文件开始、结束、失败与总完成状态均输出进度信息。
- 覆盖口径：同名输出已存在时先删除再重建。

## 4. Tool2 Params

- `--road-gpkg`：一层 Road 输入 GPKG。
- `--patch-road-gpkg`：Patch Road 输入 GPKG。
- `--raw-kind-road-gpkg`：原始 Road Kind 输入 GPKG。
- `--road-layer / --patch-road-layer / --raw-kind-road-layer`：可选图层名。
- `--road-patch-output`：PatchID 输出 GPKG。
- `--road-patch-unmatched-output`：PatchID 未匹配输出 GPKG。
- `--road-patch-kind-output`：Kind 补充输出 GPKG。
- `--patch-summary-output / --kind-summary-output / --summary-output`：可选 summary 输出路径。
- `--buffer-distance-meters`：Kind 空间匹配缓冲距离，默认 `1.0`。
- `--spatial-predicate`：Kind 空间匹配谓词，默认 `covers`。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次；Patch join / Kind enrich 开始、读取、处理、写出与完成状态均输出进度信息。
- summary 性能字段：总 summary 写入 `performance.elapsed_seconds / roads_per_second / patch_join_elapsed_seconds / kind_enrich_elapsed_seconds / spatial_candidate_count`；阶段 summary 写入阶段耗时与吞吐，并在 `stage_timings` 中细分读取、属性索引、空间查询与写出耗时。
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
- `--skip-roundabout`：跳过环岛聚合，仅初始化 `kind_2 / grade_2` 并继续后续步骤。
- `--skip-complex-divmerge`：跳过复杂分歧 / 合流聚合。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个要素输出一次；读取、字段初始化、环岛聚合、复杂分歧 / 合流聚合、写出与完成状态均输出进度信息。
- summary 性能字段：写入 `performance.elapsed_seconds / nodes_per_second / stage_timings`，用于定位读取、初始化、环岛聚合、复杂分歧 / 合流聚合与写出耗时。
- GPKG 输出写出：复用 T08 共享直接 SQLite GeoPackage 写出路径，避免 Fiona 逐要素 sink 写出。

## 6. Tool4 Params

- `--nodes-gpkg`：Nodes 输入 GPKG。
- `--roads-gpkg`：Roads 拓扑参考输入 GPKG。
- `--nodes-error-output`：错误语义路口输出 GPKG，推荐文件名 `nodes_error.gpkg`。
- `--nodes-layer / --roads-layer`：可选图层名。
- `--summary-output`：可选 summary JSON 输出路径。
- `--target-epsg`：最终输出 EPSG，默认 `3857`。
- `--nodes-default-crs / --roads-default-crs`：输入缺失 CRS 时使用。
- `--trace-distance-m`：连续分歧合流追踪距离，默认 `100` 米。
- `--angle-tolerance-degrees`：横向 / 平行几何判定角度容差，默认 `35` 度。
- `--progress-interval`：可选控制台进度输出间隔，默认每 `10000` 个语义路口输出一次。
- summary 性能字段：写入 `performance.elapsed_seconds / semantic_nodes_per_second / stage_timings / road_read_mode`，用于定位读取、拓扑构建、错误识别与写出耗时，并记录 Road 读取模式。
- GPKG 输出写出：复用 T08 共享直接 SQLite GeoPackage 写出路径。

## 7. Acceptance

1. Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，所有输出均为输入目录下同名目标格式文件。
2. Tool2 只接受 GPKG 输入。
3. Tool2 三个主输出均为 GPKG 且 CRS 为 `EPSG:3857`。
4. Tool2 `patch_id` 多值按逗号拼接。
5. Tool2 `kind` 多值按 `|` 去重拼接。
6. Tool3 输出 Nodes GPKG 且 CRS 为 `EPSG:3857`。
7. Tool3 保留原始 `kind / grade`，只在 copy-on-write 输出中写入 `kind_2 / grade_2 / mainnodeid / subnodeid`。
8. Tool3 summary 可追溯环岛组、复杂链路组、候选计数、更新节点数、CRS、字段解析与阶段性能。
9. Tool4 输出 `nodes_error.gpkg` 且 CRS 为 `EPSG:3857`。
10. Tool4 至少识别错误 T 型路口、错误交叉路口、错误分歧合流路口三类 `error_type`。
11. Tool4 不修改输入 Nodes/Roads，不输出修复后 Nodes/Roads。
12. 所有路径均由参数提供，不写死内网目录。
13. summary 可追溯输入、输出、参数、字段解析、CRS 与计数。
