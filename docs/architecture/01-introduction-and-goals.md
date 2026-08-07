# 01 引言与目标

## 文档定位

本文档说明项目级架构目标与边界。模块生命周期、模块业务说明和文档结构盘点分别由 `docs/doc-governance/module-lifecycle.md`、`docs/doc-governance/current-module-inventory.md`、`docs/doc-governance/current-doc-inventory.md` 承载。

## 架构目标

- 支撑 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09` 主业务链的持续治理。
- T10 审计编排在 T06 后、T09 前固定执行 T11 candidate extraction；可显式在 T11 后、T09 前运行 T12 原始 1V1 F-RCSD 质检，默认关闭，两者都不改变主业务数据链。T10 同时提供跳过 T08、固定启用 T12 的 F-RCSD 质量检查专用流水线。
- 沉淀 SWSD、RCSD、F-RCSD、语义路口、Segment、字段语义等跨模块共用信息。
- 保持项目级架构、文档治理、仓库元数据、模块契约职责分离。
- 保证 GIS / 拓扑 / 空间数据处理结果可解释、可审计、可复现、可验证。
- 为 P05 Target A 提供与正式主链隔离的冻结 T01 Junction—Segment、SegmentAccess 和 PhysicalMovement 存在性，以及原始 DriveZone/RCSDIntersection/SWSD/RCSD、分层标签、`RealityChangeClue` 和最小闭包 fallback。联合神经系统先替代 T07/T03/T04/T05 语义路口业务，独立通过后再负责普通 Segment、条件化 `ADVANCE_RIGHT` 和证据/作用域判断，但不能改写冻结业务骨架。
- P05 的 M1/M2R/R2/RoadGraph PTO-P0 与 JSG-PTO-P0/P1/P2/P3 全部作为历史实验保留。旧 `SegmentConnector`、PTO-A 结构选择及 Connector/Review 指标不再定义当前业务本体或门禁；旧结果只证明相应历史模型、候选、编译与资源事实。
- P05 Target A 不替代 T01、T09 或 T10，不修改 T01–T12 正式实现与接口，也不进入生产；在其离线推理链内，旧 T07–T06 业务策略完全退出，相关终态只作训练标签和评价。T07 Step1 仍只允许 DriveZone，RCSDIntersection 从模型内 Step2 才可见。现实证据冲突由模型输出线索、影响对象和显式有限 fallback 作用域；确定性层只校验并执行，不作传递闭包；第一版 Movement 不启用。
- P05-Scheme-A-P2-P0 已完成：Movement 冻结，Segment Road 与 JunctionUnit shared Node carrier 已分层；其 `USE_RCSD retention=0.165753` 保留为受限 carrier bundle 的历史联合安全保留指标，不再解释为本地 Case 或正确 RCSD carrier 缺失。
- P05-Scheme-A-Dataset-P0 已完成：按模块职责整理 741 sample、520 artifact、11,856 task target、51 Case 和 8,863 Segment；2,190 个 `USE_RCSD` Segment 的正确 Road 均由非 T01 truth-free candidate 可达，最终 Road/Node 与可用 Segment 联合可达率均为 `1.0`，正式结论 `P05_SCHEME_A_DATASET_P0_GO`。该 GO 只覆盖离线数据和候选可达性。
- P05-Scheme-A-P2-P1已于2026-07-23完成并判定`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`：条件化Node与49+2安全目标通过，但零错误自动替换、总体/`USE_RCSD` coverage、异常precision和seed43 Segment稳定性未通过；当前无可发布模型。
- P05-Scheme-A-P2-P2-P2-P0已于2026-07-23完成并判定`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`：202维合法truth-free结构证据完整覆盖9个一致错误proposal和40 Review，但线性probe仍放过2个错误，浅层MLP虽全局零错误却未在任何held-out fold同时达到unsafe recall=`1.0`和两个50%覆盖门；Node/RoadGraph继续49+2安全通过。当前只保留离线review价值。
- P05-Scheme-A-P2-P2-P2-P1已于2026-07-23完成并判定`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`：62个重点对象全部完成直接归因，40 Review已有T01 access硬门，剩余22个对象只由当前label-only T06/联合真值直接解释；完全不可观测为0，但新增获准推理证据为0，当前不得继续训练或直接提升T06终态事实。
- P05-Scheme-A-P2-P2-P2-P2已于2026-07-23完成并判定`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`：旧 unsafe 指标中13个浅层MLP残留对象实际均为carrier正确、clue漏报；carrier safety全局通过，但cross-case只有2/5 fold达到覆盖门。22/22正确候选可达且26→57 Junction闭包可复现，说明下一研究目标应为分层carrier/clue/Junction架构，而不是补Case或继续扩大同一浅层模型。
- P05-Scheme-A-P2-P3-P0已于2026-07-23完成并判定`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`：2.818M分层模型与通用Node/Junction decoder均已实现，三个seed的整图均为49 `LEGAL`+2 `EXPECTED_FAIL`且无冲突/repair；但carrier仍有`1/1/0`个错误自动接受、fold 2覆盖稳定低于门槛，clue在漏报与过报之间不稳定。当前成果证明合法RoadGraph生成链路成立，不证明业务carrier/clue已可自动发布。
- P05-Scheme-A-P2-P3-P1已于2026-07-23完成并判定`P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`：稳定误接受和13个clue-only对象已逐对象归因，当前合法推理证据没有新增直接事实，现有POC_Data也没有独立冻结的未使用端到端验证集。fold 2低coverage还包含1,795个expected baseline failure造成的分母不可达问题；在重新确认该业务度量并补足证据/验证合同前，不重启模型训练。
- P05-Scheme-A-Dataset-P1已于2026-07-23完成并判定`P05_SCHEME_A_DATASET_P1_GO`：T10 Case truth与T10-Error/T10-Error-2 target-only truth已分离，45个Segment包全部完成direct ID或Road partition lineage；8,863个当前Segment被重建为6,275个标签对象和2,588个纯上下文对象。两个expected-failure Case只阻断整图发布并局部作用于`failure_group_ids`，不再级联屏蔽全Case scorer对象。旧8,863标签分母下的模型指标保留为历史旧口径，未经Dataset-P1重训/重评不得继续作为当前结论。
- P05-Scheme-A-P2-P3-P2已于2026-07-23完成并判定`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`：同一2.818M级分层模型只用6,275个Dataset-P1 eligible标签从头重训，2,588个context-only对象全部安全回退。整图每seed仍为49 `LEGAL`+2 `EXPECTED_FAIL`且无级联/冲突，但carrier accepted wrong=`1/13/0`、Review auto=`0/12/0`，零错误seed的总体/USE coverage仅`0.1506/0.2757`。标签修正排除了旧上下文污染，却没有解决当前scorer的安全校准和Review跨Case泛化；不得挑seed、继续在已见held-out调阈值或自动发布。
- P05-Scheme-A-P2-P3-P3已于2026-07-23完成并判定`P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED`：40个`ADVANCE_RIGHT access_valid=false`硬门精确消除Review自动接受，最终wrong=`1/1/0`且49+2整图不变；剩余可靠false-use在三个seed及60个held-out近邻中均稳定落入`USE_RCSD`区域。Review安全资格已走通，下一目标转为建设T06前的新推理表征，而不是继续训练/调阈值同一202维表征。

## 非目标

- 不在 architecture 中重复模块内部 Step、参数、阈值、入口和验收细节。
- 不承载目录白名单、入口登记、文件体量等仓库技术元数据。
- 不维护阅读顺序、文档职责完整表或模块生命周期事实。
- 不替代 `modules/<module>/architecture/*` 与 `modules/<module>/INTERFACE_CONTRACT.md`。

## 结构

| 文档 | 职责 |
|---|---|
| `01-introduction-and-goals.md` | 架构目标、非目标和职责边界 |
| `02-data-and-domain-model.md` | 全局业务概念、数据对象、字段语义和术语 |
| `03-solution-strategy.md` | 跨模块主方案与 POC 边界 |
| `04-evidence-and-audit.md` | 文件证据包、summary/audit/review 与内外网信息反哺 |
| `05-quality-requirements.md` | CRS、拓扑、几何、审计、性能和契约质量要求 |
| `06-risks-and-technical-debt.md` | 项目级架构风险和技术债 |

## P05 P2-P3-P4 目标校正

Dataset-P1 标签资格必须先于 Node/Junction 真值闭包。P4 证明此前唯一残余
false-use 来自 context-only Segment 过早参与闭包，不再构成新关系表征的启动理由。
该历史 P2-P3-P4 阶段仍以安全和准确性优先；其模型因 coverage/clue 稳定性
继续 NO-GO。该结论保留追溯，但不再限制已获授权的 Target A 联合模型范围。

## P05 P2-P3-P5 完成结论

scope-first 修正真值下的同架构重训已完成，正式结论为
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。P6 后续把结果拆成 scorer 与 final
publication 两层：scorer wrong accepted=`1/1/1`，RoadGraph 原子阻断后 wrong
published=`0/0/0`；前者表示模型仍会误选，后者表示整图安全链路能够拦截。safe
coverage 与 RealityChangeClue 仍未逐 seed、逐 fold 同时通过。项目级结论是
“整图安全链路成立、当前自动化模型未通过”，不授权生产接入或自动替换 SWSD。

## P05 P2-P3-P6 完成结论

只读双层归因已完成，正式结论为
`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`。证据同时证明：
clue threshold 跨 fold 严重漂移，且稳定 carrier wrong 位于错误的202维训练邻域。
下一路线必须同时处理 clue calibration 与 T06 前 truth-free 表征；P6 GO不表示
P5模型GO，也不授权训练或生产接入。

## P05 P2-P3-P7 完成结论

P2-P3-P7 已完成并判定
`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`。用户批准从历史202维中剔除14个
实际非零Movement命名维及28个邻域派生维；P7以188维无Movement基础证据、
377维Case内compatibility邻域和37维T01相对几何形成602维表征。来源、审计、
确定性与资源门通过，但稳定wrong的新top-20训练邻域仍全部为
`USE_RCSD + clue=false`，三个seed的单调clue校准均无法过门。当前目标不是继续
训练，而是先决定是否扩大合法T06前推理来源。

## P05 P2-P3-P8 完成结论

P2-P3-P8 已完成并判定
`P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`。T03/T04
正式T05 handoff可在冻结T01 Junction—Segment关系下为carrier误选提供新增软证据，
但对6个稳定Clue错误仅覆盖1个。该阶段只证明“carrier来源值得字段级二次评审”，
不表示T03/T04整体转为模型输入，也不授权训练、自动替换SWSD或生产接入。

P9已完成严格A/B并判定`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`：
无来源、Clue、冻结骨架、fallback和RoadGraph边界全部保持，但source adapter没有
改变504个适用对象的分类指标，也未纠正三seed稳定错误。该结果关闭当前adapter方案，
不关闭神经carrier研究整体；新一轮模型或训练需独立目标与授权。

P10按后续对象级人工审计重新解释P9：`609214532 / 505101583_506183080`的
`USE_RCSD`实际正确，旧“稳定错误”是T10 Case级0.7标签误判。集合真值复算后
Control/Treatment合法准确率均为1.0、三seed错误自动接受均为0；但两臂仍无任何严格
增益，因此当前adapter方案NO-GO只保留“没有增量价值”的含义，不再解释为模型在该
对象上不安全。另两个对象确认“RCSD数据缺失但道路结构不冲突”，因此应
`KEEP_SWSD + RealityChangeClue=false`；修正后稳定Clue漏报归零，但Clue误报与冻结
coverage门仍未通过完整模型门。
