# T00 Utility Toolbox

## 模块简介

`T00` 是 `RCSD_Topo_Poc` 的 Utility Toolbox / 工具集合模块，用于承接项目内的数据整理、实验准备、辅助检查、问题排查与辅助图层预处理。

## 定位与作用

- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不直接产出 RCSD 业务要素
- `T00` 为项目内工具提供统一落仓位置、固定脚本入口和轻量治理边界

## 当前收录工具

- Tool1：整理全量 Patch 矢量目录并初始化统一 `patch_all` 骨架
- Tool2：对每个 Patch 的 `DriveZone` 生成 `DriveZone_fix.geojson`，再合并为根目录全局 `DriveZone.geojson`
- Tool3：对全量 `Intersection` 做逐 Patch 预处理后汇总输出
- Tool4：按 `A200_road.id = rc_patch_road.road_id` 给一层路网写入 `patch_id`
- Tool5：基于 Tool4 输出与 SW 原始路网给一层路网写入原始 `kind`
- Tool6：将 `A200_node.shp` 导出为保留原始属性的 `nodes.geojson`
- Tool7：将指定目录下顶层 `GeoJSON` 批量导出为同名 `GPKG`

## 模块状态

当前为直接增量实现状态：

- Tool1 已完成
- Tool2 / Tool4 / Tool5 已完成前序增量调整
- Tool3 维持既有实现
- Tool6 为本轮新增导出工具
- Tool7 为目录参数驱动的批量格式转换工具

## 与业务模块的关系

`T00` 只承担辅助支持角色，不替代正式业务模块，也不承接地图业务要素生成逻辑。

## 统一规则摘要

- Patch 子目录统一使用 `Vector/`
- Tool2 / Tool3 / Tool6 的几何处理统一在 `EPSG:3857`
- Tool4 / Tool5 通过脚本头部 `TARGET_EPSG` 固定目标 CRS，默认 `3857`
- Tool5 对 `A200_road_patch` 与 SW 允许分别配置默认 CRS
- Tool7 是经批准的参数驱动例外，目录通过脚本参数给定，且只扫描顶层 `.geojson`
- 输出已存在时先删除再重建
- 命令行执行过程中必须提供阶段级与 Patch / 记录级进度输出

## Tool6 备注

- Tool6 按项目当前要求输出 `EPSG:3857` 的 GeoJSON
- 这是项目内约定输出，不以严格 RFC 7946 互操作为目标
- Tool6 不做额外业务字段加工，不新增无关字段

## Tool7 备注

- Tool7 将指定目录下的顶层 `.geojson` 逐个转换成同目录同名 `.gpkg`
- Tool7 不递归子目录
- Tool7 默认沿用 GeoJSON 自身 CRS；若 GeoJSON 缺失 `crs` 元数据，则按仓库现有口径默认视为 `EPSG:4326`

## 文档入口

- 规格基线：[`../../specs/t00-utility-toolbox/spec.md`](../../specs/t00-utility-toolbox/spec.md)
- 阶段计划：[`../../specs/t00-utility-toolbox/plan.md`](../../specs/t00-utility-toolbox/plan.md)
- 任务清单：[`../../specs/t00-utility-toolbox/tasks.md`](../../specs/t00-utility-toolbox/tasks.md)
- 接口契约：[`INTERFACE_CONTRACT.md`](INTERFACE_CONTRACT.md)
- Agent 约束：[`AGENTS.md`](AGENTS.md)
- 模块架构：[`architecture/01-introduction-and-goals.md`](architecture/01-introduction-and-goals.md)

## 运行入口

内网 WSL 固定执行方式：

```bash
python3 scripts/t00_tool1_patch_directory_bootstrap.py
python3 scripts/t00_tool2_drivezone_merge.py
python3 scripts/t00_tool3_intersection_merge.py
python3 scripts/t00_tool4_a200_patch_join.py
python3 scripts/t00_tool5_a200_kind_enrich.py
python3 scripts/t00_tool6_node_export.py
python3 scripts/t00_tool7_geojson_to_gpkg.py /mnt/d/TestData/POC_Data/some_directory
```

默认数据根位于：

- `/mnt/d/TestData/POC_Data/patch_all`
- `/mnt/d/TestData/POC_Data/first_layer_road_net_v0`
- `/mnt/d/TestData/POC_Data/first_layer_road_net_v1_patch`
