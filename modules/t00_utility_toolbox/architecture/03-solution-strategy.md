# 03 Solution Strategy

本文件是 T00 的架构设计 / 需求具体实现策略，说明 `../SPEC.md` 中的工具集合需求如何落地。稳定输入输出、入口和摘要契约见 `../INTERFACE_CONTRACT.md`。

## 1. 策略总览

T00 采用“固定 root script + 模块内 callable + summary/log 审计”的轻量结构。每个工具只完成一个明确的数据整理或格式转换任务：读取历史输入，生成可复跑的派生输出，并用 summary/log 说明输入、输出、计数、CRS、跳过和失败原因。

T00 当前主链不是业务流水线，而是一组独立工具：

1. Tool1 整理 Patch 目录骨架和 `Vector/` 数据归位。
2. Tool2 / Tool3 / Tool9 对 DriveZone、Intersection、DivStripZone 做逐 Patch 处理和汇总。
3. Tool4 / Tool5 / Tool6 对 A200 Road / Node 做历史字段补充和导出。
4. Tool7 / Tool10 / Tool11 执行格式转换或点位导出。

## 2. Tool1 Patch 目录整理

业务目的：

- 将历史 Patch 输入整理为统一 `patch_all/<PatchID>/Vector/` 结构。

业务原则：

- 只做目录归位和文件复制，不解释地图业务语义。

实现与审计约束：

- 复跑时只清空目标 Patch 的 `Vector/`。
- 源 Patch 异常时跳过并记录，不中断全量。

输出与审计：

- `patch_all` 目录骨架。
- summary 记录 patch 数、成功数、失败数、跳过数和异常原因。

## 3. Tool2 / Tool3 / Tool9 面数据预处理与汇总

业务目的：

- 对历史 DriveZone、Intersection、DivStripZone 输入形成可复跑的 per-patch fix 和全局汇总成果。

业务原则：

- per-patch 处理和全局汇总分开；全局汇总不反向改变 per-patch 输出。
- 几何修复只允许最小化，修复失败必须进入 summary。

实现与审计约束：

- Tool2 输出 `DriveZone_fix.geojson` 和根目录 `DriveZone.geojson`。
- Tool3 输出根目录 `Intersection.geojson`。
- Tool9 兼容 `Vector/` 与 `vector/`，输出 `DivStripZone_fix.geojson` 和根目录 `DivStripZone.gpkg`。

输出与审计：

- per-patch 输出、全局输出、log、summary。
- summary 记录输入发现数、处理数、缺失数、失败数、输出要素数和 CRS 来源。

## 4. Tool4 / Tool5 / Tool6 A200 字段补充与导出

业务目的：

- 为历史 A200 Road / Node 补充 patch、kind 或节点导出成果，支持人工排查和历史比较。

业务原则：

- Tool4 只把 `rc_patch_road` 中的 patch 归属写回 A200 Road。
- Tool5 只基于 Tool4 输出和 SW 原始路网补充原始 `kind`。
- Tool6 只导出 A200 Node，不新增业务字段。

实现与审计约束：

- Tool4 overlap 时用逗号拼接多个 `patch_id`，未匹配 road 单独输出。
- Tool5 将 A200 与 SW 输入统一投影后再匹配。
- Tool6 输入 CRS 缺失时阻塞，不根据坐标值猜测。

输出与审计：

- `A200_road_patch.geojson`、`A200_road_patch_unmatched.geojson`、`A200_road_patch_kind.geojson`、`nodes.geojson`。
- summary 记录匹配、未匹配、重复、冲突、修复和失败计数。

## 5. Tool7 / Tool10 / Tool11 格式转换与点位导出

业务目的：

- 将人工排查或外部输入转换为项目更容易消费的 GPKG / GeoJSON 形式。

业务原则：

- Tool7 和 Tool11 只扫描指定目录顶层文件，不递归扩张。
- Tool10 只使用 `data.spots[].lon/lat` 生成上车点几何。
- Tool11 CRS 缺失时必须由调用方显式传入 `--default-crs`。

实现与审计约束：

- Tool7 为每个顶层 `.geojson` 输出同名 `.gpkg`。
- Tool10 输出 `pickup_spots_all` 与 `pickup_spots_recommended` 两个图层。
- Tool11 优先使用 `ogr2ogr`，失败时才回退到流式 JSON 或 SQLite GPKG 路径。

输出与审计：

- 同名 `.gpkg` / `.geojson`、双图层 GPKG、summary 和 log。
- summary 记录文件数、要素数、写出引擎、失败原因和输出路径。

## 6. 实现分层

- `common.py`：CRS、IO、日志、几何最小修复和 summary 写出。
- `patch_directory_bootstrap.py`：Tool1。
- `drivezone_merge.py`、`intersection_merge.py`、`divstripzone_merge.py`：Tool2 / Tool3 / Tool9。
- `road_patch_join.py`、`road_kind_enrich.py`、`shapefile_geojson_export.py`：Tool4 / Tool5 / Tool6。
- `geojson_to_gpkg_export.py`、`json_point_to_gpkg_export.py`、`mif_to_vector_export.py`：Tool7 / Tool10 / Tool11。
- `scripts/t00_tool*.py`：root script 入口和默认路径装配。

实现构件映射只用于帮助维护，不替代工具业务说明。

## 7. 输出策略

- formal 支撑输出：各工具生成的派生矢量、summary 和 log。
- review-only 输出：当前无稳定 review-only 输出。
- internal / recovery 输出：summary 和 log 同时承担诊断和复跑定位用途。

## 8. 性能与观测策略

- 批量工具必须输出阶段级进度。
- per-patch / per-file / per-record 处理应记录计数和失败原因。
- Tool11 大文件转换优先走 GDAL 原生路径，避免把格式转换变成 Python 逐要素主路径。
