# T07 模块规格：语义路口 1:1 锚定与 Relation 补锚

## 1. 模块定位

T07 迁移 T02 Step1 / Step2 的语义路口级锚定能力，并提供独立 Step3 relation 补锚。模块只处理代表 node 的 `has_evd / is_anchor / anchor_reason` 与 T07 版 relation evidence，不处理 Segment、不生成虚拟路口面。

## 2. 业务目标

- 基于 `DriveZone ∪ RCSDIntersection` 判断 SWSD 语义路口是否具备可锚定 evidence。
- 基于 `RCSDIntersection` 执行已有路口面 1:1 锚定，保留 T02 `fail1 / fail2` 语义。
- 基于 T05 `intersection_match_all.geojson` 对部分 `is_anchor = no` 的已有路口特征做 relation 补锚。
- 输出 T07 版 handoff surface 与 relation evidence，供 T05 relation production 消费。
- 当前作为提升替换率的兜底措施，未来 RCSD 滚动构图方案下不作为长期依赖。

## 3. 当前范围

### 3.1 正式支持

- Step1：计算代表 node `has_evd`。
- Step2：计算代表 node `is_anchor / anchor_reason`。
- Step3：基于 T05 relation 对 `kind_2 in {4,8,16}` 的候选补锚。
- 处理代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}` 的 Step1/2 字段。
- 输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.*`。

### 3.2 当前非目标

- 不读取、生成或统计 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 `segment.has_evd`。
- 不生成虚拟路口面。
- 不执行 div/merge polygon。
- 不新增 repo CLI。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T08 / SWSD `nodes` | 提供 `kind_2` 与语义路口分组基础。 |
| 上游 | DriveZone / RCSDIntersection | 提供 Step1/Step2 空间 evidence。 |
| 上游 | T05 `intersection_match_all` | 提供 Step3 relation 补锚来源。 |
| 下游 | T03 / T04 | 消费 T07 后的 nodes 状态作为后续虚拟锚定上下文。 |
| 下游 | T05 | 消费 T07 handoff surface 与 relation evidence。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| `nodes.gpkg` | SWSD 语义路口分组、代表 node 和状态写回。 |
| `DriveZone.gpkg` | Step1 evidence 面。 |
| `RCSDIntersection.gpkg` | Step1/Step2 existing surface 锚定面。 |
| `intersection_match_all.geojson` | Step3 relation 补锚来源。 |
| `RCSDNode.gpkg` | Step3 校验 `base_id` 是否存在。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| Step1 `nodes.gpkg` | 写入代表 node `has_evd`。 |
| Step2 `nodes.gpkg` | 写入代表 node `is_anchor / anchor_reason`。 |
| `node_error_1 / node_error_2` | fail1/fail2 审计。 |
| `t07_rcsdintersection_anchor_surface.gpkg` | T07 版 surface handoff。 |
| `intersection_match_t07.geojson` | Step3 relation 补锚成果。 |
| `t07_swsd_rcsd_relation_evidence.*` | T05 可消费 relation evidence。 |
| `relation_cardinality_errors.*` | Step3 relation 基数错误审计。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| 语义路口组装 | 按 `mainnodeid` 聚合，空 `mainnodeid` 退化为 singleton，多节点组代表 node 必须 `id == mainnodeid`。 |
| Step1 has_evd | 代表 node 类型在处理范围内时，要求组内所有 node 命中 `DriveZone ∪ RCSDIntersection` 才写 `yes`。 |
| Step2 anchor | 只对 `has_evd = yes` 的语义路口基于 `RCSDIntersection` 判定 `yes/no/fail1/fail2`。 |
| Step2 handoff | 输出 T07 版 surface 与 relation evidence。 |
| Step3 surface 1V1 | 基于 Step2 surface 查询 RCSDNode，唯一 RCSD 语义路口时建立 relation。 |
| Step3 T05 relation 补锚 | 对候选 `is_anchor = no` 的 existing surface 路口消费 T05 成功 relation。 |
| Step3 基数质检 | 对 1:N、N:1、重复 target 进行压制和回写。 |

## 8. 什么是对

- `has_evd / is_anchor / anchor_reason` 只写代表 node。
- `kind_2 = 2048` 不在 T07 建立 SWSD-RCSD 成功 relation，后续交由 T03。
- Step3 只接受 `status=0 / base_id!=0` 且 base_id 存在的 relation。
- 输出 ID 必须 canonical normalization，避免 `"622700016.0"` 与 `"622700016"` 分裂。

## 9. 什么是错

- 代表 node 缺失时 fallback 到其它 member node。
- 对非处理 `kind_2` 写业务 `no` 而不是 `NULL`。
- 用 T05 失败 relation 或不存在的 `base_id` 写锚定成功。
- 读取 Segment 或把 Segment 规则放入 T07。
- 在 1:N 冲突下仍发布成功 relation。

## 10. 当前治理缺口

- T07 是当前提高替换率的兜底措施，未来 RCSD 滚动构图方案下需重新评估生命周期。
- Step3 relation 补锚需要持续与 T05 `intersection_match_all` 字段契约同步。
