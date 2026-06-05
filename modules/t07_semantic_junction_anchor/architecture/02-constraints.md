# 02 Constraints

## 业务约束

- `kind_2` 是当前唯一正式类型字段，不使用 `Kind_2`。
- `kind_2` 范围判断以代表 node 为准。
- 仅处理代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}`。
- 非处理范围的语义路口，`has_evd / is_anchor / anchor_reason` 均为 `NULL`。
- Step1 对处理范围内语义路口，必须组内所有 node 均落入或接触 `DriveZone` 才写 `has_evd = yes`；任一组内 node 未命中则写 `has_evd = no`。
- Step2 仅处理 `has_evd = yes` 的语义路口。
- Step2 中 `kind_2 = 64 / 128` 基础判定写 `is_anchor = no / anchor_reason = NULL`；若同一个 `RCSDIntersection` 面对应多个 SWSD 语义路口，仍被 `fail2` 覆盖。
- Step2 中 `kind_2 = 2048` 仅当组内所有 node 均命中同一个且唯一的 `RCSDIntersection` 时基础判定写 `is_anchor = yes / anchor_reason = t`，否则写 `is_anchor = no / anchor_reason = NULL`；若同一个 `RCSDIntersection` 面对应多个 SWSD 语义路口，仍被 `fail2` 覆盖。
- 对处理范围内类型，`fail2` 优先于 `fail1` 与基础 `yes / no / t` 判定。
- Step3 处理代表 node `kind_2 in {4, 8, 16, 2048}` 的语义路口，先用 Step2 surface 1V1 推导关系，再对 `has_evd = yes / is_anchor = no` 的候选使用 T05 relation 补充关系。
- Step3 relation 补充只接受 T05 `intersection_match_all.geojson` 中 `status = 0 / base_id != 0` 的成功 relation，并要求 `base_id` 在输入 `RCSDNode.id/mainnodeid` 中存在且未被 Step2 surface 1V1 阶段占用。
- Step3 接受后只写代表 node `is_anchor = yes / anchor_reason = NULL`，并输出 relation 子集 `intersection_match_t07.geojson`。
- Step3 输出 `RCSDNode_error.gpkg` 记录 Step2 surface 面内多个 RCSD 语义路口错误；对最终候选成功 relation 做 T05 同口径基数质检，1:N、N:1 与重复 success target 输出 `relation_cardinality_errors.csv/json`；SWSD 1:N 必须取消该 SWSD 关系并回写 `is_anchor = no`。
- Step2 输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`；Step3 输出复制 Step2 surface 结果的 `t07_rcsdintersection_anchor_surface.gpkg`，并输出合并 Step2 evidence 与 Step3 成功补锚成果的 `t07_swsd_rcsd_relation_evidence.csv/json`。

## 数据约束

- `nodes` 必须包含 `id / mainnodeid / kind_2 / geometry`。
- Step2 输入 `nodes` 必须包含 `has_evd`。
- Step3 输入 `nodes` 必须包含 `has_evd / is_anchor / anchor_reason`，`intersection_match_all.geojson` 必须符合 T05 `target_id / base_id / status / level / is_highway` 规格。
- Step3 输入 `RCSDNode` 必须提供可校验的 `id` 或 `mainnodeid`。
- `DriveZone` 与 `RCSDIntersection` 必须是可用于空间命中的面状 geometry。
- 空间判定必须统一到 `EPSG:3857`。
- Step3 `intersection_match_t07.geojson` 输出 CRS 为 `CRS84`。
- `t07_rcsdintersection_anchor_surface.gpkg` 输出 CRS 为 `EPSG:3857`；`t07_swsd_rcsd_relation_evidence.csv/json` 为非空间 handoff 文件，坐标字段按 `EPSG:3857` 表达。
- 缺少 CRS、字段或 geometry 时不得 silent fallback。

## 边界约束

- 不读取 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 Segment 工件。
- 不新增 repo CLI、`tools/`、模块 `run.py` 或模块 `__main__.py`。
- 除已登记的 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 与 `scripts/t07_run_step3_intersection_match_innernet.sh` 外，不新增其它 repo 级脚本入口。
- 不根据样本反推字段语义。
