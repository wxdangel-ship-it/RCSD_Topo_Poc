# 02 数据与领域模型

## 1. 上下游数据关系

T09 消费 T08 Tool7 restriction、T08 Tool8 arrow、SWSD Node/Road、T01 Segment，以及 T06 Step3 的 F-RCSD Road/Node 和 SWSD-FRCSD Segment relation。T09 输出 Movement 级规则和 F-RCSD restriction，供 T10 Case 证据组织和后续通行能力建模。

## 2. 核心业务对象

| 对象 | 业务含义 |
|---|---|
| SWSD Arm | 一个语义路口内某方向的道路承载单元。 |
| Movement | 同一语义路口内 `from_arm -> to_arm` 的候选通行方向。 |
| road-pair carrier | Movement 的 `in_link_id -> out_link_id` 证据粒度。 |
| restriction evidence | 显式禁止通行证据，是唯一能改变禁行结论的强证据。 |
| arrow evidence | 车道箭头现场证据，用于支持、冲突、排除或复核，不单独生成禁行。 |
| special carrier evidence | 提前左转、提前右转、辅路提右等承载位移证据。 |
| restored field rule | Movement 级现场规则恢复结果。 |
| F-RCSD restriction | Step3 投影后的 `LinkID -> outLinkID` 禁止通行关系。 |

## 3. 关键字段语义

- `fully_prohibited` 必须来自 `explicit_restriction`。
- 同一 restriction id 下不同 `in_link_id / out_link_id` 是不同 road-pair 证据。
- `relation_status=retained_swsd` 或 `replaced+retained_swsd` 的 `source=2` relation road 只有属于当前 Arm seed 时才能作为 carrier。
- 未进入 Segment relation 但仍在 F-RCSD Road 中以 `source=2` 保留的 SWSD seed road，可作为 `retained_swsd_seed_fallback`，但必须标记风险。
- Step3 去重键为 `LinkID + outLinkID + junction_id + movement_type`。

## 4. 数据流

1. Step1 读取并归一 SWSD Node/Road、T01 Segment、restriction、arrow。
2. Step1 构建 Arm 和 Movement candidate road-pair universe。
3. Step2 匹配 restriction、arrow 和 special carrier evidence，恢复 Movement 级规则。
4. Step3 读取 T06 relation 与 F-RCSD Road/Node，映射 Arm carrier。
5. Step3 只对 `fully_prohibited + explicit_restriction` 输出 F-RCSD restriction。

## 5. 领域边界

T09 的 restriction 恢复依赖 T06 提供的承载关系，但不修改 T06 输出。T09 不根据 F-RCSD `source` 字段反推交通规则语义，只把 `source` 用作承载来源审计。
