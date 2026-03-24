# T01 Spec-Kit 治理规格

## 文档定位
- 本文档记录当前 T01 轮次的 spec-kit 治理目标与实施边界。
- 它不承载 steady-state accepted baseline 正文；正式业务规格仍以模块级 source of truth 为准。

## 正式业务规格落点
- 当前 accepted baseline 主体见：
  - [06-accepted-baseline.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md)
- 模块级契约见：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
- 模块入口与使用说明见：
  - [README.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/README.md)

## 当前治理主题
- `T01 GeoPackage I/O migration`

## 当前治理目标
1. 将 T01 官方矢量输入扩展为兼容 `GeoPackage(.gpkg)`、历史 `.gpkt`、`GeoJSON` 与 `Shapefile`。
2. 当同名矢量数据同时存在 `GeoPackage` 与 `GeoJSON/Shapefile` 时，统一优先读取 `GeoPackage(.gpkg)`；历史 `.gpkt` 仅做兼容读取。
3. 将 T01 官方矢量输出统一迁移为 `GeoPackage(.gpkg)`。
4. 裁剪数据脚本继续保留 `GeoJSON` 供快速目视/QGIS 对照，同时新增同名 `GeoPackage(.gpkg)` 输出。
5. 保持 T01 accepted baseline 的业务语义与最终 Segment 结果不因格式迁移而发生隐式变化。

## 范围
- in-scope：
  - `src/rcsd_topo_poc/modules/t01_data_preprocess/*` 中所有直接读写矢量数据的入口与共享工具
  - T01 CLI 入口帮助文本与默认输出命名
  - T01 相关测试
  - T01 当前 spec-kit 过程文档
- out-of-scope：
  - T01 业务算法语义调整
  - 历史 baseline / freeze / history 目录中文件名或历史证据的批量改写
  - 新增独立执行入口
  - T00 / T02 模块实现改造

## 核心约束
- 本轮将“用户口头的 GPKT 诉求”统一解释为 `GeoPackage` 能力升级，但官方正式后缀采用 `.gpkg`，以保持与仓库现有 T00/T02 约定一致。
- 历史 `.gpkt` 后缀只做兼容读取，不作为新的官方输出后缀。
- 不得因为格式迁移顺手改变 `grade_2 / kind_2`、`formway = 128`、`50m gate` 等 accepted baseline 业务规则。
- 不自动刷新 freeze baseline，不因为输出文件后缀变化重写历史审计证据。
- 同名优先规则必须在共享 I/O 层落地，而不是散落在各脚本中各自实现。

## 当前验收口径
- 代码层：
  - 现有 T01 入口均可读取 `GeoPackage(.gpkg)` 输入
  - 同名 `.gpkg` 与 `.geojson/.json/.shp` 同时存在时，默认优先 `.gpkg`
  - 除裁剪数据脚本外，官方矢量输出默认写为 `.gpkg`
  - 裁剪数据脚本同时产出同名 `.geojson` 与 `.gpkg`
- 回归层：
  - `PASS_LOCKED` 与 `FAIL_TARGET` 样例的最终 Segment 业务结果不因格式迁移发生非预期变化
  - `freeze_compare`、`baseline refresh` 等辅助脚本对新旧矢量格式均可工作
- 文档层：
  - `spec.md / plan.md / tasks.md` 反映本轮迁移计划与实施状态
  - 正式 source-of-truth 文档已同步迁移为 `.gpkg` 口径

## 当前样例治理边界
- `PASS_LOCKED`
  - `XXXS / XXXS2 / XXXS3 / XXXS4 / XXXS6 / XXXS8`
- `FAIL_TARGET`
  - `XXXS5 / XXXS7`
- 临时样例基线记录：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`
