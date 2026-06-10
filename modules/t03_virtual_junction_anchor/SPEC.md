# T03 模块规格：交叉 / T 型虚拟路口锚定

## 1. 模块定位

T03 在 T07 完成已有路口面 1:1 锚定后，面向交叉路口与 T 型路口构建虚拟锚定。模块在冻结合法活动空间内识别 SWSD 语义路口与 RCSD 的有效关联，生成受约束的最终路口面、downstream `nodes.gpkg` 更新和 T05 可消费的 relation evidence。

## 2. 业务目标

- 将 `center_junction` 与 `single_sided_t_mouth` 类型路口转化为可审计的虚拟锚定面。
- 通过 Step1-Step7 把局部上下文、合法空间、RCSD 关联、负向约束、几何生成和最终发布分离。
- 为 T05 提供 T03 surface 与 `t03_swsd_rcsd_relation_evidence.*`。
- 为 T04 提供 downstream `nodes.gpkg` 状态，不把 T03 surface 作为 T04 输入。
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
| Step7 | 压缩为 `accepted / rejected`，发布 surface、nodes 更新、relation 和审计。 |

## 8. 什么是对

- `Step4~Step7` 必须消费冻结的 Step3 allowed space/status/audit。
- `association_class` 是业务关联解释，不是最终视觉等级。
- `B / review` 是保守策略，不等价于算法失败。
- `Step6` 先确定 directional boundary，再在 boundary 内构面。
- `Step7` 只发布 `accepted / rejected`，不新增第三最终态。

## 9. 什么是错

- 为满足 required RC 而突破 Step3/Step6 边界。
- 把道路面外对象纳入当前 case 主结果。
- 把 `V1~V5` review 结果当作机器正式状态。
- 用 cleanup 静默补救几何或拓扑不一致。
- 将 `fail3` 回写为上游输入语义。

## 10. 当前治理缺口

- 质量文档仍为历史编号 `09-quality-requirements.md`，后续需与标准 `10` 编号对齐。
- `INTERFACE_CONTRACT.md` 承载了大量详细步骤，后续可逐步迁移到 `architecture/04` 并保持接口契约精简。
