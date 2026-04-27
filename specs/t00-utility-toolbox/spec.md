# T00 Utility Toolbox 规格说明

## 1. 背景与目标

`T00` 用于承接 `RCSD_Topo_Poc` 项目内的数据整理、实验准备、辅助检查、问题排查和全局辅助图层预处理工作，避免这类工具散落在业务模块或临时脚本中。

`T00` 的目标是提供轻量、可复跑、可追溯的项目内工具集合，不直接承担地图业务要素生产。

## 2. 模块定位

- 模块名称：`T00 Utility Toolbox / 工具集合模块`
- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不承担后续地图要素生成逻辑
- `T00` 只为项目内部工具提供统一落点、边界约束和固定执行入口

## 3. 当前范围

当前纳入范围为 Tool1-Tool7、Tool9、Tool10；Tool8 当前未登记：

- Tool1：Patch 数据整理脚本
- Tool2：全量 DriveZone 预处理与合并
- Tool3：全量 Intersection 预处理与汇总
- Tool4：一层路网增加 `patch_id`
- Tool5：一层路网增加 SW 原始 `kind`
- Tool6：shp 导出 GeoJSON 工具
- Tool7：目录级 GeoJSON 批量转 GPKG 工具
- Tool9：全量 DivStripZone 预处理与合并
- Tool10：指定 JSON 上车点导出双图层 GPKG 工具

## 4. 统一规则

### 4.1 路径口径

- Patch 子目录统一使用 `Vector/`
- 不使用 `vector/`

### 4.2 CRS 与几何处理口径

- 所有几何处理统一在目标 CRS 下进行
- Tool1 不做几何处理
- Tool2 / Tool3 / Tool6 统一输出 `EPSG:3857`
- Tool4 / Tool5 在脚本顶部显式设置 `TARGET_EPSG`，默认值为 `3857`
- Tool5 的两类输入默认 CRS 分别独立配置：
  - `A200_road_patch` 默认 `EPSG:3857`
  - SW 原始路网默认 `EPSG:4326`
- Tool10 只读取 `data.spots[].lon/lat` 作为点几何，按原始经纬度写出为 `EPSG:4326`
- 输入若非目标 CRS，先重投影到目标 CRS
- 允许最小限度几何修复，仅用于保证流程可执行
- 不做复杂人工推断式修复

### 4.3 覆盖口径

- 输出已存在时，先删除再重建
- Tool1 例外：复跑时只清空目标 `<PatchID>/Vector/` 后重拷贝

### 4.4 执行体验口径

- 固定脚本入口
- 文件头集中参数
- Tool7 作为批准后的例外，允许通过脚本参数传入目录路径
- Tool10 作为批准后的例外，允许通过脚本参数传入输入 JSON 路径与可选输出 GPKG 路径
- 命令行执行过程中必须提供进度输出
- 至少体现工具开始/结束、阶段级进度、Patch 或记录级进度

## 5. Tool1 至 Tool5 既有基线

- Tool1：维护 `patch_all` 目录骨架与 `Vector/` 归位
- Tool2：生成 per-patch `DriveZone_fix.geojson`，按 `+1m / -1m` 做单 Patch 修复，并汇总输出根目录 `DriveZone.geojson`
- Tool3：对 `Intersection` 做逐 Patch 预处理并汇总输出
- Tool4：对 `A200_road` 写入 `patch_id`
- Tool5：对 `A200_road_patch` 写入 SW 原始 `kind`

## 6. Tool6 需求基线

### 6.1 目标

将 `A200_node.shp` 重新导出为保留原始属性的 `nodes.geojson`，目标投影为 `EPSG:3857`。

### 6.2 输入与输出

- 输入：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_node.shp`
- 输出：`D:\TestData\POC_Data\first_layer_road_net_v0\nodes.geojson`
- 输出坐标必须真实为 `EPSG:3857`

### 6.3 处理要求

1. 读取 shp
2. 审计输入要素数量、几何类型、字段列表与输入 CRS
3. 若输入 CRS 缺失，不得猜测，应阻塞并写入摘要
4. 若输入 CRS 非 `3857`，先重投影到 `3857`
5. 保留原始属性
6. 允许最小限度修复，仅用于保证导出可执行
7. 修复失败则记录异常并计入失败统计
8. 输出已存在时先删除再重建
9. 保持输入输出要素数量尽量一致，除非存在无效几何或读写异常

### 6.4 日志、摘要与进度

- 日志与摘要落在 `first_layer_road_net_v0` 同目录
- 命令行输出至少包含：
  - Tool6 开始/结束
  - 读取阶段
  - CRS 检查 / 转换阶段
  - 导出阶段
  - 当前进度 / 总数
  - 最终统计
- 摘要至少包含：
  - `input_path`
  - `output_path`
  - `input_feature_count`
  - `output_feature_count`
  - `input_crs`
  - `output_crs`
  - `repaired_feature_count`
  - `failed_feature_count`
  - `field_names`
  - `geometry_type_summary`
  - 异常说明

### 6.5 GeoJSON 说明

- Tool6 按项目当前要求输出 `EPSG:3857` GeoJSON
- 这是项目内约定输出，不保证严格标准 GeoJSON 互操作
- 不得在实现中自行改回 `4326`

## 7. Tool7 需求基线

### 7.1 目标

将指定目录下顶层（不递归子目录）的所有 `.geojson` 文件转换为同目录同名 `.gpkg` 文件。

### 7.2 输入与输出

- 输入：脚本参数给定的目录路径
- 扫描范围：仅目录顶层 `.geojson`
- 输出：每个输入文件在同目录生成一个同名 `.gpkg`
- 不递归子目录

### 7.3 处理要求

1. 扫描目录顶层所有 `.geojson` 文件
2. 逐文件读取 GeoJSON FeatureCollection
3. 优先读取 GeoJSON `crs`
4. 若 GeoJSON 缺失 `crs`，沿用仓库现有 GeoJSON 默认口径，按 `EPSG:4326` 处理
5. 保留原始属性
6. 允许最小限度几何修复，仅用于保证转换可执行
7. 修复失败的要素写入失败统计，但不阻断其它文件继续转换
8. 同名 `.gpkg` 已存在时先删除再重建

### 7.4 日志、摘要与进度

- 日志与摘要落在输入目录
- 命令行输出至少包含：
  - Tool7 开始/结束
  - 顶层文件发现阶段
  - 单文件转换阶段
  - 当前文件进度 / 总文件数
  - 最终统计
- 摘要至少包含：
  - `directory_path`
  - `geojson_file_count`
  - `converted_file_count`
  - `failed_file_count`
  - `total_input_feature_count`
  - `total_output_feature_count`
  - `file_results`
  - `error_reason_summary`


## 8. Tool9 需求基线

### 8.1 目标

- 对全量 `DivStripZone` 做逐 Patch 预处理并汇总输出
- 生成 per-patch `DivStripZone_fix.geojson` 与根目录全量 `DivStripZone.gpkg`
- 输出 CRS 为 `EPSG:3857`，输出格式为 `GPKG`

### 8.2 输入与输出

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\vector\DivStripZone.geojson`
- 兼容输入：若存在 `Vector/DivStripZone.geojson` 允许读取
- per-patch 输出：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DivStripZone_fix.geojson`
- 全局输出：`D:\TestData\POC_Data\patch_all\DivStripZone.gpkg`

### 8.3 处理要求

1. 读取每个 Patch 的 `DivStripZone.geojson`
2. 若输入 CRS 非 `3857`，重投影到 `3857`
3. 允许最小限度几何修复；修复失败则跳过并记录异常
4. 单 Patch 内做面合并后写出 `DivStripZone_fix.geojson`
5. 每个输出要素必须包含 `patchid` 字段
6. 全量阶段将每个 Patch 的 fix 结果汇总到根目录 `DivStripZone.gpkg`
7. 输出已存在时先删除再重建

### 8.4 日志、摘要与进度

- 日志与摘要落在 `patch_all` 根目录
- 命令行输出至少包含：
  - Tool9 开始/结束
  - 阶段级进度
  - Patch 进度
- 摘要至少包含：
  - `total_patch_count`
  - `input_found_count`
  - `processed_patch_count`
  - `fixed_output_count`
  - `skip_missing_count`
  - `skip_error_count`
  - `global_merge_input_count`
  - 输出要素统计与异常原因

## 9. Tool10 需求基线

### 9.1 目标

将指定 JSON / NDJSON 请求记录中的 `data.spots` 候选上车点流式展开为点状 `GPKG`，在同一个 GPKG 中同时输出全量候选上车点与推荐上车点。

### 9.2 输入与输出

- 输入：脚本参数指定的 JSON / NDJSON 文件
- 输出：脚本参数 `--output` 指定的 GPKG；未指定时输出输入文件同目录同名 `.gpkg`
- 输出坐标保持原始经纬度，输出 CRS 为 `EPSG:4326`
- 输出几何类型为 `Point`
- 输出图层名：
  - `pickup_spots_all`
  - `pickup_spots_recommended`

### 9.3 处理要求

1. 支持 `NDJSON` 与 `JSON array` 两种输入布局
2. 按流式方式逐条解析记录，不得将超大文件整体载入内存
3. `pickup_spots_all` 中一条输出要素对应 `data.spots` 数组中的一个候选上车点
4. `pickup_spots_recommended` 只包含 `isRecommend` 为真值的候选上车点
5. 几何只读取 `spots[i].lon/lat`，不得使用顶层 `lon/lat` 或 `data.location.lon/lat`
6. 坐标值统一视为原始经纬度，直接写出，不做坐标变换
7. 输出已存在时先删除再重建
8. 属性按 spot、自身请求上下文、中心点上下文、界面状态字段平铺保存，并增加 `source_crs`
9. 若单个候选点缺失坐标、坐标非法或写出失败，则记录异常并继续处理其它记录

### 9.4 日志、摘要与进度

- 日志与摘要落在输出 GPKG 同目录
- 命令行输出至少包含：
  - Tool10 开始/结束
  - 输入布局检测阶段
  - 流式解析与导出阶段
  - GPKG 收尾阶段
  - 当前记录进度与失败统计
- 摘要至少包含：
  - `input_path`
  - `output_path`
  - `input_format`
  - `input_record_count`
  - `spot_candidate_count`
  - `all_spot_output_count`
  - `recommended_spot_output_count`
  - `failed_spot_count`
  - `source_crs`
  - `output_crs`
  - `layer_names`
  - `field_names`
  - `field_name_mapping`
  - `coordinate_source_summary`
  - `error_reason_summary`

## 10. 非范围

当前非范围包括：

- Tool11+
- Tool3 全量重写
- 复杂 manifest 治理
- 数据库落仓
- 复杂产线编排
- 为未来扩展提前搭重型框架
- 对 Tool1 至 Tool5 的无关业务重构

## 11. 风险与边界

- 必须防止 `T00` 从内部工具集合扩张为业务生产模块
- Tool6 若输入 CRS 缺失，必须明确阻塞，不得静默猜测
- Tool6 的 GeoJSON 输出采用项目内 `EPSG:3857` 约定，不应误宣称为严格标准 GeoJSON
- Tool7 允许目录参数驱动，但只能接收目录参数，不能顺手演化成复杂批处理框架
- Tool7 若遇到字段名与 GPKG 保留列冲突，必须显式记录最小重命名映射
- Tool10 只固化 `data.spots` 上车点导出，不扩大为通用 JSON 数据湖或业务生产模块

## 12. 进入后续阶段的门禁

满足以下条件后，可继续进入后续增量实现或扩展：

1. `spec / plan / tasks / README / AGENTS / INTERFACE_CONTRACT / architecture/*` 口径一致
2. Tool1-Tool7、Tool9、Tool10 的输入、输出、覆盖、异常与摘要语义稳定
3. 不改变 `T00` 作为内部工具模块的定位
4. 新工具进入 `T00` 前，先补规格与契约
