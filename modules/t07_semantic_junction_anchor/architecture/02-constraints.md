# 02 Constraints

## 业务约束

- `kind_2` 是当前唯一正式类型字段，不使用 `Kind_2`。
- `kind_2` 范围判断以代表 node 为准。
- 仅处理代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}`。
- 非处理范围的语义路口，`has_evd / is_anchor / anchor_reason` 均为 `NULL`。
- Step2 仅处理 `has_evd = yes` 的语义路口。
- `fail2` 优先于 `fail1`。

## 数据约束

- `nodes` 必须包含 `id / mainnodeid / kind_2 / geometry`。
- Step2 输入 `nodes` 必须包含 `has_evd`。
- `DriveZone` 与 `RCSDIntersection` 必须是可用于空间命中的面状 geometry。
- 空间判定必须统一到 `EPSG:3857`。
- 缺少 CRS、字段或 geometry 时不得 silent fallback。

## 边界约束

- 不读取 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 Segment 工件。
- 不新增 repo CLI、`tools/`、模块 `run.py` 或模块 `__main__.py`。
- 除已登记的 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 外，不新增其它 repo 级脚本入口。
- 不根据样本反推字段语义。
