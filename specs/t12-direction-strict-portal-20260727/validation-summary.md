# Validation Summary：T12 direction-strict portal

## 1. 自动化回归

- WSL Python：`/mnt/e/Work/RCSD_Topo_Poc/.venv/bin/python`
- 隔离源码：`PYTHONPATH=/mnt/e/Work/RCSD_Topo_Poc__wt_t12_directional_portal_20260727/src`
- T10 + T12：`116 passed`，仅有 2 条既有 pyproj/NumPy deprecation warning。
- `git diff --check`：通过。
- 生产源码、脚本、模块文档和测试未包含本次问题对象 ID；所有变更 `.py` 均小于 `100 KB`。

## 2. `1026960` 真实数据回归

- 报告：`outputs/_work/t12_direction_strict_1026960_validation_v3/validation-report.json`
- Schema：`2026-07-27.t12_frcsd_quality_audit.v5`
- 状态：`passed`
- 候选：35；自动确认：10；自动排除：25；人工待定：0。
- 确认问题类型：`directed_carrier_missing=8`、`required_local_connectivity_missing=2`。
- 验证工具逐项比对 10 个冻结确认 Segment 集合，未发生缺失或新增。

## 3. GIS 与质量证据

- CRS：所有输入和处理 CRS 均为 `EPSG:3857`，本次未发生坐标转换。
- 几何：Segment、SWSD Road/Node、FRCSD Road/Node、RCSDIntersection、DriveZone 的无效几何均为 0。
- 拓扑：FRCSD Road endpoint 缺失为 0；portal policy 明确为 source=`directed_outgoing_nodes`、target=`directed_incoming_nodes`、undirected=`diagnostic_only`。
- 几何语义：正式等价 carrier 只接受按 Road `Direction` 可行的 directed path；无向路径只解释“有物理走廊但当前方向不通”。
- Silent fix：`false`，未修改任何输入几何或拓扑。
- 追溯：报告保留解析后的输入路径、FRCSD Road/Node SHA-256、运行环境、参数、输出路径和分阶段耗时。
- 性能：1267 个 Segment、4289 条 FRCSD Road、4762 个 FRCSD Node；总耗时约 `6.54s`，candidate audit 约 `3.19s`。

## 4. 尚待内网数据确认

当前本机没有用户所查完整内网版本中 Road `5885111744069971/5885111744069974` 的原始 Road/Node/alias/portal 数据，因此尚不能声称目标 Segment 已从内网结果中消失。需用同版本完整数据仅重跑 T12，并依据 v5 输出的 `directional_portal_status`、`anchor_portals` 和 directed carrier path 复核；不得用旧版本 Road ID 或本地裁剪样本替代该确认。
