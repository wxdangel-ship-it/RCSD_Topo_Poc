# T00 - INTERFACE_CONTRACT

## 1. 模块概览

- 模块 ID：`t00_utility_toolbox`
- 模块名称：`T00 Utility Toolbox`
- 当前工具：
  - Tool1 `Patch 数据整理`
  - Tool2 `DriveZone per-patch fix + 全局 merge`
  - Tool3 `Intersection 逐 Patch 预处理与汇总`
  - Tool4 `A200 road 增加 patch_id`
  - Tool5 `A200 road 增加 SW 原始 kind`
  - Tool6 `A200_node shp 导出 nodes.geojson`
  - Tool7 `目录级 GeoJSON 批量转 GPKG`
  - Tool9 `DivStripZone 预处理与汇总输出`
  - Tool10 `超大 JSON 点记录流式转点 GPKG`

本文件用于固化 `T00` 当前稳定的输入、输出、覆盖、跳过与摘要语义。

## 2. 通用约束

- 路径口径：Patch 子目录统一使用 `Vector/`
- CRS 口径：Tool2 / Tool3 / Tool6 统一 `EPSG:3857`；Tool4 / Tool5 通过 `TARGET_EPSG` 固定目标 CRS，默认 `3857`
- Tool5 输入 CRS 口径：
  - `A200_road_patch` 默认按 `EPSG:3857`
  - SW 原始路网默认按 `EPSG:4326`
  - 两者统一投影到 `TARGET_EPSG` 后再处理
- Tool7 输入 CRS 口径：
  - 优先读取 GeoJSON `crs`
  - 若缺失 `crs`，默认按 `EPSG:4326`
- 修复口径：只允许最小修复；修复失败则跳过并记录异常
- 覆盖口径：旧输出已存在时先删除再重建
- 执行体验：命令行必须输出工具开始/结束、阶段级和 Patch / 记录级进度；Tool7 允许目录参数驱动

## 3. Tool1 契约

### 3.1 输入与输出

- 源目录：`D:\TestData\POC_Data\数据整理\vectors`
- 目标根目录：`D:\TestData\POC_Data\patch_all`
- 正式输出：

```text
<PatchID>/
  PointCloud/
  Vector/
  Traj/
```

### 3.2 覆盖、异常与摘要

- 复跑时只清空目标 `<PatchID>/Vector/`
- 源 Patch 异常时跳过并记失败，不中断全量
- 摘要至少包含：
  - `total_patch_count`
  - `success_count`
  - `failure_count`
  - `skip_count`
  - 每个 Patch 的文件拷贝数
  - 异常原因

## 4. Tool2 契约

- 单 Patch 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DriveZone.geojson`
- 单 Patch fix 输出：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DriveZone_fix.geojson`
- 全局输出：`D:\TestData\POC_Data\patch_all\DriveZone.geojson`
- 输出 CRS：`EPSG:3857`（输出格式为 `GPKG`）

## 5. Tool3 契约

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\Intersection.geojson`
- 输出：`D:\TestData\POC_Data\patch_all\Intersection.geojson`
- 输出 CRS：`EPSG:3857`（输出格式为 `GPKG`）
- 单 Patch 内逐要素做拓扑保持简化
- 全量阶段只汇总，不做面合并

## 6. Tool4 契约

- 输入一：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road.shp`
- 输入二：`D:\TestData\POC_Data\first_layer_road_net_v1_patch\rc_patch_road.shp`
- 正式输出：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch.geojson`
- 异常输出：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch_unmatched.geojson`
- 输出 CRS：`TARGET_EPSG`，默认 `3857`
- overlap 情况下，`patch_id` 记录多个值，按逗号 `,` 拼接

## 7. Tool5 契约

- 输入一：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch.geojson`
- 输入二：`D:\TestData\POC_Data\first_layer_road_net_v0\SW\A200-2025M12-road.geojson`
- 输出：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_road_patch_kind.geojson`
- 输出 CRS：`TARGET_EPSG`，默认 `3857`
- `A200_road_patch` 默认按 `EPSG:3857`
- SW 默认按 `EPSG:4326`
- 两者统一投影到 `TARGET_EPSG=3857` 后再做空间匹配

## 8. Tool6 契约

### 8.1 输入与输出

- 输入：`D:\TestData\POC_Data\first_layer_road_net_v0\A200_node.shp`
- 输出：`D:\TestData\POC_Data\first_layer_road_net_v0\nodes.geojson`
- 输出 CRS：`EPSG:3857`（输出格式为 `GPKG`）

### 8.2 处理契约

- 读取 shp 并审计输入要素数、几何类型、字段列表、输入 CRS
- 若输入 CRS 缺失，不得猜测，直接阻塞并写入摘要
- 若输入 CRS 非 `3857`，先重投影到 `3857`
- 保留原始属性
- 允许最小限度几何修复，仅用于保证导出可执行
- 修复失败或读写失败的要素记入摘要
- 输出文件已存在时先删除再重建

### 8.3 摘要契约

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
- 摘要需显式注明：
  - Tool6 按项目要求输出 `EPSG:3857` GeoJSON
  - 这是项目内约定输出，不保证严格标准 GeoJSON 互操作

## 9. 持久化输出边界

- Tool1：`patch_all` 目录骨架与 `Vector/` 归位是正式输出
- Tool2：per-patch `DriveZone_fix.geojson` 与根目录全局 `DriveZone.geojson` 都是正式输出
- Tool3：根目录全局 `Intersection.geojson` 是正式输出
- Tool4：`A200_road_patch.geojson` 与 `A200_road_patch_unmatched.geojson` 是正式输出
- Tool5：`A200_road_patch_kind.geojson` 是正式输出
- Tool6：`nodes.geojson` 是正式输出
- Tool7：指定目录下与每个 `.geojson` 同名的 `.gpkg` 是正式输出
- Tool10：同目录同名 `*.gpkg` 点数据导出文件是正式输出

## 10. Tool7 契约

- 输入：脚本参数给定的目录路径
- 扫描范围：仅目录顶层 `.geojson` 文件，不递归子目录
- 输出：每个输入 GeoJSON 在同目录生成一个同名 `.gpkg`
- 输出格式：`GPKG`
- 图层命名：默认使用输入文件 stem 的安全化结果
- 保留原始属性；若字段名与 `fid/geom` 等 GPKG 保留列冲突，可做最小重命名并写入摘要
- 几何口径：允许最小修复；修复失败的要素记入文件级摘要
- 覆盖口径：已存在同名 `.gpkg` 时先删除再重建
- 摘要至少包含：
  - `directory_path`
  - `geojson_file_count`
  - `converted_file_count`
  - `failed_file_count`
  - `total_input_feature_count`
  - `total_output_feature_count`
  - `file_results`
  - `error_reason_summary`


## 11. Tool9 契约

- 输入：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DivStripZone.geojson`
- 兼容输入：如存在 `vector/DivStripZone.geojson` 允许读取
- per-patch 输出：`D:\TestData\POC_Data\patch_all\<PatchID>\Vector\DivStripZone_fix.geojson`
- 全局输出：`D:\TestData\POC_Data\patch_all\DivStripZone.gpkg`
- 输出 CRS：`EPSG:3857`（输出格式为 `GPKG`）
- 每个输出要素必须包含 `patchid` 字段
- 覆盖口径：已存在输出先删除再重建
- 摘要至少包含：
  - `total_patch_count`
  - `input_found_count`
  - `processed_patch_count`
  - `fixed_output_count`
  - `skip_missing_count`
  - `skip_error_count`
  - `global_merge_input_count`
  - 输出要素统计与异常原因


## 12. Tool10 契约

- 输入：`D:\TestData\poi\beijing_1334198.json`
- 输出：`D:\TestData\poi\beijing_1334198.gpkg`
- 输出 CRS：`EPSG:4326`（输出格式为 `GPKG`）
- 几何类型：`Point`
- 坐标来源：优先读取顶层 `lon/lat`；若缺失，则回退读取 `data.location.lon/lat`
- 源坐标口径：`lon/lat` 视为 `EPSG:4326`，直接写出，不做坐标变换
- 属性口径：保留顶层属性；嵌套 `dict/list` 会序列化为 JSON 字符串写入属性列
- 输入布局：兼容 `NDJSON` 与 `JSON array`；按流式解析执行，不整体载入内存
- 导出上限：成功导出 `50000` 条 POI 后立即停止
- 覆盖口径：同名 `.gpkg` 已存在时先删除再重建
- 摘要至少包含：
  - `input_path`
  - `output_path`
  - `input_format`
  - `input_record_count`
  - `output_feature_count`
  - `failed_record_count`
  - `source_crs`
  - `output_crs`
  - `max_output_features`
  - `stopped_by_export_limit`
  - `field_names`
  - `field_name_mapping`
  - `coordinate_source_summary`
  - `error_reason_summary`

## 13. 非范围契约

当前不承诺以下能力：

- Tool3 全量重写
- 复杂 manifest 治理
- 数据库落仓
- 重型产线编排
- 超出当前需求的中间产物正式化治理

## 14. 后续实现注意事项

- 参数名、日志文件名和具体 CLI 形式可继续在脚本层补足
- 但不得偏离当前契约语义
- 若新增能力触及非范围项，必须先更新规格与契约
