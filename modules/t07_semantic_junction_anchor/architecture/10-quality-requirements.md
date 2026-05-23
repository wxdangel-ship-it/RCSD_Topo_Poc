# 10 Quality Requirements

## 可理解

- 文档必须直接说明 `kind_2` 处理范围、代表 node 规则与三字段写值规则。
- summary / audit 必须能解释 processed、skipped、business no 与执行失败。

## 可运行

- runner 必须能在无 Segment 输入下运行。
- Step1 / Step2 应可独立运行，也应可组合运行。

## 可诊断

- `representative_node_missing`、字段缺失、CRS 缺失、geometry 缺失必须可追溯。
- `fail1 / fail2` 必须输出涉及语义路口与 `RCSDIntersection` 的审计信息。

## GIS 正确性

- CRS 变换必须明确、可解释、可复现。
- `DriveZone` 与 `RCSDIntersection` 空间判定必须在同一 CRS 下完成。
- 不允许用隐式 CRS 默认值或几何猜测掩盖输入问题。

## 可治理

- 不新增 repo 官方 CLI。
- 除已登记的 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 外，不新增其它 repo 级脚本入口。
- 不把 T02 Stage3 / Stage4 或 Segment 逻辑带入 T07。
- 模块文档、实现与测试必须保持一致。

## 性能可验证

- GPKG 输出必须复用 T08 的直接 SQLite GeoPackage 写出路径，避免 Fiona 逐要素 sink 写出成为 full-input 主要瓶颈。
- perf 输出至少记录 node 数、语义路口数、处理数、跳过数、候选数、冲突数、总耗时与 `stage_timings`。
- `stage_timings` 至少区分读取、空间索引、语义路口准备、业务处理、冲突处理和写出阶段。
