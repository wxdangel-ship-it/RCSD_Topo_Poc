# T03 模块规格：交叉 / T 型虚拟路口锚定

## 1. 模块定位

T03 是项目“路口 1:1 关系层”的常规虚拟锚定模块。它在 T07 完成已有路口面 1:1 锚定后，面向交叉路口与 T 型路口构建虚拟锚定，在冻结合法活动空间内识别 SWSD 语义路口与 RCSD 的有效关联，生成受约束的最终路口面、downstream `nodes.gpkg` 更新和 T05 可消费的 relation evidence。

## 2. 业务目标

- 将 `center_junction` 与 `single_sided_t_mouth` 类型路口转化为可审计的虚拟锚定面。
- 通过 Step1-Step7 把局部上下文、合法空间、RCSD 关联、负向约束、几何生成和最终发布分离。
- 对 `single_sided_t_mouth` 中目标语义节点贴近 DriveZone 边界的轻微偏移，允许在 incident road 支撑和审计字段齐备时扩大组件触达判定参考；最终面仍必须完全受 DriveZone 约束。
- 为 T05 提供 T03 surface 与 `t03_swsd_rcsd_relation_evidence.*`。
- 为 T04 提供 downstream `nodes.gpkg` 状态，不把 T03 surface 作为 T04 输入。
- 将常规路口的虚拟构面结果压缩为“一个 SWSD 语义路口对应一个 RCSD 关系基点”的下游候选，交由 T05 统一做 relation 发布和基数质检。
- 保持 `Association / Finalization` 仅作为历史实现和兼容命名。

## 3. 当前范围

### 3.1 正式支持

- `center_junction`。
- `single_sided_t_mouth`。
- case-package 执行与 internal full-input 执行。
- `Step1~Step7` 主链。
- `intersection_match_t03.geojson` 与 cardinality 校验。
- T03/T04-ready 单文件文本证据包。

### 3.2 当前非目标

- 不处理分歧、合流、连续复杂路口；这些属于 T04。
- 不处理环岛。
- 不执行概率化排序、置信度学习或自动回捞。
- 不重写 Step3 合法空间冻结规则。
- 不把 review PNG 的 `V1~V5` 当作机器正式状态。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T07 | 提供已有路口面锚定后的 `nodes` 和 relation 上下文。 |
| 上游 | T08 / 原始空间数据 | 提供 SWSD Road/Node、DriveZone、RCSDRoad、RCSDNode 等输入。 |
| 下游 | T04 | 消费 T03 downstream `nodes.gpkg` 状态，不消费 T03 surface 作为输入。 |
| 下游 | T05 | 消费 T03 accepted surface 与 relation evidence。 |
| 支撑 | T03/T04 text bundle | 为本地 Case 分析和内外网问题反哺提供文件证据包。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| `nodes.gpkg` | SWSD 语义路口、代表 node 和状态更新来源。 |
| `roads.gpkg` | SWSD 局部道路与方向上下文。 |
| `DriveZone.gpkg` | 合法活动空间和道路面约束。 |
| `RCSDRoad.gpkg` | RCSD 关联语义识别与 road 支撑。 |
| `RCSDNode.gpkg` | RCSD 语义路口候选与 relation base 来源。 |
| `intersection_match_all.geojson` | 可选外部 relation 校验输入。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `virtual_intersection_polygons.gpkg` | T03 accepted 虚拟路口面主成果。 |
| `nodes.gpkg` | downstream 状态更新，代表 node 写 `yes / fail3 / no`。 |
| `nodes_anchor_update_audit.*` | nodes copy-on-write 更新审计。 |
| `t03_swsd_rcsd_relation_evidence.*` | T05 Phase2 relation evidence 输入。 |
| `intersection_match_t03.geojson` | T03 自身发布的 relation。 |
| `intersection_match_t03_cardinality_errors.*` | 1:N / N:1 relation 冲突审计。 |
| case 级 `step3/association/step6/step7` 工件 | 单 case 可追溯执行证据。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Step1 | 建立当前 case 的代表 node、局部 roads、DriveZone、RCSDRoad、RCSDNode 上下文。 |
| Step2 | 将 case 限定到 `center_junction / single_sided_t_mouth` 正式模板。 |
| Step3 | 冻结合法活动空间，后续步骤不得反向篡改。 |
| Step4 | 识别 RCSD 关联语义，区分 `A / B / C` 与 required/support/excluded。 |
| Step5 | 建立 foreign / excluded 负向约束，形成 hard negative mask。 |
| Step6 | 在合法空间、方向边界、local required RC 与 hard negative mask 内生成受约束几何。 |
| Step7 | 压缩为 `accepted / rejected`，发布 surface、nodes 更新、relation evidence 和审计；surface accepted 不等于 SWSD-RCSD relation 成功。 |

## 8. 核心场景概念：A / B / C

`A / B / C` 是 T03 对“当前 SWSD 语义路口与 RCSD 证据关系”的业务分类，发生在 Step4。它回答的是：当前 RCSD 证据能以什么角色支撑这个 SWSD 路口，而不是最终视觉效果好不好。

| 分类 | 业务含义 | 下游影响 |
|---|---|---|
| `A` | 主关联成立。当前 SWSD 路口能找到可解释的 RCSD 语义核心，具备形成 SWSD-RCSD 语义路口 relation 的基础。 | 可进入 Step6 几何生成；若 Step7 accepted 且 required RCSD 语义路口证据成立，可作为 T05 成功 relation 候选。 |
| `B` | 支持性关联成立。当前 case 有 RCSDRoad / hook zone / road-only 等支撑证据，但不足以证明完整 RCSD 语义路口核心。 | 可辅助 Step6 构面或 seam bridge；不应直接写成成功语义路口 relation，通常进入 review / `rcsd_present_not_junction` 口径。 |
| `C` | 关联不成立或不应消费。当前 RCSD 对象不属于这个 SWSD 路口，或只能作为 foreign / excluded / audit-only 证据。 | 不应作为当前路口的 required/support 证据；即便 surface 可被 Step7 accepted，也只能作为无 RCSD relation 的虚拟面审计结果，不得写成成功语义路口 relation。 |

`association_class` 不等于 `Step7` 最终状态。`A` 仍可能因几何或边界失败而 rejected；`B` 不是算法失败，而是“有支撑但不是完整语义 relation”的保守业务分类；`C` 也不是视觉等级，而是关联事实不成立。

T03 的状态字段必须分工解释：

| 字段 | 回答的业务问题 |
|---|---|
| `association_class` | RCSD 证据对当前 SWSD 路口是什么角色：主关联、支持性关联，还是不应消费。 |
| `association_state` | Step4 关联判断是否已稳定、是否需要 review 或是否被前置条件阻断；它不等于 relation 成功。 |
| `step7_state` | 当前虚拟路口面是否满足冻结约束并可作为 T03 surface 发布。 |
| `relation_state / status_suggested` | 下游是否可以把该 case 当作 SWSD-RCSD 语义路口 relation 使用。 |

因此，`association_class = C` 且 `association_state = established` 的业务含义是“已稳定判定没有可消费 RCSD 语义 relation”，不是“relation 成功”。T03 允许这种 case 在几何满足约束时发布 surface，但 relation evidence 只能表达 `no_related_rcsd / status_suggested = 1`。

## 9. 什么是对

- `Step4~Step7` 必须消费冻结的 Step3 allowed space/status/audit。
- `single_sided_t_mouth` 的 DriveZone 边界微偏移只影响 Step3 组件触达参考，不允许把 `allowed_space` 推出 DriveZone；触发时必须输出 `target_edge_touch_*` 审计字段。
- `association_class` 是业务关联解释，不是最终视觉等级。
- `B / review` 是保守策略，不等价于算法失败。
- surface accepted 与 relation 成功必须分开判断；只有 `association_class = A`、`Step7 accepted` 且存在 required RCSD 语义路口证据时，才能成为成功 relation 候选。
- `Step6` 先确定 directional boundary，再在 boundary 内构面。
- `Step7` 只发布 `accepted / rejected`，不新增第三最终态。

## 10. 什么是错

- 为满足 required RC 而突破 Step3/Step6 边界。
- 把道路面外对象纳入当前 case 主结果。
- 把 `V1~V5` review 结果当作机器正式状态。
- 把 `association_state = established` 直接理解为 SWSD-RCSD relation 成功。
- 用 cleanup 静默补救几何或拓扑不一致。
- 将 `fail3` 回写为上游输入语义。

## 11. 当前治理缺口

- `INTERFACE_CONTRACT.md` 已瘦身为输入、输出、状态、入口和最小审计字段契约；后续应避免重新承载业务策略说明。
- 历史命名映射和实现构件映射已收敛到 `architecture/03-solution-strategy.md` 的最小说明；后续模块级文档应避免再新增更深层 internal 主文档目录。
