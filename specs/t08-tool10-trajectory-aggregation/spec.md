# T08 Tool10 轨迹聚合规格

**Feature Branch**: `codex/t08-tool10-trajectory-aggregation`
**Status**: Ready for implementation
**Scope Mode**: SpecKit implementation

## 1. 需求与产品视角

Tool10 接收一个具体 Patch 目录，扫描 `<Patch>/Traj/*/raw_dat_pose.geojson`，将该 Patch 的全部轨迹点预处理为轨迹线，并聚合写入一个 GeoPackage：

```text
<Patch>/Traj/raw_dat_pose.gpkg
  layer: raw_dat_pose
  geometry: LineStringZ
  CRS: EPSG:3857
```

每条源轨迹因断点规则可输出一个或多个要素；所有要素写入同一个 `raw_dat_pose` 图层。审计摘要固定写入 `<Patch>/Traj/raw_dat_pose_summary_tool10.json`。

## 2. 真实数据证据

开发前对 `E:/Work/Highway_Topo_Poc/data/synth_local` 下 8 个由真实轨迹源生成的 Patch 做了只读审计：

- 共 8 个 `raw_dat_pose.geojson`、61,861 个 Point；均声明 `EPSG:4326`，坐标均为三维；
- Z 范围约为 `112.453m` 至 `277.954m`，未发现缺失或非有限 Z；
- 属性稳定包含 `drive_id / frame_id / timestamp`，排序可使用 `frame_id`；
- 多数点间隔约 `0.1s`，XY 转到 `EPSG:3857` 后相邻距离通常约 `1m-4m`；
- Patch `00000009` 按参考默认阈值出现 2 个真实断点，输出应为 3 段，证明必须先投影到米制 CRS 再判断距离断点。

该证据只用于验证方法适配性，不反推或新增上游字段业务语义。

## 3. 方法与处理规则

1. 严格发现 `<Patch>/Traj/*/raw_dat_pose.geojson`；找不到输入时失败。
2. 每个输入必须是 GeoJSON FeatureCollection，且每个要素必须是非空 Point。
3. 输入 CRS 必须由 GeoJSON `crs` 显式声明；缺失时仅允许调用方通过 `--default-crs` 显式补充，不允许按坐标范围猜测。
4. 所有 X/Y 转换到 `EPSG:3857`；Z 不参与二维 CRS 变换，按输入数值原样保留。
5. 每个点必须有有限 X/Y/Z。任一点缺 Z、Z 非有限或几何不合法时整批失败，不补 `0`、不丢点、不静默跳过源文件。
6. 轨迹内排序键优先级为 `seq -> frame_id -> idx -> index -> timestamp -> feature index`，排序稳定且记录实际来源。
7. 相邻点在米制坐标中满足任一条件时切段：距离间隔大于 `10m`、可解析时间间隔大于 `1s`、序号间隔大于 `20,000,000`。时间不可解析且序号连续时，距离阈值放宽为 `25m`，保持 Highway 参考方案行为。
8. 每个输出段至少包含 2 个点；若断点造成单点段则整批失败，禁止因 LineString 限制而静默丢点。
9. 输出前校验输出点总数等于输入点总数，输出所有几何均为 `LineStringZ`。
10. 先完成全量输入校验，再通过同目录临时文件写 GPKG 和 summary；成功后替换正式成果。默认拒绝覆盖，`--overwrite` 才允许替换已有成果。

## 4. 输入输出字段

`raw_dat_pose` 图层每个轨迹段至少包含：

- `traj_id`：`<source_traj_id>__segNNNN`；
- `source_traj_id`、`segment_index`、`point_count`、`split_applied`；
- `order_source`、`start_seq`、`end_seq`；
- `start_timestamp`、`end_timestamp`；
- `drive_ids`：该段直接携带的唯一 `drive_id` 集合；
- `split_reason_before`：该段前一个断点原因；
- `source_path`：相对 Patch 的源文件路径。

summary 记录输入文件、文件大小、解析 CRS、点数、Z 范围、排序来源、切段统计、参数、输出路径、运行环境、耗时和吞吐量。

## 5. 架构与研发视角

- callable：`run_t08_trajectory_aggregation(...)`；
- 正式入口：`scripts/t08_tool10_trajectory_aggregation.py --patch-dir <Patch>`；
- 内网批处理入口：`scripts/t08_tool10_run_patches_innernet.sh PATCH_DIR [PATCH_DIR ...]`，Patch 目录只允许通过位置参数传入；
- 实现位于 `src/rcsd_topo_poc/modules/t08_preprocess/trajectory_aggregation.py`；
- 复用 T08 现有 GPKG writer，不新增依赖，不修改 T00 Tool10；
- `raw_dat_pose.gpkg` 是用户指定的 Tool10 正式命名特例；summary 仍以 `_tool10` 结尾。

## 6. 非目标

- 不做 DriveZone、DivStrip、道路弧段或下游拓扑门控；
- 不平滑、抽稀、吸附、补点或修改 Z；
- 不修改输入 GeoJSON；
- 不新增 repo CLI、`Makefile`、`tools/`、模块 `run.py` 或 `__main__.py`；
- 不把 `drive_id / frame_id / timestamp` 固化为新的上游业务强语义。

## 7. 测试视角

测试必须覆盖：单/多源轨迹聚合、排序、距离/时间/序号切段、Z 保留、`gpkg_geometry_columns.z = 1`、缺 Z/非有限 Z/非法几何/缺 CRS整批失败、显式默认 CRS、覆盖保护、点数守恒、脚本固定落盘路径，以及真实 Patch `00000009` 复制后的 3 段验证。

## 8. QA 视角与验收标准

1. **CRS**：输入 CRS 可追溯，XY 正确转换为 `EPSG:3857`，输出 CRS 元数据正确，Z 原值不变。
2. **拓扑一致性**：只按显式阈值切段，不做 silent fix；点数守恒，单点段失败。
3. **几何语义**：每个要素代表一条源轨迹的连续片段，且为 `LineStringZ`。
4. **审计追溯**：输入、参数、排序来源、断点原因、输出和运行环境均可定位。
5. **性能验证**：summary 提供点数、耗时与 points/s；用 61,861 点真实来源样本验证。
6. 全部轨迹段聚合在一个 `<Patch>/Traj/raw_dat_pose.gpkg` 的 `raw_dat_pose` 图层中。
7. 任一点缺失或包含非有限 Z 时返回失败，且不生成或替换正式输出。
