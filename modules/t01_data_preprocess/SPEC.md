# T01 模块规格：SWSD Segment 构建

## 1. 模块定位

T01 消费 T08 预处理后的 SWSD `nodes / roads`，构建 SWSD Segment。双向 Segment 是当前主流程基础；单向 Segment continuation 已进入正式范围，用于补齐双向流程无法覆盖的单向、封闭式 / 高速相关 road。T01 输出供 T06 构建 RCSDSegment 与执行替换，也为 T09 路口通行规则恢复提供 SWSD Segment 承载。

## 2. 业务目标

- 在非封闭式双向道路场景下构建可审计的双向 Segment。
- 在路口面 / 多分支语义节点内保持 Segment corridor 可解释，避免把明显转向关系构造成同一个双向 trunk。
- 在 Step5C refreshed 结果之后执行单向补段，补齐仍未构段的单向 road、受控 dead-end、residual corridor fallback 与 single-road fallback。
- 在 Step6 聚合前执行 Segment 形态控制，避免最终双向 Segment 跨越明显转向；两条 road 构成的短双向 Segment 不应跨越道路等级不一致的内部语义交叉路口。
- 通过 Step6 聚合 `segment.gpkg`，反查 `sgrade`、中间路口、冲突和未构段 road。
- 保持 `grade_2 / kind_2` 作为后续业务判断字段，不用原始 `grade / kind` 直接进入强规则。
- 维护 active freeze baseline，避免双向 accepted baseline 被单向补段误覆盖。

## 3. 当前范围

### 3.1 正式支持

- `nodes.gpkg / roads.gpkg` 输入。
- Step1-Step5C 双向 Segment 构建。
- Step5 后单向补段 continuation。
- dead-end leaf、residual corridor fallback、final single-road fallback 与 final side-attachment merge。
- Step6 前 Segment 形态控制。
- Step6 Segment 聚合与冲突反查。
- freeze compare 与文本证据包 helper。

### 3.2 当前非目标

- 不直接生产 RCSD Segment。
- 不修改 T05 / T06 / T09 下游产物。
- 不把单向补段规则回写为双向 Step1-Step5C 的规则。
- 不根据缺失 `kind` 字段的几何形态反推道路等级。
- 不未经用户确认更新 active freeze baseline。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T08 / SWSD `nodes / roads` | 提供 `grade_2 / kind_2`、Road 类型与方向基础。 |
| 下游 | T06 | 消费 `segment.gpkg`、`pair_nodes / junc_nodes / roads / sgrade` 构建 RCSDSegment 与 replaceable。 |
| 下游 | T09 | 使用 Segment 作为 SWSD Arm 与 F-RCSD restriction 投影的承载关系之一。 |
| 支撑 | freeze baseline / evidence bundle | 用于回归保护和内外网审计取证。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| `nodes.gpkg` | SWSD 节点、语义路口、`grade_2 / kind_2` 与 `closed_con` 判定来源。 |
| `roads.gpkg` | SWSD Road 拓扑、方向、`formway / road_kind / kind` 与 Segment road body 来源。 |
| previous Step5 输出 | continuation 模式下只消费已完成双向流程的 refreshed `nodes / roads`。 |
| freeze baseline | 作为双向 accepted baseline 的非回退检查依据。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `nodes.gpkg / roads.gpkg` | 刷新后的 working layer，记录构段后的语义字段和 road 标记。 |
| `segment.gpkg` | 正式 SWSD Segment 聚合成果，供 T06/T09 消费。 |
| `inner_nodes.gpkg` | Segment 内部语义节点审计。 |
| `segment_error*.gpkg` | `sgrade`、`grade/kind` 冲突审计。 |
| `validated_pairs_skill_v1.csv` | 双向候选 pair 的正式 validated 结果。 |
| `segment_body_membership_skill_v1.csv` | pair-specific road body 审计。 |
| `trunk_membership_skill_v1.csv` | trunk 路径审计。 |
| `oneway_segment_*` | 单向补段成果和统计。 |
| `unsegmented_roads.*` | 全阶段完成后仍未构段 road 的审计。 |
| `skill_v1_summary.json` | 全流程 summary、计数、诊断和性能信息。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Working 初始化 | 复制输入 Nodes/Roads，初始化 `grade_2 / kind_2 / segmentid / sgrade`。 |
| 环岛与 bootstrap 预处理 | 识别环岛语义路口，执行极窄 strict-T 纠错，形成 Step1 前的 working 事实。 |
| Step1 | 在当前轮规则下搜索 pair candidates，只产出候选，不代表最终有效 Segment。 |
| Step2 | 对候选 pair 做 validation、trunk、转向角 gate、segment body 与 rejected 判定，输出 pair-specific road body。 |
| Step3 | 基于 Step2 结果刷新 Nodes/Roads 当前语义。 |
| Step4 / Step5A / Step5B / Step5C | 在 residual graph 上逐轮扩展双向 Segment，每轮后立即 refresh。 |
| 单向补段 | 在 Step5C refreshed 结果上补齐单向 road、dead-end leaf、residual corridor fallback、single-road fallback 与 side-attachment merge。 |
| Segment 形态控制 | 在 Step6 前检查最终双向 Segment 的内部语义交叉路口，按转角证据拆分长链路贯穿；仅对两条 road 构成的短双向段按道路等级证据拆分。 |
| Step6 | 聚合 Segment，输出最终 `segment.gpkg` 和冲突 / 内部节点审计。 |

## 8. 什么是对

- 双向 Step1-Step5C 与单向 continuation 的规则边界清楚，单向补段不污染双向 baseline。
- Segment 的 `pair_nodes / junc_nodes / roads / sgrade` 可解释、可追溯。
- Segment trunk 不应在多路口面内部跨越明显非直行转向关系；被拒绝候选必须保留角度、节点和 road 审计。
- 最终双向 Segment 不应在真实多路口内贯穿明显转向；两条 road 构成的短双向段不应跨道路等级变化。若 Step2-Step5C 未拦截，Step6 前形态控制必须拆分并保留 `pre_shape_control_*` 审计。
- `kind_2 = 64` 环岛、`kind_2 = 128` 复杂分歧 / 合流、`kind_2 = 2048` T 型路口的业务处理与审计明确。
- `formway = 128` 右转专用道不进入 Step1-Step5 构段图。
- 未构段 road 被显式输出到 `unsegmented_roads.*`，而不是静默丢弃。

## 9. 什么是错

- 用原始 `grade / kind` 直接替代 `grade_2 / kind_2` 做后续强规则。
- 根据缺失或不可解析的 `kind` 几何反推道路等级。
- 把 Step1 pair candidate 当作已成立 Segment。
- 把单向补段结果用于更新双向 freeze baseline。
- 隐式放宽右转专用道、封闭式道路或历史高等级边界规则。
- 在未确认前更新 active freeze baseline。

## 10. 当前治理缺口

- `README.md` 已收敛为阅读入口后，历史长运行说明需要继续依赖 `INTERFACE_CONTRACT.md` 与 accepted baseline。
- `architecture/03-solution-strategy.md` 需要持续保持架构设计职责，避免再次退化为阶段名清单。
- active freeze baseline 的更新仍需独立用户授权。
- `architecture/accepted-baseline.md` 是 baseline 业务口径补充材料，不再占用模块架构 01-06 主编号。
