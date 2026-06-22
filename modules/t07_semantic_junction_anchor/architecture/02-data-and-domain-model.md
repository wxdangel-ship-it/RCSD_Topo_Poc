# 02 数据与领域模型

## 1. 上下游数据关系

T07 消费 SWSD `nodes.gpkg`、DriveZone、RCSDIntersection、可选 RCSDNode 和 T05 `intersection_match_all.geojson`。T07 输出带 `has_evd / is_anchor / anchor_reason` 的 nodes、T07 版 RCSDIntersection anchor surface、`intersection_match_t07.geojson` 和 `t07_swsd_rcsd_relation_evidence.*`，供 T03/T04/T05 消费。

## 2. 核心业务对象

| 对象 | 业务含义 |
|---|---|
| semantic junction | 按 `mainnodeid` 聚合的 SWSD 语义路口；空 `mainnodeid` 退化为 singleton。 |
| representative node | 语义路口代表 node，多节点组必须 `id == mainnodeid`。 |
| evidence area | `DriveZone ∪ RCSDIntersection` 形成的 Step1 证据面。 |
| RCSDIntersection anchor surface | Step2 可消费 existing surface 锚定结果。 |
| T05 relation backfill | Step3 消费 T05 成功 relation 对 `is_anchor=no` 候选补锚。 |
| relation evidence | T07 向 T05 发布的 handoff 关系证据。 |

## 3. 关键字段语义

- `has_evd / is_anchor / anchor_reason` 只写 representative node。
- `kind_2` 是 T07 当前唯一正式类型字段。
- `kind_2=2048` 只有在 Step2 满足 single-surface / single-SWSD / single-RCSD strict 条件时才建立 surface 成功关系；否则保持 `no / NULL`，由 T03/T04 或 Step3 T05 relation 补锚继续处理。
- Step3 只接受 `status=0 / base_id!=0` 且 base_id 存在于输入 RCSDNode `id/mainnodeid` 的 relation。
- T07 handoff 主键必须 canonical normalization，避免 `"622700016.0"` 与 `"622700016"` 分裂。

## 4. 数据流

1. Step1 按 semantic junction 组装代表 node，判断全组 node 是否命中 evidence area 或 1.5m 容差。
2. Step2 只对 `has_evd=yes` 的代表 node 判定 `is_anchor`。
3. Step2 输出 nodes、surface handoff、relation evidence、node error 和 summary。
4. Step3 先从 Step2 surface 中推导 1V1 RCSDNode relation，再从 T05 relation 中补锚候选。
5. Step3 执行 cardinality QC，输出 `intersection_match_t07.geojson` 和合并后的 T07 relation evidence。

## 5. 领域边界

T07 是已有路口面 relation 的前置判断，不是 Segment 模块。它输出的 relation evidence 仍需由 T05 统一发布到项目级主 relation 表。
