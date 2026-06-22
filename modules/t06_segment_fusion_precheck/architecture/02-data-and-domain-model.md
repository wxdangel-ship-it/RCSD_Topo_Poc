# 02 数据与领域模型

## 1. 上下游数据关系

T06 消费 T01 `segment.gpkg / roads.gpkg / nodes.gpkg` 与 T05 `intersection_match_all.geojson / rcsdroad_out.gpkg / rcsdnode_out.gpkg`。Step3 可选消费 T03/T04/T05/T07 surface 与 T04 audit 做 surface-assisted closure。T06 输出 F-RCSD Road / Node 和 SWSD-FRCSD Segment relation，供 T09 恢复通行规则、供 T10 组织 Case 证据。

## 2. 核心业务对象

| 对象 | 业务含义 |
|---|---|
| SWSD Segment | T01 输出的待替换道路承载单元。 |
| final fusion unit | Step1 认定可进入 Step2 审查的 SWSD Segment。 |
| pair nodes | Segment 两端 hard required SWSD 语义路口。 |
| junc nodes | Segment 内部通过和侧向阻断语义路口，Step2 中作为 optional 审计对象。 |
| T05 relation | SWSD 语义路口到 RCSD 语义路口的上游主关系。 |
| RCSDSegment candidate | 在 SWSD buffer 内构造并收缩后的 RCSD corridor 候选。 |
| replaceable | 通过硬审计和特殊组门控的可替换对象。 |
| replacement plan | Step2 发布给 Step3 的正式执行边界。 |
| problem registry | Step2 对失败、已解决、已覆盖或需上游迭代问题的回流登记。 |
| F-RCSD | Step3 输出的融合后 Road/Node 网络。 |

## 3. 关键字段语义

- `pair_nodes` 是 Step2 hard required；两端必须是不同 SWSD 语义路口。
- `junc_nodes` 是 optional 内部通过 + 侧向阻断，不是 Step2 hard-stop。
- `status=0 / base_id>0` 的 T05 relation 才能用于 RCSD 映射。
- `formway & 128 != 0` 表示提前右转；T06 需要识别、审计和在特定 corridor 条件下保留。
- `execution_scope` 表达 replacement plan 的执行范围，至少包括 `standard_segment / special_junction_group_internal / path_corridor_group`。
- `source=1` 表示 RCSD 数据，`source=2` 表示 SWSD 数据；Step3 不重写原始 id，依赖 source 区分冲突。
- `relation_status=replaced+retained_swsd` 表示正式 RCSD 替换之外还保留局部 SWSD carrier。

## 4. 数据流

1. Step1 解析 T01 Segment 的 `pair_nodes / junc_nodes / roads / sgrade`，输出 candidates、final fusion units 和 rejected。
2. Step2 读取 T05 relation 与 RCSD copy-on-write 网络，基于 SWSD Segment buffer 构建 RCSD candidate graph。
3. Step2 收缩为 pair required semantic nodes 之间的最小 corridor，并执行方向、叶子端点、buffer overlap、视觉连续性、特殊组等硬审计。
4. Step2 输出 replaceable、rejected、probe、repair candidates、failure audit、replacement plan 和 problem registry。
5. Step3 只执行 replacement plan ready action，输出 F-RCSD 和最终拓扑审计。

## 5. 领域边界

T06 的 repair candidate 和 effective relation 是当前 Segment 内的执行策略，不是 T05 relation 主表的修正。T06 的 retained SWSD carrier 是局部通行承载和风险审计，不是正式 RCSD 替换道路。
