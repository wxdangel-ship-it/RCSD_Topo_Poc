# 04 证据与审计

## 1. 审计目标

T07 必须解释代表 node 为什么有 evidence、为什么能或不能 existing-surface anchor，以及 Step3 relation backfill 是否来自显式提供的兼容成功 relation 且 RCSD base 可消费。

## 2. Step1/2 证据

| 证据 | 业务用途 |
|---|---|
| Step1 `nodes.gpkg` | 写入 representative node `has_evd`。 |
| Step2 `nodes.gpkg` | 写入 representative node `is_anchor / anchor_reason`。 |
| `node_error_1 / node_error_2` | fail1 / fail2 冲突审计。 |
| `t07_rcsdintersection_anchor_surface.gpkg` | T07 版 existing surface handoff。 |
| `t07_swsd_rcsd_relation_evidence.csv/json` | T05 可消费 relation evidence。 |
| summary / audit / perf | 计数、输入、CRS、失败和性能证据。 |

## 3. Step3 证据

| 证据 | 业务用途 |
|---|---|
| `intersection_match_t07.geojson` | Step3 发布的 T07 relation。 |
| `relation_cardinality_errors.csv/json` | 1:N、N:1、重复 target 审计。 |
| `t07_step3_audit.csv/json` | relation missing、relation failed、base missing、duplicate 等补锚失败原因。 |
| `t07_step3_summary.json` | Step2 surface relation、兼容 relation backfill、anchor counts 和 CRS。 |

## 4. Cardinality 审计

Step3 对最终候选 relation 执行 T05 同口径基数质检。SWSD 1:N 关系会从 `intersection_match_t07.geojson` 移除并回写 `is_anchor=no`；N:1 与重复 target 必须进入审计，避免后续 T05/T06 误读。

## 5. Handoff 审计

T07 Step2 与 Step3 均维护 `t07_swsd_rcsd_relation_evidence.*`。Step3 需要合并 Step2 evidence 与自身成功补锚 relation，并记录 `step2_anchor_count / step3_anchor_count / total_anchor_count`。
