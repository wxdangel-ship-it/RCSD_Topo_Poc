# T00 Utility Toolbox

> 本文件是 `T00` 的操作者入口与固定脚本总览。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实冲突，以后者为准。

## 模块简介

`T00` 是 `RCSD_Topo_Poc` 的 Utility Toolbox / 工具集合模块，用于承接项目内的数据整理、实验准备、辅助检查、问题排查与辅助图层预处理。

## 定位与作用

- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不直接产出 RCSD 业务要素
- `T00` 为项目内工具提供统一落仓位置、固定脚本入口和轻量治理边界

## 当前收录工具

- Tool1：整理全量 Patch 矢量目录并初始化统一 `patch_all` 骨架
- Tool2：对每个 Patch 的 `DriveZone` 生成 `DriveZone_fix.geojson`，再汇总为根目录 `DriveZone.geojson`
- Tool3：对全量 `Intersection` 做逐 Patch 预处理后汇总输出
- Tool4：按 `A200_road.id = rc_patch_road.road_id` 给一层路网写入 `patch_id`
- Tool5：基于 Tool4 输出与 SW 原始路网给一层路网写入原始 `kind`
- Tool6：将 `A200_node.shp` 导出为保留原始属性的 `nodes.geojson`
- Tool7：将指定目录下顶层 `GeoJSON` 批量导出为同名 `GPKG`
- Tool9：对全量 `DivStripZone` 做逐 Patch 预处理并汇总输出
- Tool10：将指定 JSON / NDJSON 中的 `data.spots` 上车点导出为单个双图层 `GPKG`

## 文档角色

- `architecture/*`：长期结构与风险说明
- `INTERFACE_CONTRACT.md`：稳定输入、输出、覆盖、异常与摘要契约
- `AGENTS.md`：模块级 durable guidance
- `README.md`：操作者入口与固定脚本总览

## 与业务模块的关系

`T00` 只承担辅助支持角色，不替代正式业务模块，也不承接地图业务要素生成逻辑。

## 统一规则摘要

- Patch 子目录统一使用 `Vector/`
- Tool2 / Tool3 / Tool6 的几何处理统一在 `EPSG:3857`
- Tool2 单 Patch 膨胀 / 腐蚀参数默认 `1m`
- Tool4 / Tool5 通过脚本头部 `TARGET_EPSG` 固定目标 CRS，默认 `3857`
- Tool5 对 `A200_road_patch` 与 SW 允许分别配置默认 CRS
- Tool7 是经批准的参数驱动例外，目录通过脚本参数给定，且只扫描顶层 `.geojson`
- Tool10 是经批准的参数驱动入口，输入 JSON 通过脚本参数给定
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

## Tool9 备注

- Tool9 读取 `patch_all/<PatchID>/(Vector|vector)/DivStripZone.geojson`
- 每个 Patch 输出 `DivStripZone_fix.geojson` 并写入 `patchid`
- 根目录 `DivStripZone.gpkg` 为逐 Patch 汇总结果，保留 `patchid`

## Tool10 备注

- Tool10 读取调用参数指定的 JSON / NDJSON 文件
- Tool10 默认输出输入文件同目录同名 `.gpkg`，也可通过 `--output` 指定
- Tool10 在一个 GPKG 内输出两个图层：`pickup_spots_all` 与 `pickup_spots_recommended`
- `pickup_spots_all` 一条要素对应 `data.spots` 数组中的一个候选上车点
- `pickup_spots_recommended` 只包含 `isRecommend` 为真值的候选上车点
- 几何只取 `spots[i].lon/lat`，直接按原始经纬度写入 GPKG，不使用顶层 `lon/lat` 或 `data.location.lon/lat`

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
make env-sync
make doctor
```

```bash
.venv/bin/python scripts/t00_tool1_patch_directory_bootstrap.py
.venv/bin/python scripts/t00_tool2_drivezone_merge.py
.venv/bin/python scripts/t00_tool3_intersection_merge.py
.venv/bin/python scripts/t00_tool4_a200_patch_join.py
.venv/bin/python scripts/t00_tool5_a200_kind_enrich.py
.venv/bin/python scripts/t00_tool6_node_export.py
.venv/bin/python scripts/t00_tool7_geojson_to_gpkg.py /mnt/d/TestData/POC_Data/some_directory
.venv/bin/python scripts/t00_tool9_divstripzone_merge.py
.venv/bin/python scripts/t00_tool10_json_point_export.py /mnt/d/TestData/poi/beijing_1334198.json
```

默认数据根位于：

- `/mnt/d/TestData/POC_Data/patch_all`
- `/mnt/d/TestData/POC_Data/first_layer_road_net_v0`
- `/mnt/d/TestData/POC_Data/first_layer_road_net_v1_patch`

说明：

- `T00` 官方入口采用 repo root `scripts/` 下的固定脚本，不新增模块级私有 `python -m` 入口。
- 若后续新增工具脚本，必须先满足 repo root `AGENTS.md` 的入口治理规则，并同步更新仓库入口注册表。
