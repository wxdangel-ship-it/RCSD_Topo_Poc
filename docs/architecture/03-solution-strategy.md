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
| T12 | 对原始 1V1 F-RCSD 执行 audit-only 质量检查，验证 SWSD 方向通行性等价假设，覆盖必需方向缺失与非预期反向载体。1V1/T05 mainNode 锚定只展开选中 `base_id` canonical raw alias group，其它显式 grouped raw node 不递归扩组；按当前方向 source outgoing / target incoming 进入 raw identity endpoint topology，锚定 alias 距离仅审计，非锚定 spatial fallback 不放宽。以 portal-constrained semantic carrier、T07 Road-surface portal carrier 和 SWSD 反向替代路径为误报排除门禁；Road-surface 层要求唯一标准面和有向物理 Road，非预期反向载体仅在双端唯一 T07 标准面且无 SWSD 等价反向路径时自动确认。人工复核仅作可选 QA 覆盖，不执行修复。 |
| P05 | 在正式链外采用方案 A：冻结 T01 Junction—Segment/PhysicalMovement 骨架，模型只为 Road/Node carrier 评分/选择并报告异常；冲突进入最小闭包 fallback。全部旧 M1/M2R/R2/PTO/JSG-PTO 结论作为历史证据。 |

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

P05 与规则主链并行，当前只执行方案 A。T01 Segment 集合、Junction relation 与 PhysicalMovement 存在性先冻结，神经模型只学习 carrier 候选评分、Road/Node carrier 选择和异常概率；确定性层仅验证骨架 signature、schema、引用、方向、CRS、lineage 和最小 fallback 闭包。`ADVANCE_RIGHT` 是 Segment，不是 Connector。证据冲突形成 `RealityChangeClue`，不得通过 PTO-A、补路、吸附或重连改变骨架。

Scheme-A-P2-P0 已完成且未训练模型。它把 P1 中绑在每个 Segment 上的共享 Node carrier 分离为 JunctionUnit 统一选择：candidate 阶段只枚举当时受限的 T01/proposal Road/Node，Oracle 阶段才读取 label-only truth；Movement 不参与候选、求解或评价。其 `USE_RCSD retention=0.165753` 现在只保留为该受限 carrier bundle 的联合安全保留指标，不再外推为训练 Case 或正确 RCSD carrier 缺失。

Dataset-P0 随后按正式模块职责重新审计全部数据与候选：T01 仅为 SWSD 骨架/fallback，T07 固定 `DRIVEZONE_ONLY`，T03/T04/T05 为中间监督，T06 为最终标签。正式双跑证明 2,190/2,190 `USE_RCSD` Road 由非 T01 truth-free candidate 可达，23,224 final Road、27,553 final Node 和 8,823 个可用 Segment 联合 exact 均为 `1.0`。因此下一阶段可以基于冻结高召回候选设计 scorer，但模型泛化、异常 calibration 与轻量在线 proposal 性能仍须独立验收。

P2-P1 已按该方案完成并判定 `P05_SCHEME_A_P2_P1_SAFETY_NO_GO`。Road来源条件化将Node exact从独立评分约`0.7558`提升到`0.9965~0.9985`，通用compatibility gate使三个seed均保持49+2；这证明“先选Road、再条件化Node carrier”的分层正确。NO-GO来自安全接受而非候选缺失：仍有高置信Segment错误及其Node连带错误，anomaly head和Review少数类也不稳定，无法同时实现零错误与50%覆盖。后续只能作为新的class-aware calibration/abstention阶段另行授权，不得在本次held-out分母上调阈值后重报GO。

P2-P2-P0 已完成只读错误链和可分性审计。原 `17/9/17` 是 selected-candidate 对象级指标，真正 accepted Segment 根错误为 `2/0/3`，Node 错误多数是条件化传播或 fallback 前后口径；因此安全判定应放在 Segment 根 carrier 进入 Node 条件化之前。8 个稳定 false-use 对单一 probability/margin/entropy/anomaly 阈值的最佳零错误 `USE_RCSD` 覆盖仅 `0.200275`，故 calibration-only NO-GO；完整现有 truth-free feature 无跨 truth 精确碰撞，下一阶段技术方向是冻结基础 scorer、另建 Case-grouped/cross-fitted safety head，而不是继续调同一阈值或增加 epoch。

P2-P2-P1 已实际验证上述方向，但当前 safety head 正式 `MODEL_NO_GO`。模型冻结基础 scorer/candidate，只以三 seed OOF 统计和既有 truth-free Segment feature 做 accept/abstain；零错误 seed 只能保留约 7% 总体/USE，另两 seed 在约 30%~37% 总体覆盖时仍接受 4~5 个错误。Node 条件化、共享冲突 fallback 和 49+2 RoadGraph 均通过，说明瓶颈仍是跨 Case 的 Segment 安全泛化，不是图闭包。后续不得在已见 held-out 上继续调同一阈值或只增加 epoch；若继续，应新增 truth-free 局部业务证据或验证预训练表征，并作为新阶段重新验收。

P2-P2-P2-P0 随后把允许推理期使用的 T01/T07、proposal/KEEP 有向结构差、compatibility/Junction共享压力和 base OOF 统计冻结为 202 维证据，以 203 参数线性和 15,105 参数浅层 MLP 做预登记 probe。线性仍自动放过 2 个错误；浅层 MLP 的全局 accepted wrong 为零，但 5 个 held-out fold 无一同时达到 unsafe recall=`1.0`、总体和 `USE_RCSD` coverage 均 `>=0.50`。因此不得继续在当前特征上扩模型或调阈值；下一研究路线必须带来真正新增的推理期信息，或另立预训练表征和新冻结验证集，不能把 T03–T06 label/status/reason 暗中提升为输入。

P2-P2-P2-P1 不再训练，而是逐对象回答“正确判定从哪里来”。62 个目标中，40 个 Review 由已有 T01 access 硬门直接解决；22 个风险对象的直接原因只存在于 T06/联合真值层，P2-P1 truth-free joint fallback 虽有相关性但 unsafe precision 仅 `0.2083~0.2981`，不能成为业务硬门。因此当前技术路线必须保持这 22 个对象 fallback/Review，或另行证明一个在 T06 之前独立生成的等价事实来源；直接读取 T06 终态只会把 P05 变成 T06 后处理器。

P2-P2-P2-P2 证明了 Pre-T06 分层路线存在，但没有放行现有模型。22 个对象的正确候选全部可达：5 个 carrier Road 缺失对象由候选集合无 `USE_RCSD` 保证 Road 侧安全，异常原因交给独立 clue head；1 个 `MIXED_CARRIER` 候选已存在，由 carrier scorer 选择；16 个对象通过 Segment carrier 评分、通用 Node compatibility 与 Junction 一致性闭包组合。T03/T04 节点证据、T05 relation 和 T06 carrier/clue 只作为辅助监督目标，推理期仍只使用当前允许的 T01/T07、truth-free candidate 和模型输出。现有浅层 MLP 只有 2/5 fold 通过覆盖门，因此下一模型必须另立分层架构和冻结验证，不得把本审计改写为模型 GO。

P2-P3-P0 已按上述分层路线完成：candidate listwise/correctness head 选择 `KEEP_SWSD/USE_RCSD/MIXED_CARRIER`，共享表示同时训练独立 clue head 和 7 个 T03/T04/T05 辅助 head，随后用固定 Node compatibility/Junction consistency decoder 物化 RoadGraph。该 decoder 在三 seed 上均无 conflict/mismatch/repair，证明结构组合问题已解决；MODEL NO-GO 来自 scorer 和 clue 的 cross-case 选择性不稳定。下一轮不得在同一 held-out 51 Case 上调 threshold、挑 seed 或把 T03–T06 label-only 字段偷渡为输入；需要真正的新推理期表征或新冻结验证证据后另行授权。

P2-P3-P1 的只读证据库存结论保留，但其 stable false-use 与 fold 2 coverage-ceiling 是旧标签/级联口径下的历史解释。Dataset-P1 已先修正分母：T10 全 Case为标签，Segment 包只标目标 ID或精确 Road partition 后继，2,588 个非目标 Segment只作上下文；expected-failure Case仍不发布，但只对各自 failure group执行对象级失败/fallback。下一技术顺序因此是先以 Dataset-P1 重建可训练 dataset和全部指标，再决定是否需要新的 T06 前表征；未经新授权不训练，T03/T04/T05/T06 final status/reason 继续保持 label-only。

P2-P3-P2 已完成上述同模型重基线：只用6,275个eligible标签训练/选阈值/评价，2,588个context-only对象固定回退，通用Node/Junction decoder仍处理全部8,863 Segment。标签与级联问题被消除后，整图安全继续通过，但一个可靠target false-use在两个seed重复出现，另一个seed把12个`ADVANCE_RIGHT` Review自动发布；零错误seed又只能保留约15%总体coverage。因此下一技术顺序不再是继续清洗同一标签或增加epoch，而是先把Review/ADVANCE_RIGHT硬安全资格与carrier scorer解耦，再为剩余false-use建设T06前可用的新表征或独立验证合同。

P2-P3-P3已完成第一步解耦：冻结`access_valid=false`只命中40个Review，三seed共120条决策全部硬回退，非Review decision逐字段不变；重放后Review auto为0且49+2整图保持。剩余对象在三个seed中均以大margin选错，60个held-out近邻全部为`USE_RCSD`。后续顺序固定为：先定义并验证T06前新增表征的来源、生成时点、成本、lineage与跨Case可分性，再授权新模型；不继续使用同一表征重训。

历史 R2/PTO/JSG-PTO 路线继续保留：R2 证明输出语言和 small-batch 可学习性，RoadGraph PTO/JSG-PTO 证明历史候选/约束/compiler 的可行性，P3 证明 object-conditioned context 的评分增益。这些结论不再直接决定当前标签或验收门禁；旧 Connector 与 Review/Unknown 数值必须在 carrier-only 合同下重新建立。

PTO 路线把生成拆为 candidate proposal、learned cost 与 constrained selection。P0 已完成前后两端的可达性证明：T03-T06 策略重放只能从 raw/T01 产生 proposal；候选冻结后 Oracle cost 才可读取 truth，并仅用 action domain、唯一 ID、base/endpoint 引用、有限非空几何和生成状态约束选图。51 Case 的候选覆盖与精确求解通过，但 proposal replay P95/max 超预算。P1 先在冻结/缓存候选上训练 object-conditioned scorer；并行把全链 replay 替换为轻量或增量 proposal generator。P0 成功不等于模型成功。

JSG-PTO-P0 路线已完成：T01/T05/T06 与 R2 Oracle 转换为 canonical Junction—Segment—Movement truth，JSG evaluator 验证本体语义，compiler 读取已声明 carrier realization、生成 R2 edit IR 并复用 materializer 输出 Road/Node。JSG-PTO-P1 也已完成：candidate manifest 在 truth 进入前冻结，PTO-A 选择业务结构，PTO-B 选择 Unit carrier/RoadGraph edit，再复用 compiler；双跑 51/51 精确且确定。任何 scorer 推迟到后续独立授权。

JSG-PTO-P3 已完成。candidate/context 双编码与交互网络只读取 ID-free candidate、同组备选、dependency graph 和 T01 相对方向证据，按 outer business-ID grouped 5-fold 与 inner validation 训练，score 通过统一合同进入同一 PTO/compiler。正式 `3 seeds × 5 folds` 的总体 JSG Top-1 已过门槛，但 Connector 与 Review/Unknown 未过门槛，判定 `P3_MODEL_NO_GO`；不得通过修改 PTO 约束或 compiler 掩盖该输入证据缺口。

## 生命周期影响

- T00 保留为支撑工具集合，历史一次性预处理能力主要由 T08 吸收。
- T02 已 Retired，历史能力分别由 T07、T03、T04、T08 承接，历史入口和脚本仅作为可追溯资产存在。
- P01 是异构路口通行能力 POC / 成果模块，不替代 T09 正式契约。
- P02 是武汉局部人工锚定实验 POC / 成果模块，不进入正式主链，也不伪造 T07/T03/T04 产物。
- P04 是 Segment-first Road 直出 POC / 成果模块，不进入正式主链，不把当前 Road/LaneGroup、历史 V2/V3 或单 Case 候选提升为正式 RCSD。
- P05 是方案 A 神经网络 carrier 决策 POC / 成果模块；冻结业务骨架，不进入正式主链。既有模型与 RoadGraph/JSG PTO 只作为历史基线保留。

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
- F-RCSD QA：T06 Step3 结果继续由 T06 正式审计；外部 1V1 匹配生成的 F-RCSD 由 T12 检查 SWSD 方向等价可达性、必需方向缺失、非预期反向载体、road-node integrity、anchored canonical alias 到 raw Direction endpoint 的映射、canonical 候选图、raw verdict 图、portal-constrained semantic carrier、T07 Road-surface portal、SWSD 反向替代路径和自动高置信发布；人工复核仅作可选 QA 覆盖。
- 通行能力增强：T09 当前以 SWSD restriction / Laneinfo 为主，后续应引入 RCSD Laneinfo 和轨迹证据；P01 的 Arm / RoadNextRoad 经验可作为正式化前的参考材料。

## P05 P2-P3-P4 固定顺序

方案 A 的数据与闭包顺序固定为：
`Dataset-P1 scope -> context KEEP_SWSD safe materialization -> Node/Junction truth closure -> scorer metric`。
P2-P1 的 truth-free candidate、feature、payload 与 compatibility edge 可按 hash
复用，但标签层必须按该顺序重建。P4 后不再先建设新关系表征；下一可讨论阶段是
修正真值下的重训/复验，仍需独立授权。

## P05 P2-P3-P5 同架构复验结果

P5 已按上述固定顺序复用 candidate/feature/payload/compatibility，仅替换
scope-first Segment/Node label，并从头训练原 2.818M 级分层网络。硬门和通用闭包
保证三 seed 的最终错误发布为0及合法整图，但P6确认scorer层每seed仍各有1个错误
自动接受。seed 311/317 的自动覆盖不足，三个 seed 的 clue head 分别表现为过报或
漏报。当前策略因此保持“scorer 软判断 + 确定性安全 fallback”，不将安全层通过
解释为模型 GO。

P6 已完成失败归因。下一路线固定为双路：一条先提出不使用T06终态的关系/共享上下文
表征并做跨Case可分性审计；另一条把clue/abstention从carrier rank解耦并建立Case域
校准合同。二者未另行授权前，不训练新模型、不调当前held-out阈值、不挑seed。

P2-P3-P7 已执行上述两路的训练前可行性审计。表征路线仅使用现有合法
T01/T07/proposal/compatibility来源，并主动剔除历史证据中的Movement命名维；
校准路线只计算recall=1条件下单调阈值的理论最佳结果，不拟合校准器。两路均失败，
因此同一来源上的新scorer训练没有技术启动依据。后续只能先获得新的来源角色决策：
提升T03/T04为推理来源，或建设不读取T06终态的确定性关系生成器。

P2-P3-P8已选择并完成前一条路线的训练前来源合同审计。结果只支持将T03/T04的
relation/surface状态作为carrier软证据候选进入字段级promotion评审；Clue路线因
稳定错误覆盖仅`1/6`继续阻断。下一步不能直接重训完整scorer，应先由用户批准
carrier-only字段合同，再构建不改变冻结骨架、保留fallback的增量对照实验。

P9已按该策略完成严格A/B。602维Control与冻结Control后的source residual adapter
满足无来源零差异和Clue零source消费，但504个适用对象的pooled macro-F1/KEEP recall
与Control完全相同，稳定错误仍未纠正，故正式判定promotion model NO-GO。下一步不能
继续沿用同一adapter重复训练，也不能通过扩大fallback掩盖；若继续，需重新讨论来源
表示与Control饱和logit之间的交互架构。

P10不重训模型，而是冻结P9输出后应用对象级人工裁决。策略上先判
`selected_target in allowed_targets`，再单独统计是否命中`preferred_target`，Clue
继续作为独立head验收；Junction fallback优先于集合carrier选择。复算证明P9 carrier
已在全部适用对象上业务合法，但Treatment相对Control无增益。后续不得把真值校准GO
误表述为adapter GO；若启动新训练，必须另立目标并避免用本次事后裁决重报同一
held-out结果。对RCSD缺失对象先执行安全`KEEP_SWSD`，只有存在独立道路结构冲突证据
才设置`RealityChangeClue=true`。
