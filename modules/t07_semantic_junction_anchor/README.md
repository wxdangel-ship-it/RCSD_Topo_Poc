# T07 Semantic Junction Anchor

`t07_semantic_junction_anchor` 是 T02 Step1 / Step2 的语义路口级重构模块，并提供独立 Step3 relation 补锚。当前只做代表 node 的 `has_evd / is_anchor / anchor_reason`，不处理 Segment。

## 当前范围

- Step1：基于 `nodes` 与 `DriveZone` 计算代表 node 的 `has_evd`。
- Step2：基于 `nodes` 与 `RCSDIntersection` 计算代表 node 的 `is_anchor / anchor_reason`。
- Step3：基于 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`，对候选 SWSD 语义路口补写 `is_anchor = yes`。
- `kind_2` 只使用代表 node 字段。
- 仅处理代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}`。

## 非目标

- 不读取、生成或统计 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 `segment.has_evd`。
- 不生成虚拟路口面。
- 不执行 div/merge polygon。
- 不新增 repo CLI；除已登记的内网包装脚本外，不新增其它 repo 脚本入口。

## 当前入口状态

当前模块提供模块内 callable runner；Step1 / Step2 内网执行通过已登记脚本 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 包装，Step3 通过独立脚本 `scripts/t07_run_step3_intersection_match_innernet.sh` 包装。仓库不新增 repo 官方 CLI。

Callable runner：

```python
from rcsd_topo_poc.modules.t07_semantic_junction_anchor import (
    run_t07_semantic_junction_anchor,
    run_t07_step1_has_evd,
    run_t07_step2_anchor_recognition,
    run_t07_step3_intersection_match,
)
```

内网脚本默认读取：

- `NODES_PATH=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.gpkg`
- `DRIVEZONE_PATH=/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg`
- `INTERSECTION_PATH=/mnt/d/TestData/POC_Data/patch_all/RCSDIntersection.gpkg`

上述路径均可通过同名环境变量覆盖；脚本不接受或读取 Segment 输入。

Step3 内网脚本默认读取最近一次 T07 Step2 `nodes.gpkg`、T05 Phase2 `intersection_match_all.geojson` 与输入 `RCSDNode.gpkg`；可通过 `NODES_PATH / INTERSECTION_MATCH_ALL_PATH / RCSDNODE_PATH` 覆盖。

## 关键规则

- 语义路口按 `mainnodeid` 聚合；空 `mainnodeid` 退化为 singleton。
- 多节点组代表 node 必须满足 `id == mainnodeid`。
- `has_evd / is_anchor / anchor_reason` 只写代表 node。
- `kind_2` 不在 `{4, 8, 16, 64, 128, 2048}` 时，三个业务字段均为 `NULL`。
- 处理范围内语义路口必须组内所有 node 均落入或接触 `DriveZone` 才写 `has_evd = yes`；任一组内 node 未命中则写 `has_evd = no`。
- `has_evd = yes` 才进入 Step2。
- Step2 对 `kind_2 = 64 / 128` 基础判定写 `is_anchor = no / anchor_reason = NULL`，后续由专项规则处理；若同一个 `RCSDIntersection` 面对应多个 SWSD 语义路口，仍被 `fail2` 覆盖。
- Step2 对 `kind_2 = 2048` 仅在该组所有 node 均命中同一个且唯一的 `RCSDIntersection` 时基础判定写 `is_anchor = yes / anchor_reason = t`；否则写 `is_anchor = no / anchor_reason = NULL`；若同一个 `RCSDIntersection` 面对应多个 SWSD 语义路口，仍被 `fail2` 覆盖。
- 处理范围内类型保留 T02 `fail2` 语义，且 `fail2 > fail1`。
- Step2 输出 T07 版 T02 handoff 成果：`t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`。
- Step3 处理代表 node `kind_2 in {4, 8, 16, 2048}` 的 SWSD 语义路口，先从 Step2 surface 1V1 推导 SWSD-RCSD 语义路口关系，再对 `has_evd = yes / is_anchor = no` 的候选使用 `intersection_match_all.geojson` 补充关系。
- Step3 relation 补充只接受 `intersection_match_all.geojson` 中 `status = 0` 且 `base_id != 0` 的成功关系；若 `base_id` 在输入 `RCSDNode.id/mainnodeid` 中存在且未被 Step2 surface 1V1 占用，则输出该 relation 到 `intersection_match_t07.geojson`，并把对应 SWSD 代表 node `is_anchor = yes / anchor_reason = NULL`。
- Step3 若 Step2 surface 面内包含多个 RCSD 语义路口，输出 `RCSDNode_error.gpkg`；若最终 SWSD 语义路口关联多个 RCSD 语义路口，则从 `intersection_match_t07.geojson` 移除该 SWSD 的关系并回写 `is_anchor = no`。
- Step3 输出 `t07_rcsdintersection_anchor_surface.gpkg`，内容复制 Step2 surface 结果；同时输出 `t07_swsd_rcsd_relation_evidence.csv/json`，合并 Step2 evidence 与 Step3 `intersection_match_t07.geojson` 成功补锚成果，并记录 Step2 / Step3 各自锚定数量。
- Step3 对内网常规输入启用快路径：`nodes.gpkg` 为 EPSG:3857 时复制后仅更新命中代表 node；T05 `intersection_match_all.geojson` 为 CRS84 时原样筛选 relation，避免不必要的几何投影。

## 输出

Step1 输出：

- `nodes.gpkg`
- `t07_step1_summary.json`
- `t07_step1_audit.csv/json`
- `t07_step1_perf.json`

Step2 输出：

- `nodes.gpkg`
- `node_error_1.gpkg/csv/json`
- `node_error_2.gpkg/csv/json`
- `t07_rcsdintersection_anchor_surface.gpkg`
- `t07_swsd_rcsd_relation_evidence.csv/json`
- `t07_step2_summary.json`
- `t07_step2_audit.csv/json`
- `t07_step2_perf.json`

Step3 输出：

- `nodes.gpkg`
- `intersection_match_t07.geojson`
- `t07_rcsdintersection_anchor_surface.gpkg`
- `RCSDNode_error.gpkg`
- `t07_swsd_rcsd_relation_evidence.csv/json`
- `relation_cardinality_errors.csv/json`
- `t07_step3_summary.json`
- `t07_step3_audit.csv/json`
- `t07_step3_perf.json`

## 文档

- 稳定契约：[INTERFACE_CONTRACT.md](INTERFACE_CONTRACT.md)
- 架构说明：[architecture/](architecture/)
- 变更任务书：[../../specs/t07-semantic-junction-anchor-step12/](../../specs/t07-semantic-junction-anchor-step12/)
