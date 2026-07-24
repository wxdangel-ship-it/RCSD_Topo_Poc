# Data Model: P05 M1

## 1. M1Config

| 字段 | 类型 | 含义 |
|---|---|---|
| `m0_run_root` | Path | 冻结 M0 run；必须通过 manifest/output hash 校验。 |
| `output_root/run_id` | Path/string | 不可变 M1 run 根。 |
| `seed` | int | 数据、模型和训练随机种子。 |
| `neighbor_distance_m` | float | 空间邻接距离；仅用于图边。 |
| `polyline_points` | int | 折线固定采样点数。 |
| `hidden_dim/layers/dropout` | number | 模型超参数。 |
| `entity_guard_hops` | int | 低优先级 split 移除的邻域层数，M1 默认 1。 |

## 2. InputArtifact

记录 `sample_id/role/path/sha256/source_run_summary/crs/schema/feature_count`。输入角色至少包含 `t01_roads/t01_segment/t03_nodes/t04_nodes/t05_rcsdroad_out/t05_rcsdnode_out/t07_nodes`；T06 roles 标记为 `label_only=true`。

## 3. CandidateRoad

| 字段 | 含义 |
|---|---|
| `candidate_key` | `sample_id + source_role + canonical id` 的审计键，不进入模型。 |
| `source_role` | `t01_roads` 或 `t05_rcsdroad_out`。 |
| `geometry_features` | 归一化固定点采样及派生几何。 |
| `attribute_features` | Road 原始属性的受控编码与 missing mask。 |
| `endpoint_features` | 端点与 T03/T04/T05/T07 node 的可用输入特征。 |
| `edge_index/edge_type` | 共享端点、有向或空间邻接。 |
| `split` | 经 entity guard 后唯一集合。 |
| `supervision_weight` | Case `0.7`；Segment target `0.7`、context `0.3`。 |

## 4. RoadOperationLabel

| 字段 | 含义 |
|---|---|
| `operation` | `DROP/KEEP/SPLIT_1/SPLIT_2/SPLIT_3`。 |
| `output_road_ids` | 仅审计，不进入模型。 |
| `direction/source` | 最终输出属性监督。 |
| `split_fractions` | 沿父 Road 的有序切分比例；不足位置 masked。 |
| `endpoint_targets` | 输出端点坐标/输入 Node 映射。 |
| `target_scope` | `case/target_segment/context`。 |
| `label_weight` | `0.7/0.3`。 |

## 5. EntityLeakageDecision

记录 canonical entity ID、出现的 sample/split、最终 owner split、被移除 candidate 及一跳邻域、理由和数量。优先级固定为 test、validation、train。

## 6. Prediction

记录 `sample_id/candidate_key/operation probabilities/predicted operation/direction/source/split geometry/confidence/model hash`。确定性基线使用相同 schema。

## 7. MaterializedCase

记录预测 Road/Node 路径、hash、CRS、feature count、重复 ID、端点引用、失败列表和 `silent_fix=false`。任何失败不得以修补后结果替换原预测。

## 8. M1Run

状态：`created -> dataset_ready -> trained -> frozen -> final_evaluated -> passed|failed`。固定 test 在 `frozen` 前不可执行。未达到成功标准时状态为 `failed`，但 run 与证据保持完整。

