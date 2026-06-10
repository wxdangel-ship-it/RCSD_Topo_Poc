# T04 模块规格：分歧 / 合流 / 复杂路口虚拟锚定

## 1. 模块定位

T04 在 T03 交叉 / T 型虚拟锚定之后，面向分歧、合流、连续分歧 / 合流和复杂连续链路口构建虚拟锚定面。模块基于 SWSD 候选、道路面、DivStripZone、RCSDRoad 与 RCSDNode，生成受道路面和事实证据约束的 `divmerge_virtual_anchor_surface*`，并向 T05 发布 surface 与 relation evidence。

## 2. 业务目标

- 以 `Step1-7` 作为正式业务范围处理分歧 / 合流 / complex 128 候选。
- 将拓扑骨架、事实事件解释、几何支撑域、polygon assembly 和最终发布分层。
- 在无主证据、弱 RCSD、road-only、SWSD-only 等场景下提供可解释 fallback，不静默构面。
- 输出 accepted / rejected 分层、summary、audit、review 和 downstream `nodes.gpkg`。
- 对 T04 自身 relation 与 T07/T03 relation 做最终 1:1 cardinality 校验。

## 3. 当前范围

### 3.1 正式支持

- `diverge / merge / continuous complex 128` 候选。
- case-package 执行。
- internal full-input 执行。
- `Step1-7` 主链。
- Anchor_2 official 39-case baseline。
- `intersection_match_t04.geojson` 与 nodes 状态回写。

### 3.2 当前非目标

- 不推进 T03/T04 成果统一命名。
- 不把 T04 surface 主产物改名。
- 不把 Step4 `STEP4_REVIEW` 解释为 Step7 第三态。
- 不把 `857993 = rejected` 视为待修成 accepted 的缺陷。
- 不处理 T03 负责的交叉 / T 型路口。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T03 / T07 downstream nodes | 提供前序锚定状态与需排除的已处理关系。 |
| 上游 | T08 / 原始空间数据 | 提供 SWSD Road/Node、DriveZone、DivStripZone、RCSDRoad、RCSDNode。 |
| 下游 | T05 | 消费 accepted T04 surface、T04 relation evidence、nodes 状态和审计。 |
| 支撑 | T03/T04 text bundle | 提供本地 Case 复现和内外网证据包。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| `nodes / roads` | SWSD 语义路口、候选、拓扑骨架和 downstream 状态更新。 |
| `DriveZone` | 道路面合法空间与可通行区域。 |
| `DivStripZone` | 分歧 / 合流主证据和 Reference Point 来源之一。 |
| `RCSDRoad / RCSDNode` | RCSD 语义路口、road-only 对齐、负向掩膜和 fallback 支撑。 |
| T07/T03 relation | 可选最终 1:1 校验输入。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `divmerge_virtual_anchor_surface.gpkg` | T04 accepted 几何真值主成果。 |
| `divmerge_virtual_anchor_surface_rejected.*` | rejected / no-effect 定位与审计。 |
| `divmerge_virtual_anchor_surface_summary.*` | run 级统计。 |
| `divmerge_virtual_anchor_surface_audit.gpkg` | 几何与业务过程审计。 |
| `nodes.gpkg` | downstream 状态索引层。 |
| `nodes_anchor_update_audit.*` | nodes copy-on-write 更新审计。 |
| `intersection_match_t04.geojson` | T04 对 T05 发布的 SWSD-RCSD relation。 |
| `step7_consistency_report.json` | 最终一致性报告。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Step1 | 判断 representative node 是否属于 T04 正式候选范围。 |
| Step2 | 构建高召回 local context，保留 SWSD/RCSD/道路面/导流带上下文。 |
| Step3 | 生成 case coordination skeleton 与 event-unit executable skeleton。 |
| Step4 | 解释事实事件，确定主证据、Reference Point、section reference 与 RCSD/SWSD 对齐。 |
| Step5 | 将事实解释转为 must-cover、allowed-growth、forbidden、terminal-cut 等几何约束。 |
| Step6 | 在 Step5 约束内组装单一连通 case surface。 |
| Step7 | 最终验收、发布 accepted/rejected、回写 nodes 并生成 relation。 |

## 8. 什么是对

- T04 主几何真值是 `divmerge_virtual_anchor_surface.gpkg`，不是 `nodes.gpkg`。
- Step4 内部 `STEP4_REVIEW` 只能作为审计态，不进入 Step7 最终状态机。
- Reference Point 只能来自主证据；无主证据时不得反推虚拟 Reference Point。
- Step5 只定义约束，Step6 才生成最终面。
- Step7 最终状态机只允许 `accepted / rejected`。

## 9. 什么是错

- 用 SWSD/RCSD 抽象点伪造主证据 Reference Point。
- 把 RCSD 数据存在等价为 RCSD 语义路口成立。
- 用 cleanup 静默修正 polygon 违反 allowed/forbidden/terminal cut 的情况。
- 把 `nodes.gpkg` 状态当作 surface 几何真值。
- 把 rejected baseline 样本作为必须修成 accepted 的缺陷。

## 10. 当前治理缺口

- 复杂路口属性修正长期应逐步移交 T08，T04 保持构面和 relation evidence 职责。
- 旧 baseline 与当前 official 39-case baseline 的关系需继续在质量文档中保持清晰。
