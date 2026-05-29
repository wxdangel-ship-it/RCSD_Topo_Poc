# 10 Quality Requirements

## 可理解

- 文档必须直接说明 `kind_2` 处理范围、代表 node 规则与三字段写值规则。
- summary / audit 必须能解释 processed、skipped、business no 与执行失败。

## 可运行

- runner 必须能在无 Segment 输入下运行。
- Step1 / Step2 应可独立运行，也应可组合运行；Step3 必须独立运行，不并入 Step1 / Step2 脚本。

## 可诊断

- `representative_node_missing`、字段缺失、CRS 缺失、geometry 缺失必须可追溯。
- `fail1 / fail2` 必须输出涉及语义路口与 `RCSDIntersection` 的审计信息。
- `kind_2 = 64 / 128 / 2048` 的 Step2 专属分流必须可从 summary / audit / 输出字段解释，不得误进入 `fail1 / fail2`。
- Step2 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.json` 必须可追溯到 Step2 代表 node 判定与命中的 `RCSDIntersection`。
- Step3 的 relation 缺失、relation 失败、重复 `target_id`、RCSD `base_id` 不存在必须可从 audit / summary 解释。
- Step3 `t07_rcsdintersection_anchor_surface.gpkg` 必须复制 Step2 surface 结果；Step3 `t07_swsd_rcsd_relation_evidence.json` 必须合并 Step2 evidence 与 `intersection_match_tool7.geojson` 成功补锚成果，同一 `target_id` 以 Step3 成功补锚行覆盖，并显式记录 Step2 / Step3 锚定数量。

## GIS 正确性

- CRS 变换必须明确、可解释、可复现。
- `DriveZone` 与 `RCSDIntersection` 空间判定必须在同一 CRS 下完成。
- Step3 relation 输出 `intersection_match_tool7.geojson` 必须保持 T05 relation 输出 CRS `CRS84`。
- 不允许用隐式 CRS 默认值或几何猜测掩盖输入问题。

## 可治理

- 不新增 repo 官方 CLI。
- 除已登记的 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 与 `scripts/t07_run_step3_intersection_match_innernet.sh` 外，不新增其它 repo 级脚本入口。
- 不把 T02 Stage3 / Stage4 或 Segment 逻辑带入 T07。
- 模块文档、实现与测试必须保持一致。

## 性能可验证

- GPKG 输出必须复用 T08 的直接 SQLite GeoPackage 写出路径，避免 Fiona 逐要素 sink 写出成为 full-input 主要瓶颈。
- Step3 copy-update 输出必须补齐 `gpkg_ogr_contents` 与增删触发器，使 QGIS 旧版 OGR provider filter 后的图层要素计数与实际过滤结果一致。
- Step3 在安全条件满足时必须使用 GPKG copy + SQLite 字段更新和 CRS84 relation 原样筛选快路径，避免无业务必要的节点几何重写与 relation 投影。
- perf 输出至少记录 node 数、语义路口数、处理数、跳过数、候选数、冲突数、总耗时与 `stage_timings`。
- `stage_timings` 至少区分读取、空间索引、语义路口准备、业务处理、冲突处理和写出阶段。
