# 06 风险与技术债

## 当前架构风险

| 风险 | 影响 | 缓解方向 |
|---|---|---|
| 字段语义漂移 | 局部样本反推字段可能污染正式规则 | 字段启用必须写入项目级或模块级源事实，并保留未确认边界 |
| RCSD Laneinfo / 轨迹证据缺失 | T09 对混源路口通行能力还原仍不完整 | 先以 SWSD Laneinfo / restriction 和 F-RCSD 承载关系恢复，再专项补证 |
| 混源 F-RCSD 解释风险 | SWSD Segment 替换后 Road / Node 语义可能难追溯 | T06 / T09 必须保留 source、relation evidence 和审计摘要 |
| 锚定召回与准确率权衡 | 兜底关系提高替换率，但可能引入误关联 | T05 汇总关系时区分正式、兜底、review-only 证据 |
| 将 P2 安全保留率误当候选可达率 | 错误认为本地 Case 缺少正确 RCSD，或要求 T01 提供 RCSD candidate | Dataset-P0 分离 T01 SWSD fallback 与非 T01 proposal 分母；保留历史指标但以模块职责重解释 |
| P2-P1复用单一proposal Node图层 | 重新制造旧P2 mainnode兼容缺口，使模型无法选择实际存在于其它replay的正确Node | Node carrier payload必须来自PTO-P0全量多来源FINAL_NODE集合；按endpoint/JunctionUnit重组并冻结后，再由Segment Road来源连接条件化标签 |
| 把完整T06 PTO Oracle直接作为混合RoadGraph Node标签 | `KEEP_SWSD` Road所需T01 Node被错误丢弃，Oracle组合也会出现endpoint缺失 | PTO Oracle只作候选可达性证据；Node真值按Road来源选择`T01_NODE / PROPOSAL_NODE / OMIT`，共享payload冲突执行Junction fallback |
| P2-P1条件化图合法但高置信carrier仍选错 | 通用图约束可把错误Road/Node组合成合法图，若只看RoadGraph会误判可自动发布 | P2-P2-P0 已把对象级17/9/17分解为accepted Segment根错误2/0/3及Node传播；单一阈值零错误覆盖最多20.03%，下一阶段冻结基础scorer并研究cross-fitted/class-aware safety head，不在原held-out上调阈值重报GO |
| 独立safety head在有限Case上不稳定 | P2-P2-P1中零错误seed覆盖仅约7%，较高覆盖seed仍接受4~5个稳定错误；继续调本次held-out会形成选择泄漏 | 当前模型正式NO-GO并只保留离线review；若继续，必须另立阶段增加truth-free局部证据或预训练表征，保持Case隔离并用新门禁重验，不以扩模型/加epoch/调阈值重报GO |
| 当前合法truth-free结构证据仍不足 | P2-P2-P2-P0 的202维证据使浅层MLP全局零错误，但跨Case fold仍不能同时维持unsafe recall=1和50%覆盖；平均指标会掩盖fold失效 | 当前证据路线正式EVIDENCE_NO_GO；停止在已见Case上继续调参。只有新增推理期信息源或独立预训练表征并使用新冻结验证集才可重启；label-only字段提升必须二次确认 |
| 直接风险事实被源合同阻断 | P2-P2-P2-P1 的22个风险对象均能由T06/联合真值直接解释，但这些事实产生于label/evaluation层；直接作为输入会形成truth泄漏或把P05降为T06后处理 | 保持22对象强制fallback/Review；只接受在T06之前独立生成且经source-contract审计的等价事实。P2-P1 joint fallback precision仅20.83%~29.81%，不得作硬门 |
| carrier安全与clue可见性混为unsafe | 正确`KEEP_SWSD`但漏报RealityChangeClue会被误解为错误Road，掩盖真正的覆盖率问题 | P2-P2-P2-P2固定双指标：carrier错误与clue-only漏报分开；现有浅层MLP carrier全局安全但仅2/5 fold通过coverage，仍禁止自动发布 |
| 单层scorer无法表达Junction依赖与MIXED | 16个Junction依赖对象需要共享Node一致性，1个MIXED候选需要不同于二分类KEEP/USE的选择；继续扩同一safety head无法稳定跨Case | 后续若授权，使用carrier scorer、辅助node evidence/clue head和通用Junction闭包的分层架构；T03–T06保持监督角色，不作推理规则 |
| 分层模型的selective calibration仍不稳定 | P2-P3-P0虽使49+2整图全部合法，但seed 311/313稳定错误接受同一Segment，seed 317靠大量clue/fallback避免错误；fold 2三seed覆盖均约0.29 | 当前模型NO-GO；冻结双跑证据，禁止在已见held-out上继续调阈值/挑seed。后续须引入新推理期表征或新冻结验证证据，T03–T06继续保持label-only |
| P2-P3-P1新增推理证据与独立验证均缺失 | 直接根因只存在于label-only Junction/T06 final事实；51个端到端Case已全部用于OOF，其余本地包不是冻结RoadGraph真值 | 保持`EVIDENCE_NO_GO`；先确认coverage分母，再建设T06前新表征和独立验证合同，禁止把旧Case复用或label-only字段提升伪装成新证据 |
| expected baseline failure级联污染对象coverage | 旧P2-P3把`T10:609214532/74155468`全Case 1,795/159个Segment覆盖为fallback，混淆Case不可发布与对象评分 | Dataset-P1固定双层合同：Case仍`EXPECTED_FAIL`，只对`failure_group_ids`局部失败；其它Segment保留scorer资格，corrected cascade mask=0 |
| Dataset-P1重训后scorer仍跨Case不稳定 | 一个可靠target Segment在seed311/313重复`KEEP_SWSD→USE_RCSD`，seed313另自动发布12个ADVANCE_RIGHT Review；seed317零错误但coverage仅0.1506 | 保持P2-P3-P2 MODEL_NO_GO；Review/ADVANCE_RIGHT先走独立硬安全资格，剩余false-use需新增T06前表征或独立验证，禁止挑seed/调已见held-out |
| 当前202维表征把残余KEEP对象映射到USE区域 | P2-P3-P3中三个seed均大margin选择USE，三个held-out域前20近邻合计60/60为USE真值 | 保留已通过的access硬门；下一阶段先补充并冻结T06前关系/共享上下文表征，再决定逐对象scorer或跨Segment图模型，不重训同一表征 |
| T06 替换边界复杂化 | RCSD 数据质量和工艺差异导致 T06 同时承担 relation 诊断、补拓扑和替换执行，容易扩大模块职责 | T06 只在 Step2 replacement plan 和 Step3 audit 边界内执行；上游问题通过 problem registry / T10 feedback 回流 |
| Surface-assisted closure 误用 | T03/T04/T05/T07 surface 证据若被当成替换白名单，可能绕过 T04 reject 或多候选冲突 | Surface closure 只补节点语义或 relation node map，不新增正式替换道路，不改写原始道路几何 |
| 提前右转与保留 SWSD carrier 混源 | 提高通行 carrier 保留率的同时可能模糊正式替换道路来源 | `frcsd_road_ids` 描述最终可消费 carrier，可包含 `source=2` 保留 SWSD；必须通过 `replaced+retained_swsd`、`frcsd_road_source_values / source_mix` 和风险标记暴露混源边界 |
| T10 feedback 自动回灌过度 | 上游反馈若直接驱动替换，可能绕过 T03/T04/T05/T06 正式审计 | T10 feedback 只回灌可消费 endpoint candidate 或形成上游任务，不作为 T06 Step3 替换白名单 |
| 原始 1V1 F-RCSD 与 T06 F-RCSD 混用 | 相同 Source 语义但生成路径不同，混用会污染质检结论 | T12 只接受显式 `frcsd_1v1_roads / frcsd_1v1_nodes`，不得回退到 T06 Step3 输出 |
| T12 候选被误当正式问题 | 自动可达性检查仍可能受 canonical 节点折叠、node portal、路口归组、SWSD 反向绕行、相邻 Segment RCSD 借用或数据覆盖影响 | 已锚定 mainNode 只把选中 `base_id` canonical group 的 raw alias 提升为 portal 候选，禁止递归展开其它 grouped node 的 group；仍须在 raw identity 图按当前方向形成物理 Road carrier。锚定 alias 距离仅审计，非锚定 spatial fallback 仍受硬门禁。既有 semantic carrier 保留端点和内部 alias 约束；正确且唯一的 T07 标准面允许用有向物理 Road 的 surface 相交或 anchor→frontier、接触标准面的单侧一跳 support 排除 node-portal 假断裂，禁止双端任意一跳拼接。非预期反向载体必须搜索 SWSD 全图反向替代路径并按同一几何阈值保守排除；第一/最后 Road 还必须接触当前双端标准面，锚点间逐 raw RCSD Road 必须唯一归属于当前 Segment，不能借用其它 Segment 更强覆盖或并列路径。其它弱证据只进入候选/排除层。锚点可信度、方向和路径长度继续门禁，外部 review 只作可选 QA 覆盖 |
| T09 通行证据缺口 | T09 已具备模块文档面，但 RCSD Laneinfo 与轨迹通行证据仍不足 | 后续专项补充 RCSD Laneinfo / 轨迹证据，并同步 T09 契约 |
| P04 直出 POC 过早正式化 | 冻结 Directional V2 与 High-Precision V3 仅证明历史候选在单 Case 技术门禁下成立，未证明 Segment-first 语义完整、JunctionUnit 边界、局部结构召回、部分资料缺失接管和正式 Road/Node/RoadNextRoad 合同；restriction/ReferenceLane 完整合法性仍未接入 | 保持 Active POC、无正式入口；按独立 Segment-first SpecKit 实现，未知字段不进强规则，状态、可发布性、接管范围与输入质量解耦，继续做真实数据、多 Case movement/几何真值/性能 QA |
| T02 历史入口仍在 | Retired 生命周期与真实脚本入口容易混淆 | 后续入口治理中同步 retired / historical 口径 |
| P05 Segment包上下文被误作弱标签 | T10-Error/T10-Error-2 包内非目标Segment曾以0.3进入训练/指标，造成stable-wrong与coverage分母失真 | Dataset-P1只允许target ID或无歧义Road partition后继使用0.7标签；0.3仅作context input，旧8,863标签指标全部历史化 |
| P05 局部 Case 实体重叠与 test 过小 | 同一 Road 可跨 Case 出现，固定 test 5 案且不含标准 T10 | M1 entity guard、开发集 group CV、标准 T10 shadow holdout 与固定 test 分层 |
| P05 多任务目标不完整 | T03/T04 单点 bundle 可能只有输入，错误目录也不代表负类 | M2R task-target readiness audit、Unknown mask、grouped OOF；默认禁止以策略重放补真值，仅在用户明确授权、输入 manifest 精确匹配且 artifact lineage 完整时，允许在授权范围内将具有正式业务终态的策略重放结果作为人工确认真值，运行失败保持 `Unknown` |
| P05 通用约束夹带业务策略 | 最终 Road 可能被确定性逻辑共同决定 | 约束白名单、逐动作 intervention audit、事后内容修复为零 |
| P05 R2 oracle payload 泄漏 | 真值 edit/geometry 若进入输入会虚假提高生成效果 | oracle artifact 强制 `label_only=true`、feature role 白名单、泄漏 fixture 与 manifest audit |
| P05 R2 CREATE/SPLIT 稀有 | 表示虽完备但模型可能只学 COPY/DROP | 分 action macro-F1、每类 SPLIT recall、CREATE 单列、拓扑保持 crop 与现有真值重采样 |
| P05 ordinal slot-query 泛化失败 | 全局 scene pooling 与固定顺序 slot 容易学习 fold 内布局先验，不能把输出对象稳定匹配到输入 Road/Node | 停止继续增加当前架构 epoch；保留 R2 edit/pointer 语言，下一轮采用 object-conditioned cross-attention/bipartite matching 的 graph/set decoder，并复用同一 grouped OOF 门禁 |
| P05 PTO 策略候选被误当答案 | 历史策略重放可能恰好与 truth 相同，造成“模型已成功”的错误表述 | candidate/label 两阶段 manifest 隔离；策略仅作 proposal，P0 Oracle cost 仅证明可达，P1 grouped OOF 才评价 learned scorer |
| P05 PTO 候选爆炸或成本不可接受 | P0 候选与求解本身已满足预算，但全量 T03-T06 replay 实测 P95/max 超限 | P1 先消费冻结/缓存候选；并行实现轻量、缓存或增量 proposal generator，重新审计 replay CPU/RAM 与端到端 P95/max，禁止无界枚举 |
| P05 JSG 字段映射被误当业务真值 | 局部 T01/T06 字段转换可能固化错误本体 | 只使用已声明语义；保留 raw evidence，冲突进入 REVIEW/anomaly，不从局部样本反推上游强规则 |
| P05 JSG Oracle carrier 泄漏 | 精确编译可能被误称为推理或模型能力 | carrier realization 与 R2 IR 强制 label-only；P0 只证明本体/编译，候选层留到独立 JSG-P1 |
| P05 JSG 零实例类型虚假通过 | 51 Case 当前可能没有真实 loop 等对象 | 每类同时报告 observed/expressed/review/unexpressed；零实例只算 schema 支持，不算真实正例验证 |
| P05 JSG-P1 候选层伪装 truth | 从 P0 truth 复制对象或使用 truth 比较结果裁剪候选会使 reachability 虚高 | candidate config 不接受 truth path；manifest 先冻结，Oracle 后读取；破坏测试检查 truth/candidate hash 隔离 |
| P05 JSG-P1 候选爆炸 | Junction/Segment 任意全连接会使 PTO 不可执行 | 只在 T01 Segment、Junction 邻域和局部 access 生成有限 enum/Movement/Connector 候选，记录 unbounded-enumeration gate |
| P05 JSG-P2 fold/ID 泄漏 | 线性基线记住 Case/object/candidate ID 会伪造 OOF 泛化 | 复用 M0 business-ID fold；ID 只用于 join/audit，不进入 feature token；逐 fold train/held-out Case 与 forbidden-token audit 必须为零 |
| P05 JSG-P3 把 RoadGraph 100% 误称模型成功 | strategy proposal carrier 可掩盖 JSG 排序错误 | P3 以 JSG/Review 为主门禁，RoadGraph 只作 safety gate；3 seeds 均须通过 |
| P05 JSG-P3 上下文或 vocabulary 泄漏 held-out | 小 Case 数下会虚高 OOF | context 零 truth/ID；fold vocabulary、class weight、inner validation 只来自 outer train |
| P05 旧业务本体污染方案 A | 旧 SegmentConnector、PTO-A 或 Review 指标若继续进入当前合同，会让模型学习改写业务骨架 | 当前 source-of-truth 固定 T01 Segment/Junction/PhysicalMovement；旧 P0–P3 只读历史，current object type 中禁止 SegmentConnector |
| P05 fallback 扩大或伪成功 | 为提高自动化率可能把局部冲突扩大、或把不合法 SWSD 保留计成功 | 使用确定性最小依赖闭包；fallback 后重新验证独立 Road、引用、方向、CRS、拓扑和 lineage，不通过即 FAIL |
| P05 expected failure 被误当排除项 | 原始 SWSD 非法 Case若被移出分母，会虚高模型与异常指标 | 两个登记 Case保留在51 Case分母；只允许 RoadGraph 终态为 `EXPECTED_FAIL`，仍要求线索、禁止发布、确定性和全部模型指标 |
| P05 现实冲突被自动改结构 | 模型或约束可能把冲突解释成 Segment 增删改 | 只输出 RealityChangeClue 并失败/fallback；任何 skeleton mutation hard fail |

## 可接受技术债

- 当前保留 T00 / T02 历史支撑入口，以满足追溯和局部工具复用。
- P01 作为 POC / 成果模块存在，不进入 T09 正式契约。
- P02 作为武汉局部实验 POC / 成果模块存在；完整输入实验、人工关系和空兼容工件不得被误解释为全量 T07/T03/T04/T05 生产能力。
- P04 作为 Segment-first Road 直出 POC / 成果模块存在；Phase 0、第一/第二里程碑、冻结 Directional Road V2、High-Precision Road V3 及当前 Segment-first 单 Case 成果均不得被误解释为已实现生产能力。
- P05 当前采用方案 A，冻结骨架、策略基线、carrier-only 标签、RealityChangeClue 与 fallback 合同已完成；Scheme-A-P1 也已完成并判定 `P05_SCHEME_A_P1_MODEL_NO_GO`。P1 的对象级 Segment/Movement 指标和 RoadGraph 安全通过，但逐对象 truth 在整图 carrier 来源组合上不闭合，accepted coverage 仅 `0.3533~0.3637`，seed 29/43 anomaly precision 也未过门。下一阶段如启动，应先建设 JunctionUnit 级一致 carrier-set truth/candidate compatibility；旧 M1/M2R/R2/PTO/JSG-PTO 继续仅作历史实验，不得接入生产。
- 旧 `TEXT_QC_BUNDLE` 相关 CLI 入口保留为兼容工具，但不再作为正式协作协议。
- `docs/doc-governance/audits/` 保留历史审计材料，其中旧文件名和旧口径仅作追溯，不作为当前源事实。
- T06 当前同时保留 problem registry、visual check、topology audit 和 surface topology audit 多类质量证据；短期接受证据类型较多，后续应沉淀成更稳定的批量质量看板。

P05 新增的已关闭风险是“Dataset-P1 之前先做 Junction 真值闭包”：旧顺序让
context-only carrier 冲突级联为可靠 target 的错误 `KEEP_SWSD` 真值。P4 已以
scope-first 顺序消除该残余对象，并使三seed accepted wrong归零。仍未关闭的风险是
safe coverage与RealityChangeClue precision/recall跨seed/fold不稳定；不得把真值
修正 GO 误称为模型 GO，也不得继续使用 P2-P3-P3 的残余对象论证新表征必需。

P2-P3-P5 已通过同架构重训关闭“修正真值后仍有错误 carrier 自动发布”的风险：三 seed
accepted wrong 和 Review auto 均为 0，整图无新增冲突。仍未关闭的风险转为
“依赖大量 fallback 才能保持安全”和“clue 在不同 held-out 域中过报/漏报方向
不一致”。这两项不能靠挑 seed 或调当前阈值解决；下一研究阶段应先逐对象/逐 fold
归因，再决定新 truth-free 表征、模型结构或独立验证数据，且须另行授权。
## P05 P2-P3-P6 新增技术债

P6 关闭了“P5零错误自动接受”的错误解释：零错误只成立于final publication，
scorer层三seed各有1个稳定误选。当前技术债分为两条独立路线：fold clue threshold
从`0.000296`跨到`0.998983`，需要独立校准/abstention合同；稳定wrong的top-20训练
邻域全部为`USE_RCSD + clue=false`，需要新增T06前truth-free关系表征。只处理其中
一条不足以重启模型；RoadGraph原子阻断继续保留为最终安全门。

P2-P3-P7证明仅增加Case内compatibility聚合和T01相对几何仍不能关闭上述技术债，
排除Movement后结论也不变；单调calibration-only同样数学不可行。当前主要风险已
从“是否有足够Case”收敛为“现有合法推理来源不含决定性关系事实”。未经业务授权，
不得把T03/T04/T05/T06标签字段偷偷提升为输入；继续路线必须在T03/T04推理角色和
新确定性T06前关系生成器之间作显式选择。

P2-P3-P8将来源缺口进一步拆开：T03/T04的正式关系状态能修复当前已知carrier
邻域缺证据问题，但其适用范围只有504/6,275，且只覆盖1/6稳定Clue错误。主要风险
因此变为“把carrier局部正向结论误扩展成全局Clue或整体模型GO”。任何后续实验都
必须使用applicability mask、保留无来源fallback，并把carrier增益和Clue门分开
报告；未经字段级promotion批准，T03/T04仍不得进入推理。

P9已经证明隔离风险可控，但当前source adapter无效：它没有影响无来源对象或Clue，
也没有改变适用对象的carrier分类。剩余技术债是602维Control的错误logit已高度饱和，
而30.7K~31.1K参数的后置residual未学出足以改变候选排序的条件差异。不得以更多同构
epoch或扩大fallback重复该路线；若继续，应先独立评审joint conditioning、logit
校准/门控或更强的source-object交互，并保持P9 NO-GO基线。

P10进一步暴露标签风险：T10 Case级0.7不能被当作每个Segment的硬真值，否则会把
正确模型选择计为稳定错误。当前通过对象级1.0裁决、allowed/preferred分层和完整
lineage控制该风险。与此同时，事后裁决不能回流训练后重新评价同一held-out对象；
P10只读复算，任何新训练必须使用独立目标、重新冻结数据合同并单独授权。P9 NO-GO
现只表示adapter无严格增益，不再包含609对象不安全的归因。RCSD数据缺失与现实道路
结构冲突必须分离：前者默认安全`KEEP_SWSD`且`clue=false`，不得制造虚假变更线索。
