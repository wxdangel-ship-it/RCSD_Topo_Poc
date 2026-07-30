# 02 数据与业务模型

## 文档定位

本文档承载项目级全局业务概念、共用数据对象、字段语义和术语。模块局部字段、阈值、Step 规则和输出契约仍以模块级 source-of-truth 为准。

## 数据对象

| 对象 | 项目级含义 | 主要消费者 |
|---|---|---|
| SWSD | 现场道路、节点、Laneinfo、restriction 等源侧语义数据 | T08、T01、T03、T04、T05、T06、T11、T12、T09 |
| RCSD | 场景路网侧 Road / Node / RoadNextRoad 等承载数据 | T08、T03、T04、T05、T06、T11、T09 |
| F-RCSD | 融合后的承载数据；当前仓库生产链中的 F-RCSD 由 T06 Segment 替换生成，T12 质检对象则是外部 1V1 匹配技术生成的原始 F-RCSD，两者 Source 语义一致但生成路径不得混同 | T11（T06 结果审计）、T12（原始 1V1 F-RCSD 质检）、T09、P01、P02（局部实验审计） |
| Semantic Junction | SWSD 语义路口代表对象，承载路口级关联、锚定与通行建模语义 | T07、T03、T04、T05、T09 |
| Segment | 以 SWSD Road / Node 组织出的可替换道路连续单元 | T01、T06、T11、T09 |
| Virtual Anchor | 在无现成 RCSD 路口面或需补充表达时构建的虚拟锚定成果 | T03、T04、T05 |
| Relation Evidence | SWSD 与 RCSD 语义路口、Road、Segment 的关联证据 | T05、T06、T11、T09 |
| Patch Vector Evidence | 与 SWSD/完整 RCSD 无对象级直接 ID 关系的 Patch Lane、LaneTopo、Boundary、道路面和设施证据；通过 Segment 覆盖范围、Patch membership 与跨 Patch 统一聚合建立候选，高精 Road 几何以此为正式物理证据 | P04 |
| Segment-first RoadGraph Candidate | P04 中由 T01 Segment 和 SWSD 路口—路段先验建立完整语义骨架，由 T07/T03/T04/T08 accepted surface 定义 JunctionUnit，再由 Patch Vector、同版本 Patch Road 与 LaneTopo 实例化的 Road/Node/RoadNextRoad POC 候选；语义存在、证据支持、可发布性与接管范围必须分离 | P04 POC QA |
| P05 Training Sample | 限定本地 Case 的实验样本；包含人工检查边界、任务 mask、标签权重、lineage 与业务 ID 分组，不等同于生产真值 | P05 |
| P05 Task Target | M2R 中按 T03/T04/T05/T06/T07 和目标类型拆分的 `available/unknown/invalid/excluded` 部分标签；缺失任务只 masked，不等同于负样本 | P05 |
| P05 R2 Graph Edit | 对基础 Road/Node 的 `COPY/UPDATE/SPLIT/CREATE/DROP` label-only 动作及输出 payload；用于证明/监督完整 T06 RoadGraph，不得作为推理输入 | P05 |
| P05 R2 Pointer | T05 `target_id -> base_id/NO_MATCH` 的精确候选与唯一选择监督；基数和 base existence 必须独立审计 | P05 |
| P05 PTO Candidate | 由 raw/T01 与登记策略 commit 独立重放产生的有限 Road/Node edit 或 pointer proposal；`label_only=false`、`truth_derived=false`，按规范化 payload 去重并保留来源 lineage | P05 |
| P05 PTO Solve Certificate | 候选 manifest 冻结后生成的 label-only cost、选中候选、objective/lower bound/gap 与通用图约束证书；不等于 learned scorer 输出 | P05 |
| P05 Scheme-A Frozen Skeleton | 冻结的 T01 Segment 集合、JunctionSegmentRelation 和 PhysicalMovement 存在性；模型不得增删改。普通提右属于 `ADVANCE_RIGHT Segment`，以 `source_segment_access/target_segment_access` 连接两个普通 Segment，可包含 `junc_nodes`，并必须有独立 Road | P05 |
| P05 Carrier Realization | Segment、JunctionUnit 和 PhysicalMovement 的 Road/Node 实现；是模型允许评分/选择的对象，不改变业务对象存在性 | P05 |
| P05 Dataset-P0 Semantic Record | 对 T01/T07/T03/T04/T05/T06/T09/T11/T10 artifact 标记模块职责、训练角色、权重、task mask、lineage 与候选来源；T01 只能是冻结骨架/SWSD fallback，T07 固定 DriveZone-only，T06 Step3 Road/Node 是最终主标签 | P05 |
| P05 P2-P1 Joint Scoring Group | Segment组使用冻结Road candidate；Node组从PTO-P0全量FINAL_NODE truth-free payload按Road endpoint/JunctionUnit重组为`T01_NODE / PROPOSAL_NODE / OMIT` carrier option。candidate先冻结，随后由方案A有效Segment标签及Road来源连接条件化Node标签；PTO Oracle不直接作Node标签。JunctionUnit兼容边只表达共享Node payload、引用和拓扑合法性 | P05 |
| P05 P2-P2-P2-P0 Safety Evidence | candidate-first 的 Segment accept/fallback 数值证据；由 T01 冻结骨架、T07 DriveZone-only anchor、proposal/KEEP Road 有向结构差、Segment→Node compatibility/Junction共享压力和 base OOF 统计组成。Case/object/candidate ID 只作 lineage，T03/T04/T05/T06 字段和 label 只在证据冻结后参与评估 | P05 |
| P05 P2-P2-P2-P1 Missing Evidence Attribution | 对 9 error、残留 unsafe accepted 与 40 Review 的唯一对象并集记录直接原因、辅助信号、推理可用性、源角色、生成时点、成本和 lineage；终态仅为 `INFERENCE_EVIDENCE_AVAILABLE / SOURCE_FACT_BLOCKED / UNOBSERVABLE_FALLBACK`，label-only 事实不得因相关模型信号自动升级 | P05 |
| P05 P2-P2-P2-P2 Pre-T06 Source Route | 将旧 unsafe 拆为 `ROAD_CARRIER_UNSAFE / CLUE_MISS_ONLY / SAFE_AND_VISIBLE`，并对重点 Segment 记录 candidate target 可达性、label-only 辅助监督、推理期分层组件和 Junction 依赖闭包；T03/T04/T05/T06 不因进入监督路线而改变现有 source role | P05 |
| P05 P2-P3-P0 Hierarchical Example | 每个 Segment 由 P2-P1 candidate set、冻结 202 维 T01/T07/truth-free 结构证据、carrier/clue 主标签和 7 个 T03/T04/T05 `label_only` 辅助标签构成；辅助标签只进入训练损失，held-out 推理不得读取对应 artifact | P05 |
| P05 P2-P3-P1 Failure/Evidence Ledger | 对稳定 false-use、fold 2 和 clue-only Segment 记录 candidate/score/decision/truth、直接事实、字段角色和逐 seed 结果；字段唯一归类为 `INFERENCE_ALLOWED/LABEL_ONLY/FORBIDDEN_LEAKAGE/UNAVAILABLE`，验证库存另外记录 current-51 membership、人工真值口径、replay/lineage 与独立性 | P05 |
| P05 Dataset-P1 Segment Label Scope | 将 Case terminal、Segment label、Segment scorer metric 与 context input 四层资格分离；T10 全 Case可标注，T10-Error/T10-Error-2 只允许 manifest target ID 或无歧义 Road partition 后继标注，其它 Segment固定为 `CONTEXT_ONLY_MASKED` | P05 |
| P05 P2-P3-P2 Scope Application / AllSegmentDecision | 将 Dataset-P1 scope精确join到P2-P3 example；eligible对象覆盖监督权重并进入OOF，context-only与局部expected-failure对象生成确定性`KEEP_SWSD` fallback；scorer metric使用6,275对象，整图effective selection使用8,863对象 | P05 |
| P05 P2-P3-P3 AccessSafetyEligibility / ResidualSeparabilityAudit | `ADVANCE_RIGHT access_valid=false`由冻结T01事实直接触发Review fallback；不读取标签或T06终态。残余false-use只在held-out训练Case内审计202维证据近邻、候选margin与表征重叠，不生成业务规则 | P05 |
| P05 RealityChangeClue | 推理证据与冻结结构冲突时产生的可审计线索；只触发失败/fallback，不自动改写业务结构 | P05 |
| P05 Fallback Plan | 按 Movement/Segment/Junction 最小依赖闭包保留 SWSD 或阻断发布的确定性计划；业务正确才计成功 | P05 |
| P05 Historical JSG/PTO Evidence | 旧 Junction/StandardSegment/SegmentConnector/PTO-A/PTO-B、scorer 与 compiler 的历史证据；不得作为当前方案 A 业务本体或当前模型指标 | P05 |

方案 A 以 T01 为 Segment 集合源事实，不再把普通提右转换为 `SegmentConnector`。Junction、Segment、PhysicalMovement 与 carrier realization 分层；TrafficRule 继续由 T09 表达。历史 JSG-PTO-P0/P1 的 signature、Oracle 和 compiler 证据保留追溯，但 PTO-A 不得选择或改变当前骨架。

## 主数据流

```text
SWSD / RCSD raw data
  -> T08 preprocessing and QC
  -> T01 SWSD Segment
  -> T07 / T03 / T04 junction anchoring
  -> T05 semantic junction relation fusion
  -> T06 Segment replacement and F-RCSD
  -> T09 traffic rule restoration
```

## 字段语义

| 字段 / 字段族 | 当前项目级语义 |
|---|---|
| `mainnodeid` / `subnodeid` | SWSD 语义路口代表 node 与子 node 关系，用于路口级聚合、锚定和证据归集。 |
| `kind` / `Road.kind` | 道路种别字段；单个 token 为 `XXXX`，前两位表示道路等级，后两位表示道路类型，多个 token 用 `|` 分隔。 |
| `kind_2` | SWSD 语义路口类型字段，当前用于区分交叉、T 型、分歧、合流、复杂路口等业务类型。 |
| `grade_2` | SWSD 语义路口等级字段，配合 `kind_2`、拓扑和道路等级进行候选识别与质量判断。 |
| `closed_con` / `closed_connect` | 两者表达同一 SWSD Node 闭合连接语义。`closed_con` 是项目规范字段；`closed_connect` 是正式启用的原始输入别名，由 T08 copy-on-write 归一为 `closed_con`。两字段同时存在时必须值一致，不一致不得继续。当前适用范围为 SWSD Node 输入；不据此扩展 RCSD 字段语义。 |
| `formway` / `Road.formway` | 道路形态语义字段，已用于道路形态判断、through incident degree 裁剪等跨模块判断。 |
| `RCSDRoad.formway` | RCSD 道路形态字段；当前确认 `1024` bit 表示调头口，表达式为 `(formway & 1024) != 0`。 |
| `direction` | 道路方向语义，参与 Segment、通行规则、调头 fallback 等判断；方向不可信时只能审计，不得直接固化强过滤。 |
| `Laneinfo.Arrow_Dir` / T08 `arrow` | SWSD 车道箭头语义；字母型箭头码大小写不敏感，`A/a` 表示 `straight`，数字 `0` 与字母 `o/O` 语义不同。 |
| `restriction` | SWSD 限行 / 禁转语义输入，T09 用于路口通行规则还原。 |
| T05 `T11_MANUAL` relation audit | 人工审计后由 T05 正式发布的正向 relation 来源。T06 Step1 只在 `source_modules/source_module` 包含 `T11_MANUAL`、`relation_status/status=0`、`base_id>0` 且 `graph_consumable=1` 时，用它释放对应 `is_anchor=fail3/fail4` 的旧锚定失败门禁；该语义不改变节点事实，也不是 T06 Step2/Step3 替换白名单。 |
| T12 quality hypothesis | SWSD 与原始 1V1 F-RCSD 在方向通行性上应等价：SWSD 必需方向不应缺失，单向 Segment 也不应无证据地增加反向载体。该语义用于 raw endpoint topology、portal-constrained semantic carrier、标准路口 portal、SWSD 反向替代路径和锚点可信度联合质检；semantic carrier 只排除 raw 假断裂，SWSD 等价反向路径只排除反向误报，完成各自排除门禁且通过高置信锚点规则的记录才可进入正式问题层，但任何质量结论都不得直接提升为修复规则。 |
| `SWSD Road.patch_id`（P04） | P04 当前确认其为 Patch membership；逗号分隔表示多个 Patch 共同覆盖同一 SWSD Road。它只能限定 Segment 候选证据范围，不构成 Patch Vector 对象级匹配。跨 Patch Segment 必须先统一聚合证据再构建。 |
| `DriveZone_fix / DivStripZone_fix`（P04） | T00 生成的修正版图层：`DriveZone_fix` 与原始 `DriveZone` 业务语义等价，均表示道路面；`DivStripZone_fix` 与原始 `DivStripZone` 业务语义等价，均表示路面导流带，不是 Patch 分区。`fix` 的 per-Patch 生成方式只属于处理与 lineage 事实，不产生新的业务对象类型；P04 不把 raw 与 fix 当两份独立证据重复计权。 |
| `ReferenceLane.FlowNum`（P04） | 当前可用语义为轨迹聚合强度的弱证据，用于 movement 候选排序和审计；不解释为精确车流量、合法通行规则或单独的 accepted 门禁。 |
| `inferred_lane_width_m`（P04） | 通过 Lane 局部垂线分别投影到左右最近且方向/走廊相容的 LaneBoundary，取两侧距离之和形成的几何推导宽度；必须同时记录双侧匹配覆盖率和宽度稳定性，不能由单侧或跨道路 Boundary 补造。 |
| P04 Segment 发布状态 | `hp_full / hp_partial / swsd_retained / conflict_retained`。它描述 Segment carrier 的证据与发布方式，并与 `segment_publishable`、`carrier_takeover_ready`、`replacement_scope`、`review_required` 和 `evidence_quality_state` 分离。`hp_partial` 内的新建 Road 只允许由 `hp_observed + hp_constrained_completion` 组成，不直接拼接 SWSD 坐标；不能满足 hard gate 时整体保留原 carrier 或仅阻断该 Segment，不得以 review 绕过。 |
| P04 Road/Node 连通不变量 | 每个正式 Segment 至少有一条独立 Road；高精证据可区分上下行时必须形成两条连续方向主干链，链可按LaneGroup、物理Node、`junc_nodes`、分流合流和证据边界细分为多条Road，铺装面内无法区分方向时可发布双向Road，非高速主辅路等按T01结构可包含额外方向链和附属Road。SWSD负责完整的逐Segment Access方向与逐Junction Movement拓扑合同，不负责built坐标或Road一一对应；细分后仍按归一化方向链保持该合同。ordinary Junction保留分布式portal Node，同一正确分类JunctionUnit的Node共享mainnodeid，不生成中心聚合点或星形内部Road；其RoadNextRoad由同一ordinary JunctionUnit内方向兼容的进入—离开Road组合编译，并记录两端物理Node与Junction lineage。Segment内部连续性和复杂路口仍要求实际共享Node或显式物理关系；T04复杂路口、环岛和聚合异常不得由mainnode机械全连接。跨Segment被拒Movement显式排除，不自动回退两侧Segment。 |
| P04 历史候选 | M2、冻结 Directional V2 与 High-Precision V3 保留为回归和几何对照，不再作为当前 Segment-first 数据模型。 |
| P05 `label_weight` | P05 监督可信度：`1.0` 为 T03/T04 目标对象逐对象人工确认/修正，`0.7` 为 T10 整体 Case或指定 Segment/lineage 后继检查通过；`0.3` 只允许表示非目标规则上下文的 `context_input_weight`，不得进入 label、loss、threshold、calibration 或 metric。仅适用于 P05 POC，不改变上游字段语义。 |
| P05 `task_availability` | M2R 任务标签可用性；只有可追溯 artifact 和人工确认 scope 同时成立时为 `available`，否则为 `unknown/invalid/excluded`，不得从 `Error` 目录名推断。 |

## 字段治理规则

- 外部 GPKG / GeoJSON / Shapefile / CSV / JSON 记录的字段名按 `str(field_name).casefold()` 解析；模块契约中的字段名是 canonical logical name，因此 `snodeid`、`snodeId`、`SNODEID` 只在名称层等价，字段值语义不变。
- 字段名归一化只用于外部字段查找，不得修改原输入或向原属性就地插入 lowercase alias；普通 copy-on-write 输出继续保留原字段名，模块正式输出 schema 继续使用各自契约中的 canonical 名称。T01 working layer、T06 内部 feature 和 P01 内部模型按各自契约在独立副本中发布 lowercase canonical keys，属于显式 canonicalization，不得回写输入文件。
- 同一记录存在多个仅大小写不同的原字段时，相同非空值或单一非空值可归并读取；不同非空值必须以字段冲突显式失败，不得按遍历顺序 silent fix。
- 大小写归一化不得自动扩展业务别名；`startNodeId` 是否等价于 `snodeid` 仍必须由项目或模块契约正式声明。模块自产 handoff / audit 字典继续使用精确 canonical key，避免掩盖模块间契约拼写错误。
- 未在项目或模块源事实中正式启用的字段，不得进入 Step1 / Step2 强规则。
- 字段正式启用时，必须说明可用语义、适用范围和未确认边界，并同步写入对应模块契约。
- 禁止基于局部样本、人工真值或单次冒烟结果反推字段含义并固化为强规则。
- 当数据现象与已确认字段语义冲突时，应先形成审计证据并回到契约层裁定。

## 术语

| 术语 | 含义 |
|---|---|
| SWSD | 现场语义道路数据源。 |
| RCSD | 场景路网承载数据源。 |
| F-RCSD | 融合 SWSD Segment 替换成果后的 RCSD 承载数据。 |
| 语义路口 | 以 SWSD node 组织的路口级业务对象。 |
| 虚拟锚定 | 基于道路面、导流带、SWSD、RCSD 等证据构建的路口关系锚定成果。 |
| 文件证据包 | 用于本地 case 分析、内外网协作和结果复核的文件化证据集合。 |

## P05 Dataset-P1-first 真值层

P05 Segment 对象同时具有两种互斥资格：`label_eligible=true` 的对象贡献监督真值；
`CONTEXT_ONLY_MASKED` 对象只以 `context_input_weight=0.3` 提供输入上下文。后者在
整图安全物化时使用 `KEEP_SWSD`，但该选择不是标签。Node carrier 与 Junction
fallback 必须在这两类资格冻结后计算，禁止由 context-only 原标签触发监督真值级联。

## P05 P2-P3-P5 训练与输出对象

P5 以 `ScopeFirstTrainingOverlay` 只重建标签层：8,863 个 Segment 中 6,275 个为
训练/指标对象，2,588 个只作输入上下文；修正 Node 标签为 28,240 个。模型输出分为
`CarrierDecision` 与 `RealityChangeClue`，之后依次经过 40 个
`ADVANCE_RIGHT access_valid=false` 硬门、Node/Junction compatibility 闭包和
RoadGraph materialization。context-only 的 `KEEP_SWSD` 是安全执行选择，不是模型
监督标签，也不进入 coverage 或 clue 指标。

## P05 P2-P3-P6 双层审计对象

P6 新增只读 `ScorerDecisionOutcome`、`FinalPublicationOutcome`、
`ObjectAttribution`、`ClueError` 与 `EvidenceNeighborhoodAudit`。完整审计分母为
6,275 eligible；safe coverage 排除40个强制 Review，以6,235为分母。scorer层保留
逐对象模型判断和局部failure group，publication层保留RoadGraph原子阻断；两层不得
互相覆盖。邻域只允许使用held-out fold之外的Case，不把truth写回推理工件。

## P05 P2-P3-P7 表征与校准对象

P7新增`MovementFreeBaseEvidence`、`CompatibilityNeighborhoodEvidence`、
`RelativeGeometryEvidence`和`ClueCalibrationContractAudit`。历史202维证据只读
保留；实际命名为`MOVEMENT_DEGREE/CONTEXT_MOVEMENT_DEGREE`的14维及其28个邻域
派生维不进入P7，最终维度固定为`188+377+37=602`。T01几何只输出长度、曲折度、
转角和方向离散度等平移/旋转不变量；Segment/Node ID只作Case内join。校准对象只
记录outer fold、inner pool和诊断指标，本阶段fit/tuning均为0。

## P05 P2-P3-P8 来源合同对象

P8新增`T03T04SourceFact`、`SegmentSourceApplicability`、
`CarrierSourceSignatureAudit`和`ClueSourceCoverageAudit`。来源事实只保留正式
T05 handoff枚举、对象计数和形式合法性布尔量；ID只作lineage和Case-local
`junc_nodes`精确join，坐标、路径、free-text reason、review、T05/T06终态、truth
和Movement均禁止进入promotion候选。T04 `merge/diverge`保留为上下文候选，但
carrier安全状态signature对该方向不变；无来源是`NOT_APPLICABLE`，不是负特征。

P9 promotion overlay将P8 `T03T04SourceFact`限制到carrier branch；历史Dataset-P0
角色不回写。`source_applicable=false`必须产生零source residual，Clue branch的
source feature/loss/decision计数必须为0。

P9正式结果验证了该隔离合同：5,771个`NOT_APPLICABLE`对象的Control/Treatment
score与decision差异为0，Clue概率差异为0；504个适用对象进入fold-local
unknown/tri-state/log1p/mean-max编码，但没有形成carrier分类增益。该编码结果只属于
P9实验工件，不回写T03/T04或P8字段角色。

P10新增`HumanCarrierAdjudication`评价覆盖：对象级人工裁决包含
`allowed_targets/preferred_target/clue_target/target_weight/fallback_scope`。
`allowed_targets`回答业务是否合法，`preferred_target`只评价优选命中，
`clue_target`独立表达现实冲突；三者不得合并为单一硬标签。对象级1.0裁决覆盖
Case级0.7，未裁决对象继续candidate-exact。该overlay只进入label/evaluation，
不得成为模型输入或回写P9历史工件。`rcsd_candidate_role=UNAVAILABLE`表示RCSD
候选数据缺失；若没有独立现实冲突证据，应`KEEP_SWSD + clue_target=false`，不得把
数据可用性缺口自动解释为道路结构变化。
