# 01 引言与目标

P05 当前研究目标 A 联合神经 RoadGraph 决策系统。它与正式规则链并行，在独立 POC 中先验证能否替代 T07/T03/T04/T05 路口业务，路口门通过后再验证 T06 Segment 业务；不修改或接入 T01–T12 正式实现/接口。

目标 A 冻结 T01 Junction—Segment、SegmentAccess 和 PhysicalMovement 存在性，T10 继续负责数据与编排。路口专用编码器直接读取原始 DriveZone/RCSDIntersection/SWSD/RCSD，依次输出 T07/T03/T04/T05 关键状态和完整锚定对象；路口阶段独立验收通过后，才训练普通 Segment 和 `ADVANCE_RIGHT`。旧 T07–T06 终态只作标签/验收；T07 Step1 只可见 DriveZone，第一版不启用 Movement、不接生产。普通提右仍是 `ADVANCE_RIGHT Segment`，当前业务层无 `SegmentConnector`。

M0 的架构目标是先建立可信数据与度量底座：限定 Case 范围、冻结真值权重、阻止切分泄漏、统一 Road/Node 质量评价，并把所有异常和 lineage 保留为可追溯证据。

M1 的架构目标是验证可学习性：从 T01/T05 候选 Road 与 T03/T04/T07 语义构建输入图，预测最终 Road 的保留、删除、1~3 子 Road 切分及属性/端点，再由无业务 fallback 的确定性物化器输出 Road/Node。固定 test 只在模型冻结后运行。

M2R 的架构目标是验证分层监督：共享编码器必须学习 T03、T04、T05、T06 任务，T07 作为可选辅助 Head，最终输出仍是 T06 Step3 语义 Road/Node。推理不运行 T03-T06 规则；free decoder 与通用图约束 decoder 共用模型 logits，后者只保证形式合法，不替模型决定 Road 业务内容。

R2 的架构目标是先解决 M2R `86.79%` 表示上限：Road/Node edit-set 必须通过 oracle 精确重建全部现有 truth，T05 改为精确 pointer，CREATE/SPLIT/端点/连接均进入显式生成合同。R2 已完成：Gate 1/2 通过，Gate 3 因当前 ordinal slot-query decoder 跨 Case 泛化失败而 no-go。T07 默认关闭，推理仍不运行 T03-T06 规则；下一轮需改用 object-conditioned graph/set decoder。

PTO-P0 已验证另一种分解在 51 Case 上语义成立：策略只产生高召回候选，未来神经网络只学习候选 cost，通用约束负责全局合法选择；Oracle cost 已证明候选可达性和 formulation。全链策略 replay 的 P95/max 超预算，因此 PTO-P1 先在冻结候选上训练 scorer，并行治理 proposal 成本。P0 不证明神经模型已成功。

2026-07-21 正式启动的 JSG-PTO-P0 已完成。它以 Junction—Segment—Movement 本体表达现实道路业务，再把 Road/Node 复杂性封闭到 Unit carrier 和 R2 edit 编译后端。P0 已证明 51 Case 的本体、Oracle 和 compiler，不训练模型、不接生产。

2026-07-22 授权的 JSG-PTO-P1 已完成：无 truth EvidenceGraph/candidate、PTO-A/PTO-B Oracle、双层约束和编译闭环在 51 Case 双跑通过。P1 未训练 scorer；历史 M1/M2R/R2/RoadGraph PTO 只作为基线证据。

JSG-PTO-P3 已完成并判定 `P3_MODEL_NO_GO`：candidate/context interaction neural scorer 将 held-out JSG Top-1 提升到 `0.9390~0.9395`，但 SegmentConnector 与 Review/Unknown 未达门槛；RoadGraph、约束、compiler、GIS、资源和确定性门禁通过。该结论现在只作为历史模型证据；旧 Connector/PTO-A 不得进入方案 A 当前本体和门禁。online proposal 与生产仍为 NO-GO。

Scheme-A-P2-P0 已完成并判定 upstream carrier NO-GO。它没有训练模型，冻结 Movement，把 Segment Road carrier 与 JunctionUnit shared Node carrier 分层；其 `USE_RCSD retention=0.165753` 保留为受限 carrier bundle 的历史联合安全保留率，不再解释为本地 Case 或正确 RCSD carrier 缺失。

Scheme-A-Dataset-P0 随后按模块职责证明现有51 Case并不缺少正确 carrier：2,190/2,190 `USE_RCSD` Segment 的目标 Road 由非 T01 truth-free candidate 可达，最终 Road/Node 与可用 Segment 联合 exact 均为 `1.0`，正式结论 `P05_SCHEME_A_DATASET_P0_GO`。该结论只覆盖离线数据与候选可达性，不包含 scorer 或在线性能。

Scheme-A-P2-P1已完成并判定`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`。全量多来源Segment/Node候选、Road来源条件化Node和49+2整图安全已走通，但每seed仍有9~17个错误接受，coverage/anomaly/Review稳定性未达到离线GO；当前模型只保留离线排序与研究证据。

Scheme-A-P2-P2-P0已完成并判定`P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO`。错误根审计把对象级17/9/17收敛为accepted Segment根错误2/0/3；单一阈值零错误USE覆盖最多20.03%，但现有完整truth-free feature无跨truth精确碰撞。后续Scheme-A-P2-P2-P1已完成独立Segment safety head验证并判定`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`：零错误seed覆盖仅约7%，较高覆盖seed仍接受4~5个错误；Node条件化与49+2 RoadGraph安全门通过。当前无可自动发布神经模型。

Scheme-A-P2-P2-P2-P0随后完成202维合法推理证据审计并判定`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`。浅层MLP虽然在全局阻断全部9个一致错误proposal和40 Review，但unsafe recall仍为0.994191，且0/5 held-out fold同时满足完整recall和两个50%覆盖门。该结果确认当前瓶颈是跨Case可观测证据不足，而不是Node/RoadGraph闭包失败。

Scheme-A-P2-P2-P2-P1随后对9个一致错误、13个残留unsafe accepted和40 Review完成逐对象直接归因并判定`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`。40 Review已由T01 access硬门解释；其余22个对象的直接事实只存在于label-only T06/联合真值层。完全不可观测为0，但当前新增获准推理证据为0，因此不启动训练。

Scheme-A-P2-P2-P2-P2进一步将Road/Carrier安全和RealityChangeClue可见性分开。13个残留对象均为正确KEEP后的clue漏报；22/22正确候选可达，26个初始Node payload冲突与57个Junction fallback Segment确定性复现。但现有浅层MLP仅2/5 fold通过覆盖门，因此结论为`PARTIAL_ROUTE_NO_MODEL_GO`：分层路线成立，现有模型不放行。

Scheme-A-P2-P3-P0已将该分层路线实现为2.818M参数多任务模型和固定Node/Junction decoder。三个seed均生成49 `LEGAL`+2 `EXPECTED_FAIL`且无冲突、错配或额外repair；但carrier错误接受、fold 2低覆盖和clue跨seed校准不稳定仍使业务门失败，正式结论为`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`。

Scheme-A-P2-P3-P1已完成只读失败归因与证据库存审计。稳定误接受和13个clue-only的直接事实仍只存在于label-only Junction/T06 final层，现有合法推理证据无新增直接事实；51个端到端Case已全部用于OOF，其余POC_Data包不构成独立冻结RoadGraph验证集。正式结论为`P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`，当前不启动下一轮模型训练。

Scheme-A-Dataset-P1 随后修正了旧标签范围：T10 为全 Case真值，Segment 包只标
manifest target ID或精确 Road partition 后继，其余只作上下文。正式结果为
6,275 label + 2,588 context、上下文标签泄漏 0；expected-failure 保持 Case
不发布，但不再级联屏蔽其它 Segment scorer。`P05_SCHEME_A_DATASET_P1_GO`
只放行新标签合同，旧模型指标须重训/重评。

Scheme-A-P2-P3-P2随后在该合同上从头重训同一2.818M级模型。6,275个eligible
对象进入监督/指标，2,588个context-only对象固定回退；每seed整图仍为49
`LEGAL`+2 `EXPECTED_FAIL`。但accepted wrong=`1/13/0`、Review auto=`0/12/0`，
零错误seed的总体/USE coverage仅`0.1506/0.2757`，正式结论为
`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`。这证明标签修正必要但不充分，当前目标仍是
研究安全scorer，不是自动发布。

Scheme-A-P2-P3-P3进一步把冻结`ADVANCE_RIGHT access_valid=false`作为独立硬
安全资格。40个Review精确命中、非Review零误触发，Review auto降为0且49+2不变；
剩余false-use三个seed仍大margin选错，60/60 held-out近邻均为`USE_RCSD`。
因此本阶段完成的是安全层GO，不是scorer GO；下一研究目标是T06前的新关系表征。

Scheme-A-P2-P3-P4随后证明上述“新关系表征”目标建立在错误真值闭包顺序上。
Dataset-P1 scope-first 后，唯一残余对象恢复为正确USE真值，三seed accepted wrong
归零。当前目标改为先冻结正确标签层；模型仍因coverage/clue稳定性NO-GO，只有
另行授权后才能按新真值重训/复验。

Scheme-A-P2-P3-P5 已完成该复验并判定
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。P6确认final publication wrong为0，但
scorer decision wrong accepted=`1/1/1`；整图49+2安全门拦截了错误，不能反向解释
为模型判断正确。三个seed的clue门均失败，逐fold也未闭合。

Scheme-A-P2-P3-P6 已完成只读归因并判定
`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`。下一技术目标需同时
解决clue calibration和T06前truth-free表征；当前模块仍只具备安全、可解释的
离线研究能力，不具备自动替换SWSD或生产接入条件。

Scheme-A-P2-P3-P7 已完成并判定
`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`。602维Movement-free关系/几何
表征和独立clue校准合同均已完成可信审计，但稳定wrong的训练邻域与单调校准门仍
失败。当前合法来源不支持下一轮训练；模块继续保持离线研究和安全fallback定位。

Scheme-A-P2-P3-P8 已完成并判定
`P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`。T03/T04
正式T05 handoff对稳定carrier wrong提供了跨Case正确同类证据，但稳定Clue错误覆盖
仅`1/6`。模块当前只获得carrier来源promotion二次评审理由，不具备完整新训练阶段
或自动发布授权。

P9已完成并判定`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`。T03/T04白名单只进入
carrier branch、Clue和无来源对象不受影响的隔离目标已经达成，但adapter没有纠正
稳定错误或提高适用对象分类。后续不延续同构adapter训练，需重新授权技术目标。

P10按用户对象级人工裁决对冻结P9输出复算。609对象的`USE_RCSD`被确认正确，旧稳定
错误归因失效；集合真值下两臂合法准确率均为1.0、三seed错误自动接受均为0。但
Control/Treatment仍无严格增益，故P9 adapter继续NO-GO。另两条RCSD数据缺失对象
确认不属于现实道路结构冲突，稳定Clue漏报归零；Clue误报与冻结coverage仍阻断完整
模型。

P12R已把提右从旧T05锚定目标中移出，并按“普通Segment先替换、提右后条件化实现”
重建474个`ADVANCE_RIGHT Segment`。业务、安全、GIS和双跑门均通过；候选总体召回
为`0.952020`，但T10:706247 fold仅`0.875`，故当前目标收敛为补强
Road endpoint/JunctionUnit条件化RCSD提右候选，而不是训练scorer或增加样本。

P12R-R1已完成上述候选补强并判定
`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`。在不改变业务骨架、不读取T05提右
标签或T06终态推理事实的前提下，候选总体recall提升到`0.979798`，最差fold提升到
`0.916667`且无fold退化。当前候选可达性不再阻断下一阶段技术讨论，但模型排序、
拒识和整图安全仍需独立训练与验收授权。

P13-P0已完成该训练并判定
`P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO`。480,739参数集合模型的raw
exact-set为`0.646907`，低于5m Local Control的`0.680412`；安全层仍有14次unsafe
RCSD发布。当前目标不再是扩大候选或继续同构调参，而是先确认相邻普通Segment的
OOF soft carrier状态能否作为合法joint-conditioning证据。
