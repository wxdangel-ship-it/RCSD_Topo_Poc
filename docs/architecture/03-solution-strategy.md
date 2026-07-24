# 03 方案策略

## 文档定位

本文档只描述跨模块主方案和项目级技术取舍，不展开模块内部 Step、参数、阈值和验收规则。

## 主链策略

| 环节 | 项目级职责 |
|---|---|
| T08 | 统一 SWSD / RCSD 输入预处理、格式转换、Road / Node 清理、SWSD 质量修复和 Laneinfo / restriction 显性化。 |
| T01 | 基于 SWSD 构建双向与单向 Segment，作为 T06 替换和 T09 通行建模基础。 |
| T07 | 基于现有路口面建立 SWSD-RCSD 1:1 锚定，并保留显式兼容 relation 补锚能力。 |
| T03 | 构建交叉路口、T 型路口等常规路口虚拟锚定，补齐后续语义关系融合所需证据。 |
| T04 | 构建分歧、合流、复杂路口虚拟锚定，并提供 SWSD / RCSD 数据级锚定兜底。 |
| T05 | 汇总 T07 / T03 / T04 关系，形成统一 SWSD-RCSD 语义路口关系和 RCSD junctionization 成果。 |
| T06 | 以 T01 Segment 和 T05 语义关系为依据构建 RCSDSegment，并生成 F-RCSD 承载关系。 |
| T09 | 基于 SWSD Laneinfo / restriction 与 F-RCSD 承载关系还原路口级通行规则。 |
| T10 | 组织端到端编排与 Case 证据包；v1 Case runner 编排 T01 / T07 Step1/2 / T03 / T04 / T05 / T06 / T11 / T09，T11 为 audit-only，T08 独立前置运行；内网全量总控可把 T08 作为独立阶段串入。 |
| T12 | 对原始 1V1 F-RCSD 执行 audit-only 质量检查，验证 SWSD 通行性等价假设，以 raw endpoint topology 为主、portal-constrained semantic carrier 与 T07 Road-surface portal carrier 为误报排除门禁；Road-surface 层要求唯一标准面和有向物理 Road，距离仅作审计。结合锚点可信度自动发布确认与排除层，人工复核仅作可选 QA 覆盖，不执行修复。 |

## 业务分层策略

当前方案按四个业务层推进。

### 输入与 Segment 基础层

T08 先把原始 SWSD / RCSD 数据中不稳定的格式、字段、类型、restriction、Laneinfo 和 RCSD 拓扑问题显性化。T01 再把 SWSD Road/Node 组织成 Segment，使后续模块能以“两个语义路口之间的道路连续单元”作为替换对象，而不是直接处理零散 Road。

### 路口 1:1 relation 层

T07、T03、T04、T05 都服务于 SWSD-RCSD 语义路口关系构建，但它们覆盖的业务场景不同：

- T07 处理已经存在道路面或 RCSDIntersection 证据的路口，并在显式提供兼容 relation 文件时补齐部分未锚定候选；该能力不是 T05 之后的默认回灌阶段。
- T03 处理交叉路口和 T 型路口，在合法道路面空间、RCSD 关联和负向约束下构建虚拟锚定面。
- T04 处理分歧、合流、连续分歧 / 合流和复杂路口，用事实事件解释和几何支撑域生成虚拟锚定面。
- T05 将 T07/T03/T04 的证据统一融合，处理 road-only split、RCSDNode grouping、环岛和复杂路口归组，并发布 `intersection_match_all`。

这一层的目标不是让每个模块各自输出一份局部成功关系，而是让下游 T06 能消费统一、唯一、可审计的 SWSD-RCSD relation。

### Segment 替换层

T06 的原始目标是基于 T01 Segment 与 T05 1:1 relation 执行 SWSD Segment 到 RCSD Segment 的替换。真实数据运行后，T06 需要承担更多质量承接工作：

- RCSD 的道路切分可能与 SWSD Segment 不一致，单个 SWSD Segment 可能对应多条 RCSDRoad 或跨越短连接。
- RCSDNode 的 `mainnodeid / subnodeid` 归组、端点节点和 Road 方向可能与 SWSD 语义路口侧位不完全一致。
- 部分 pair anchor 可能缺失、错锚或两端坍缩到同一个 RCSD 语义路口。
- 提前右转、内部调头口、road-only split 和 detached junc 会导致“主通道可替换，但局部通行 carrier 仍需保留”。
- T03/T04/T05/T07 surface 可以提供节点闭合证据，但不能绕过 T04 reject、Patch 冲突或多候选冲突。

因此 T06 采用“先证明可替换，再执行替换”的策略：Step2 通过 buffer corridor、方向、连通、覆盖、特殊组门控和 problem registry 发布 replacement plan；Step3 只执行 plan，并用 source 边界、提前右转后处理、surface topology closure 和 topology connectivity audit 保护最终 F-RCSD。

### 通行恢复与验证层

T09 基于 T06 的 F-RCSD carrier 恢复 restriction。T10 默认在 T06 后先运行 T11 形成 relation repair candidate audit，再进入 T09；显式提供原始 1V1 F-RCSD 时，在 T11 后、T09 前运行 T12。T12 与 T11 都不改变 carrier。F-RCSD 质量检查专用入口固定跳过 T08、启用 T12，并复用同一 full runner。T10 通过 Case replay、T06 funnel、可选 T12 quality audit、T11 candidate audit、visual check、feedback package 和 full pipeline summary 把真实数据问题组织成可追溯证据链。P01 作为 POC，在 Arm / RoadNextRoad 层探索更完整的通行能力建模，但不替代 T09。P02 作为武汉局部实验 POC，在缺少道路面、导流带和 RCSDIntersection 时，以 T11 格式人工关系进入 T05，再由 T06 验证 Segment 替换；P02 不替代被编排模块。P04 作为并行 POC，以 T01 Segment 为顶层业务单元，复用 T07/T03/T04/T08 accepted surface 建立 JunctionUnit，并以 Patch Vector、Patch Road 和 LaneTopo 实例化 Road/Node/RoadNextRoad；P04 当前不进入 T10 正式编排。

## 生命周期影响

- T00 保留为支撑工具集合，历史一次性预处理能力主要由 T08 吸收。
- T02 已 Retired，历史能力分别由 T07、T03、T04、T08 承接，历史入口和脚本仅作为可追溯资产存在。
- P01 是异构路口通行能力 POC / 成果模块，不替代 T09 正式契约。
- P02 是武汉局部人工锚定实验 POC / 成果模块，不进入正式主链，也不伪造 T07/T03/T04 产物。
- P04 是 Segment-first Road 直出 POC / 成果模块，不进入正式主链，不把当前 Road/LaneGroup、历史 V2/V3 或单 Case 候选提升为正式 RCSD。

## 设计取舍

- 项目级只维护跨模块共用语义、链路和质量约束；模块细节下沉到模块契约。
- 虚拟锚定与数据级锚定并存：前者支撑可解释关系建模，后者作为替换率和召回的兜底。
- T06 之后的 F-RCSD 是 T09 还原规则的承载基础，但 RCSD Laneinfo 和轨迹通行证据仍是后续迭代缺口。
- T07 的兼容 relation 补锚属于当前阶段可选兜底策略；未来 RCSD 滚动构图方案成熟后可退出或降为历史兼容能力。
- T10 以文件级 handoff contract validation 为基础，已经接入空间切片 Case 包、Case 级 replay、T06 上游反馈包和内网全量总控；后续重点是稳定真实数据反馈迭代、全量审计口径和跨模块 handoff 质量。
- P04 选择“Segment 先完整、JunctionUnit 定边界、Vector 实例化 Road、LaneTopo 验证物理连通”的约束构图路线。T01 Segment 是顶层 owner；T07 accepted surface 优先于冲突的 T03，T04 负责分歧/合流与短距离连续分合流复杂路口，环岛 Junction 复用 T08/T01。核心使用可解释规则和图不变量，学习模型只允许在有充分标注后参与候选排序。
- P04 按单 Segment 原子构建与回退。每个正式 Segment 至少发布一条独立 Road；可区分上下行时必须形成两条从一端JunctionAccess连续到另一端JunctionAccess的方向主干链，而不是固定两条Road记录。方向链可按LaneGroup、物理Node、`junc_nodes`、分流合流和证据边界细分；非高速主辅路等按T01可包含额外方向链和附属Road。部分证据支持只允许新建 Road 内的 `hp_observed + hp_constrained_completion`，不得直接拼接 SWSD 坐标；无证据可整体保留 SWSD carrier。单 Segment hard gate 失败只阻断该 Segment 及相关 Movement，不扩大为 Junction 关联 Segment 组回退；跨Segment被拒Movement显式排除，不自动回退两侧Segment。
- P04 对“SWSD参考轴长、实际两个Junction边界间走廊短”的场景，以 `accepted surface + junction_endpoint_buffer` 判定真实Segment端点。已通过占用冲突、DriveZone和最小观测比例门禁的Patch access-surface候选，可在两个互不接触的端点保护区之间形成surface-to-surface主干并原子推导缺失方向；不得把该规则用于重叠保护区、同一Junction内部短线或任意raw component直拉。
- P04 对已选走廊执行“直线补齐优先、局部道路域路径兜底”：路径只在端点与目标accepted surface的局部范围搜索，必须受合法域覆盖和绕行比例限制，并为后续平滑预留边界余量；SWSD只提供端点归属和方向语义，不提供路径坐标。新路径引出的LaneTopo切分不得把端点面之外的尾段继续冒充Segment主干，也不得顺带改写无直接因果的其它Segment。
- P04 发布状态使用 `hp_full / hp_partial / swsd_retained / conflict_retained`，并与 `segment_publishable`、`carrier_takeover_ready`、`replacement_scope`、人工 review 和输入质量状态分离。软质量问题可带 review 发布，hard gate 不得被 review 绕过。
- P04 的 Node/mainnode 与连通按SWSD两级路口模型编译：普通十字/T型保留分布式高精portal Node，同一正确分类的ordinary JunctionUnit共享mainnodeid，不生成中心聚合点或星形内部Road；RoadNextRoad按同一ordinary JunctionUnit内方向兼容的进入—离开Road组合表达默认PhysicalMovement，并保留source/target物理Node lineage。Segment内部连续性、T04复杂路口、环岛和聚合异常仍要求实际共享Node或显式LaneTopo/RCSD物理关系，禁止仅凭mainnode值机械全连接。
- P04 必须把原始SWSD解释为完整拓扑合同：逐Segment复核Access进入/离开方向，逐ordinary Junction复核全部方向兼容Movement；Road可按稳定LaneGroup交接细分且无需与SWSD Road一一对应，但不得丢失该完整拓扑。T04 complex只接受明确物理关系；SWSD弱fallback还必须同时具备原始shared Node、member lineage匹配和accepted surface内portal。
- P04 的候选仲裁按固定优先级执行：完整 Segment 方向走廊优先，baseline/access 恢复次之，只有前两者都无法形成必要方向链时，才允许单 SWSD member 使用一方向观测与 RoadSurface 推导另一方向。fallback 后释放未发布 Segment 的证据占用并迭代到固定点；不能释放仍与有效 built carrier 冲突的证据。唯一 SWSD member 方向路径可在该固定点后驱动 Road 角色，歧义路径只进入审计。
- P04 闭域验收把“原始目标是否属于Baseline”“当前是否必须DirectBuild”“最终如何完整发布”分成三层：Baseline由输入确定并冻结；DirectBuild资格默认必建，只能通过外部确认且带hash/证据的清单逐对象标记`patch_data_insufficient`或`reality_change`；发布处置仍覆盖全量Segment。质量报告必须并列展示Baseline实现率、DirectBuild实现率和完整发布率，不允许用缩小后的硬分母遮蔽原始Baseline。
- P04 最大化复用 T00-T12 正式产物、公开契约和兼容通用能力，但不修改 T01-T12；无法无损兼容时建立 P04 内部版本化实现/适配层，并保持现有主链输入输出不变。
- Directional Road V2 与 High-Precision V3 保留为历史回归基线。当前 Segment-first 终态必须由独立发布后 QA 硬门禁，并提供原始 SWSD、原始 RCSD、新生成 Road、原始 Lane 与 Road-Lane 关系的 QGIS 对比；生产器自检、目视相似或旧候选统计均不能单独宣布通过。

## T06 替换率提升策略

T06 的替换率提升不是简单放宽阈值，而是在不破坏安全边界的前提下扩大可解释替换范围：

1. 对 relation 缺失或疑似错锚的 Segment，先输出 buffer-only probe 和 repair candidates；只有候选唯一、高置信、方向和几何审计通过时，才允许当前 Segment 内 effective relation 重试。
2. 对高等级 Segment 的裁剪窗口不足，允许 graph-first 或 adaptive buffer 受限重审；重审通过仍必须满足 50m core、方向、叶子端点、额外 mapped semantic node 和特殊组门控。
3. 对环岛和复杂路口，要求关联 Segment 组完整可替换；若单段成功但组不完整，不允许局部替换破坏路口内部承载。
4. 对跨外部 accepted anchor 的 path corridor，只有闭包内 carrier 通过正式 group probe 并由 replacement plan 发布时，Step3 才能成组替换。
5. 对 detached junc、提前右转和保留 SWSD carrier，Step3 用 `replaced+retained_swsd`、`frcsd_road_source_values / source_mix` 与风险标记表达“主通道替换 + 局部 carrier 保留”；`frcsd_road_ids` 表达最终可消费 carrier，正式 RCSD 来源审计仍必须排除 `source=2` 保留 SWSD carrier。
6. 对 surface-assisted node closure，T06 只在唯一候选、T04 未 reject、Patch 无冲突和距离门槛可解释时补写节点映射或 `mainnodeid`；它不新增正式替换道路，不修改原始道路几何。
7. 对 retained-junction 20m 距离 gate，T06 只允许在 surface 1:1 pass 或原始 pair endpoint 映射可解释时降级为风险释放；释放后必须重跑 Step3 topology audit，新增 hard fail 对应的 plan 必须回退，相对 baseline 的新增 fail 必须显式记录。

## 改进路线

- Relation 质量产品化：T07/T03/T04/T05 需要继续减少“成功但不可图消费”的 relation，并把 blocked / review-only / fallback 状态稳定输出给 T06。
- Feedback 闭环：T10 feedback iteration 应优先消费 T06 problem registry 中明确可自动转给 T05 的 endpoint candidate；其它问题形成上游模块任务，不进入 Step3 白名单。
- F-RCSD QA：T06 Step3 结果继续由 T06 正式审计；外部 1V1 匹配生成的 F-RCSD 由 T12 检查 SWSD 等价可达性、road-node integrity、canonical 候选图、raw verdict 图、portal-constrained semantic carrier、T07 Road-surface portal 和自动高置信发布；人工复核仅作可选 QA 覆盖。
- 通行能力增强：T09 当前以 SWSD restriction / Laneinfo 为主，后续应引入 RCSD Laneinfo 和轨迹证据；P01 的 Arm / RoadNextRoad 经验可作为正式化前的参考材料。
