# 02 数据与领域模型

## 核心对象

- `TrainingSample`：一个 Case 归档版本及其任务 mask、scope 和可信权重。
- `SampleGroup`：按 `mainnodeid`、Segment ID 或 Case ID 形成的泄漏隔离单元。
- `LabelArtifact`：从可追溯 T10 run 解析的输入、辅助标签或 T06 主标签文件。
- `DataAnomaly`：缺失、冲突、不可追溯或不满足字段/CRS 契约的结构化记录。
- `EvaluationResult`：candidate 与 truth 的对象、属性、几何和有向拓扑差异。
- `ApprovedExclusion`：用户确认的参数化排除决定；保留样本证据与 split lineage，但关闭全部训练 task mask。
- `CandidateRoad`：来自 T01 Road 或 T05 RCSD Road 的推理时可用候选，包含几何、属性、端点语义和稀疏图边。
- `RoadOperationLabel`：T06 truth 对候选的 `DROP/KEEP/SPLIT_1/SPLIT_2/SPLIT_3` 监督，以及方向、source、切分几何和标签权重。
- `EntityLeakageDecision`：跨 Case 重复 Road 的唯一 split 归属及一跳邻域移除审计。
- `TaskTarget`：M2R 中某个样本、任务和目标类型的可用性、trust tier、权重、人工确认 scope、artifact lineage 与 CRS。
- `SharedSceneGraph`：不包含当前样本目标泄漏的基础 Road/Node/surface/raster 与稀疏图输入。
- `TaskPrediction`：T03/T04/T05/T06/T07 Head 的原始 logits、置信度和任务 mask。
- `DecoderIntervention`：通用图约束屏蔽非法动作的审计；不得包含事后业务修图。
- `RoadEdit`：R2 对基础 Road 的 `COPY/UPDATE/SPLIT/CREATE/DROP` 监督和模型输出；可以产生零个、一个或多个显式 output payload。
- `NodeEdit`：R2 对基础 Node 的 `COPY/UPDATE/CREATE/DROP` 监督和模型输出；区分最终 T06 Node 与先于 pointer 物化的 T05 阶段 Node 候选图。
- `T05PointerTarget`：R2 精确 `target_id -> base_id/NO_MATCH` 候选与唯一选择监督；候选是同次推理生成的 T05 Node `id/mainnodeid`，不是 truth 注入的输入对象。
- `PTOCandidate`：P0 的 Road/Node edit 或 pointer proposal，含 group/mode、canonical payload hash 与一到多个策略/base 来源；必须 `label_only=false`、`truth_derived=false`。
- `PTOSolveCertificate`：候选冻结后产生的 label-only cost、选中候选、objective/lower bound/gap、通用约束与 hard failure 记录。
- `FrozenJunction`：方案 A 冻结的业务 Junction 身份及其 Segment relation；模型不得增删改。
- `FrozenSegment`：T01 Segment 原样业务骨架，包含 `STANDARD/ADVANCE_RIGHT`、`pair_nodes/junc_nodes` 和至少一条独立 SWSD Road；`ADVANCE_RIGHT` 还必须保留 `source_segment_access/target_segment_access`。模型不得增删改。
- `JunctionSegmentRelation`：独立表达 `ENDPOINT/THROUGH` 与 `ENTER/EXIT/BOTH/UNKNOWN`；多 THROUGH 必须 REVIEW。
- `PhysicalMovement`：同一 JunctionUnit 内 Segment access 之间的物理可达，不受 T09 TrafficRule 过滤。
- `SemanticJunctionAnchor`：模型对一个 SWSD 语义路口输出的唯一 RCSD 锚定对象、关联 Road 与打断位置，以及 `SUCCESS/NO_EVIDENCE/AMBIGUOUS/ABSTAIN`；普通 Segment 后续判断不得反向修改锚定。
- `CarrierRealization`：普通 Segment 或 `ADVANCE_RIGHT` 的完整 Road/Node 实现，包含 Road 清单、业务用途、唯一所有权、access、方向、Node、打断/衔接和挂接关系；不是单个 `USE/KEEP` 标签。
- `RealityChangeClue`：证据与冻结骨架冲突时形成的线索，不改变骨架。
- `FallbackDirective`：模型明确给出 Segment/Junction 类型、原因和受影响对象；Segment 级只含一个 Segment，Junction 级只含该 Junction 的 T01 直接关联 Segment，确定性层校验但不补全、不传递扩张。

旧 `StandardSegmentUnit/SegmentConnector/PTO-A/PTO-B` 只存在于历史 JSG-PTO 证据。当前普通提右必须是 `ADVANCE_RIGHT Segment`，通过 source/target Segment access 直接关联两个普通 Segment，可包含真实 `junc_nodes`，并具有独立 Road。当前 T01 未显式存储 access 时，只接受“独立 Road 唯一有向端点 + 端点处唯一普通 Segment owner”的可追溯结果；不唯一即保留空值并形成现实冲突线索。

## 标签层级

`1.0` 表示目标对象经过逐对象人工确认/修正；`0.7` 表示整体 Case或指定
Segment/lineage 后继人工检查通过；`0.3` 只表示仅规则产出的上下文输入，不是弱标签，
不得进入 loss、threshold、calibration 或 metric。权重不表达样本难度，也不允许
自动推断上游字段的新业务语义。

## RoadGraph 语义

P05 主目标由 T06 F-RCSD Road 与 Node 共同定义。Road 的身份、方向、source、起终点引用和几何，与 Node 的身份和几何共同形成有向 RoadGraph；单独几何相似不足以证明语义等价。

M1 中 T06 Road/Node/relation 全部是 label-only。模型输入不得包含最终 ID、relation status/reason、generated/split reason 或由 validation/test truth 计算的统计。canonical ID 仅用于 lineage、label join 和泄漏审计，不进入数值特征。

M2R 中 T03/T04/T05/T06 目标全部按任务级 label-only 处理。下游 Head 可以消费共享 latent 或上游神经预测，但不得消费当前样本真实上游目标。`Unknown` 只能 masked，不能编码为 negative/rejected。T07 同样遵循 label-only 与可关闭辅助任务边界。

R2 oracle edit/pointer/output payload 全部是 label-only。Gate 1 允许读取 T06 Road/Node 和 T05 `rcsdnode_out/relation` truth 生成监督并验证表示往返；dataset 的 input role 白名单仍只包含 raw/T01 基础事实，不得把 truth-derived proposal、坐标或对象 ID 混入模型输入。T05 阶段候选图在推理时必须由模型 Node edit Head 生成，再供 pointer Head 消费。

PTO candidate layer 与 label/evaluation layer 使用两个不可变 manifest 隔离。candidate layer 只读 POC raw/T01、策略代码与重放输出；solve layer 固定引用 candidate manifest hash 后才可读取 R2 oracle truth。内容相同不等于 lineage 相同，独立策略结果与 truth 一致仍须保留不同路径和来源证明。

JSG-P0 truth layer 同样是 label-only。T01 `pair_nodes/junc_nodes/roads/sgrade/segment_type`、T05 锚定和 T06/R2 carrier 只能按已声明语义转换；无法解释或互相冲突的字段保留 evidence 并进入 `REVIEW/UNKNOWN`，不得升级为上游强规则。Road/Node 是编译载体，JSG 业务语义与 carrier identity 分层评价。

P0 实测保留了上述边界：真实 loop 为零实例；121 个 StandardSegment 缺少冻结 final carrier、26 个 Connector access 无法唯一证明、411 个 Terminal 类型证据不足，均保持 `REVIEW/UNKNOWN`，没有从几何近邻或局部字段补造语义。

P1 新增 `JSGP1Candidate/JSGP1CandidateSet/JSGP1SolveCertificate`。candidate payload 只含 PTO-A 业务语义投影或 PTO-B truth-free proposal 引用；carrier IDs、access legs、Oracle cost 与 truth signature 不进入候选特征。candidate/group/cost/selection 分开哈希。

P2 新增 `P2FeatureRow/P2LinearModel/P2CandidateScore/P2SelectionCertificate`。ID 只用于 split/join/audit，不进入 feature；feature token 只表达候选枚举、结构、source/role、复杂度和证据状态。label、fold、model、score、selection 分层哈希；V1 held-out fold 不得参与任何权重统计。

历史方案 A carrier baseline 的 label layer 只生成 Segment/Movement carrier 与异常软标签；该边界只作为旧实验事实保留。目标 A 先训练 T07/T03/T04/T05 路口 evidence、surface、relation、graph-consumable/junctionization 和完整锚定对象，通过后再训练普通 Segment、条件化 `ADVANCE_RIGHT`、RealityChangeClue/影响对象/fallback。T01 业务骨架仍没有增删改 target；旧 T07–T06 终态只能进入标签、loss 或评价，不能进入推理 feature。

Dataset-P0 的 T07 `DRIVEZONE_ONLY` 前置角色只作为历史 carrier 实验事实保留。当前路口阶段把原始 DriveZone 与 RCSDIntersection 分层存入 inference store，把 T07/T03/T04/T05 产物存入物理隔离的 label store；Step1 tensor 必须没有 RCSDIntersection 通道。

P2-P1联合数据包含`SEGMENT`与`NODE`两类candidate group。Segment group来自P1冻结Road option；Node group从PTO-P0全量FINAL_NODE truth-free payload按Road endpoint/JunctionUnit重组为`T01_NODE / PROPOSAL_NODE / OMIT` option。ID仅用于join/split/audit，payload仅用于物化/引用审计；模型feature只保留候选、对象、Junction上下文token和归一化相对量。Segment有效标签取carrier_labels；Node标签在候选冻结后由Segment真值Road来源条件化连接，PTO Oracle不直接作Node标签。

P2-P2-P2-P0新增`SafetyEvidenceExample`和candidate-first evidence contract。202维向量由冻结proposal的base OOF数值、proposal/KEEP原有Road统计差、Road payload集合差、有向端点图结构、Segment→Node compatibility/Junction共享压力、T07 DriveZone anchor覆盖和通用枚举token组成。Case/object/candidate ID只保留在lineage行，label-only truth在evidence signature冻结后独立join；probe只输出accept/fallback，不改选candidate。

P2-P2-P2-P1新增逐对象`MissingEvidenceAttribution`与`EvidenceCandidate`审计合同。终态只允许`INFERENCE_EVIDENCE_AVAILABLE / SOURCE_FACT_BLOCKED / UNOBSERVABLE_FALLBACK`且互斥；直接原因与相关模型信号分栏记录。T06 relation/terminal fact和truth-conditioned Junction fallback只允许用于归因、监督和评价，未经二次确认不能成为推理输入。

P2-P2-P2-P2新增`ROAD_CARRIER_UNSAFE / CLUE_MISS_ONLY / SAFE_AND_VISIBLE`三类业务结果与`PreT06SourceRoute`。每个重点Segment记录proposal/truth target、candidate target集合、carrier可达性、监督-only源、推理期组件和Junction依赖；T03/T04/T05/T06继续保持label-only，通用compatibility/Junction closure只保证图合法，不生成业务carrier真值。

P2-P3-P0新增`HierarchicalTrainingExample`：一个Segment组合P2-P1 carrier candidate、冻结202维T01/T07/truth-free结构证据、carrier/clue主标签和7维T03/T04/T05辅助标签。辅助标签不拼入推理feature，仅由训练loss消费；fold-local词表、数值标准化和inner-validation threshold均不读取held-out Case。

P2-P3-P1新增`FailureAttributionLedger`、`InferenceFieldRoleLedger`和`ValidationInventory`。前者按Segment记录stable/fold2/clue cohort、逐seed score/decision、truth、直接原因与source role；字段账本只允许`INFERENCE_ALLOWED/LABEL_ONLY/FORBIDDEN_LEAKAGE/UNAVAILABLE`四类；验证库存记录current-51/auxiliary membership、人工真值口径、replay、lineage、合同完整性和独立性。T07 Step1 `has_evd`只允许DriveZone，Step2 `is_anchor/anchor_reason`可消费RCSDIntersection；二者在P05均属于已存在的T06前证据。

Dataset-P1新增`SegmentPackageLineage`、`SegmentLabelScope`、
`ExpectedFailureScope`和`HistoricalMetricInvalidation`。标签范围使用四层资格：
Case terminal、Segment label、Segment scorer metric和context input。direct ID 是
Segment包正式身份；ID消失时只接受manifest冻结Road集合的精确分区，不读取geometry。
Case `EXPECTED_FAIL`只阻断发布并局部命中`failure_group_ids`，不覆盖其它对象资格。

P2-P3-P2新增`DatasetP1ScopeApplication`与`AllSegmentDecision`。前者把每个
P2-P3 Segment group精确标记为eligible或context-only，并以Dataset-P1
`label_weight`覆盖监督权重；后者把eligible scorer decision与context/local-failure
确定性fallback合并为8,863 Segment整图分母。scorer metric只允许6,275个eligible
对象，context与局部失败仍保留完整lineage和Case终态。

P2-P3-P3新增`AccessSafetyEligibility`和`ResidualSeparabilityAudit`。前者只含
`case_key/group_id/object_id/segment_type/access_valid/inference_source`及是否
触发硬门；后者记录每seed held-out训练范围、candidate margin、202维近邻、exact
signature碰撞和路线判定。标签真值只在审计结果中出现，不进入硬门或推理特征。

P2-P3-P4新增`ScopeFirstSegmentTruth`、`ScopeFirstNodeTruth`、
`JunctionFallbackClosure`和`LabelDelta`。Segment truth明确分开
`label_truth_contribution`与`safe_materialization_only`：eligible前者为1，
context-only前者为0且后者为true。Node truth只能由scope-first后的有效Segment
carrier requirement推导；label delta必须保留old/new target、candidate、anomaly、
scope class和eligible资格，禁止覆盖历史P2-P1标签工件。

P2-P3-P5新增只读复用层`ScopeFirstTrainingOverlay`：P4 Segment/Node truth覆盖
历史P2-P1 loader labels，candidate features、payloads、groups、compatibility
edges和oracle均按hash复用。`EligibleCarrierDecision`只覆盖6,275个目标对象；
`ContextSafeDecision`覆盖2,588个上下文对象且固定`KEEP_SWSD`。
`AccessGateDecision`只允许对40个`ADVANCE_RIGHT access_valid=false`对象设置
`accepted=false + clue_predicted=true`，之后才进入`JunctionSafetyClosure`和
`RoadGraphTerminalState`。

P2-P3-P6新增`ScorerDecisionOutcome`、`FinalPublicationOutcome`、
`ObjectAttribution`、`ClueError`和`EvidenceNeighborhoodAudit`。同一对象同时保留
scorer/final状态，不允许final原子阻断覆盖scorer事实。`ObjectAttribution`记录
carrier target/candidate正确性、clue probability/threshold、score/utility
margin和两层reason；邻域只从held-out fold之外的Case构造。

P2-P3-P7新增`MovementFreeBaseEvidence`、`CompatibilityNeighborhoodEvidence`、
`RelativeGeometryEvidence`和`ClueCalibrationContractAudit`。历史202维证据保留，
14个Movement命名维和28个对应邻域派生维被排除；最终表征为602维。T01 geometry
仅产生平移/旋转不变量，ID只用于Case内join，校准对象不包含任何fit后的参数。

P2-P3-P8新增`T03T04SourceFact`、`SegmentSourceApplicability`、
`CarrierSourceSignatureAudit`和`ClueSourceCoverageAudit`。`target_id`只作
Case-local lineage join；promotion候选不含ID、坐标、路径、reason、review、
T05/T06终态、truth或Movement。T04方向字段可作上下文，但不拆分carrier安全状态
signature；无来源明确为`NOT_APPLICABLE`。

P9 overlay把source fact编码为carrier residual输入；`source_applicable=false`时
residual为0。Clue branch不包含source representation。

正式P9 fold-local编码维数为`264/268`，adapter trainable参数为
`30,721~31,105`。5,771个无来源对象保持全零residual并逐对象复用Control；
该表示不改变P8历史role contract，也不成为T03/T04输出字段。

P10新增`HumanCarrierAdjudication`：`allowed_targets`表达业务合法集合，
`preferred_target`表达优选，`clue_target`独立表达现实冲突，`target_weight=1.0`
覆盖Case级0.7，`fallback_scope`约束Segment/Junction最小闭包。未裁决对象继续
candidate-exact；该对象只存在于label/evaluation overlay，不进入模型输入。
`rcsd_candidate_role=UNAVAILABLE`只表达RCSD候选缺失，不等同于
`RealityChangeClue=true`。

P12R新增`AdvanceRightRealizationUnit`、`AdvanceRightCandidateGroup`和
`AdvanceRightAttachmentAudit`。Unit以冻结Segment access关联两个普通Segment，
由普通Segment T06 relation产生两侧`required_source`，再由T06终态和审计动作
产生label-only `realized_source/truth_plan`。`topology_supplement_from_swsd`
保留SWSD lineage；`replacement_segment_ids`只表示T06动作上下文，附着Segment
必须由实际target Road lineage反查owner。候选组只包含T01 SWSD identity与原始
RCSD，不包含T05提右锚定或T06终态。

P12R-R1新增`AdvanceRightEndpointCandidate`、`EndpointEvidenceAudit`和
`CandidateDelta`。候选以Case-local原始RCSD Road bundle为原子，保留Road ID、
component/bundle lineage、两侧incident普通Road、T01相邻普通Segment owner、
orientation及各距离证据；不重写Road/Node几何。`AMBIGUOUS`只表示不同owner方向
无法唯一确定，必须拒绝自动加入。label只在candidate frozen signature产生后用于
Control/Treatment Oracle，不进入候选字段。

P13-P0新增`AdvanceRightCandidateFeature`、`CandidateSetScore`、
`SafetyAbstentionScore`和`AdvanceRightCarrierDecision`。50维feature只含
candidate source、bundle/incident/owner关系、相对几何和集合rank；5m Local
membership作为固定prior。模型输出raw候选Road集合，safety head和置信门再决定
是否发布；空集合解释为`KEEP_SWSD`。Review/Oracle不可达身份只用于label-only
评价，除T01 access无效外不得成为推理mask。
