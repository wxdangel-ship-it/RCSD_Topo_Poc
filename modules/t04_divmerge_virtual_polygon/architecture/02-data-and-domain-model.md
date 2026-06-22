# 02 数据与领域模型

## 1. 上下游数据关系

T04 消费 SWSD Road/Node、DriveZone、DivStripZone、RCSDRoad、RCSDNode，以及 T03/T07 downstream 状态。T04 输出 accepted surface、rejected 审计、nodes copy-on-write 状态、T04 relation evidence 和 `intersection_match_t04.geojson`，供 T05 Phase 1 / Phase 2 继续融合和发布。

## 2. 核心业务对象

| 对象 | 业务含义 |
|---|---|
| representative node | 当前 T04 case 的 SWSD 代表语义节点。 |
| event unit | 一个复杂路口 case 内可执行事实解释的局部单元。 |
| main evidence | 真实物理空间证据，只能来自导流带或道路面分叉。 |
| Reference Point | 主证据决定分歧 / 合流位置的事实点；无主证据时为空。 |
| section reference | 用于确定截面位置的参考对象，可来自主证据、RCSD/SWSD 语义对象或 fallback。 |
| support domain | Step5 形成的 must-cover、allowed-growth、forbidden 与 terminal-cut 约束集合。 |
| accepted surface | Step6/Step7 发布的 T04 主几何真值。 |
| relation evidence | 面向 T05 的 SWSD target 与 RCSD base 候选关系证据。 |

## 3. 关键字段语义

- `kind_2 in {8,16,128}` 是 full-input 正式候选发现的主要入口；legacy `kind` 只能兼容 case-package 或审计，不得替代 `kind_2`。
- `final_state = accepted` 是 T04 surface 被 T05 消费的正式成功状态；`STEP4_REVIEW` 只是 Step4 内部审计态。
- `surface_scenario_type` 表达主证据、RCSD 对齐和 SWSD 可用性的业务场景。
- `rcsd_alignment_type` 表达 RCSD 对齐类型，至少区分完整 RCSD 语义路口、partial junction、road-only、无 RCSD 和 ambiguous RCSD。
- `base_id_candidate` 是 T05 relation handoff 候选；partial handoff 中可使用局部 `local_rcsd_unit_id`，原语义主点保留到 `semantic_required_rcsd_node_ids` 审计链。

## 4. 数据流

1. Step1 只做候选准入。
2. Step2 构建高召回 local context。
3. Step3 生成 case coordination skeleton 和 event-unit executable skeleton。
4. Step4 解释事实事件并唯一发布场景、RCSD 对齐和参考对象。
5. Step5 将事实解释转为几何支撑域。
6. Step6 在支撑域内组装单一连通 case surface。
7. Step7 发布 accepted/rejected、回写 nodes、输出 relation 和一致性审计。

## 5. 领域边界

T04 的 relation evidence 是 T05 的上游证据，不是项目级最终关系主表。T04 可以给出局部 RCSD 基点和失败审计，但最终 SWSD-RCSD 关系收口、cardinality 审计和 RCSD junctionization 属于 T05。
