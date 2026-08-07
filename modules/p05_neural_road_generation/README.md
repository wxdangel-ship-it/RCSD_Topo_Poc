# P05 神经网络 F-RCSD Road 直出 POC

## 当前目标 A

P05 当前冻结 T01 Junction—Segment、SegmentAccess 和 PhysicalMovement 存在性，T10 继续负责数据与编排。联合神经系统先直接读取原始 DriveZone、RCSDIntersection 和 SWSD/RCSD Road/Node，按 Step1 DriveZone-only → Step2 existing surface → T03/T04 → T05 的业务顺序完成语义路口判断；路口阶段独立通过后，才允许训练普通 Segment 完整 Road/Node 方案、条件化 `ADVANCE_RIGHT`、`RealityChangeClue` 与 fallback 作用域，并由约束 RoadGraph decoder 联合选择。fallback 不采用通用冲突传递闭包：Segment 级只回退自身并止于 Junction，Junction 级只覆盖模型明确列出且经冻结 T01 验证的直接关联 Segment，并止于这些 Segment；所有权联合求解不得扩大作用域，T01 依赖图只作 encoder 上下文。旧 T07–T06 终态只作标签与验收，退出目标 A 推理链；确定性层只执行几何/Node 写出、已确定 fallback 和通用图合法性，不重作业务判断。普通提右是 `segment_type=ADVANCE_RIGHT` 的 Segment，必须有独立 Road，可包含真实 `junc_nodes`；当前业务层不使用 `SegmentConnector`。第一版不启用 Movement、不接生产，也不修改 T01–T12 正式实现或接口。

截至 2026-07-31，v388r1/v389 已形成第一版 recall-first 端到端研究基线：外层 fold1 对 143/143 个提右强制输出，Road top-1=`86/106=0.811321`，需要几何动作的 top-1 complete exact=`30/67=0.447761`，Road+几何联合 top-1=`33/77=0.428571`；Road 与几何 beam 均为 16 时联合正确方案 `77/77` 可达。该结果只证明模型可以稳定出结果并保住正确方案，不代表最终 Node/方向/拓扑和 RoadGraph 已正确物化。v390 的平面组合 decoder 使 top-1 降至 `32/77`，已判定 NO_GO；下一步分别收敛 Road cardinality/完整成员和分类型几何 top-1，不再扩候选或评估 beam。

[P05-Scheme-A-Dataset-P0](../../specs/p05-scheme-a-dataset-p0-module-semantic-reachability-20260722/) 已完成并判定 `P05_SCHEME_A_DATASET_P0_GO`：在不增加 Case 的前提下，741 sample、520 artifact、11,856 task target、51 Case 和 8,863 Segment 已按模块业务语义重新归档；T01 只作 SWSD 冻结骨架/fallback，T07 固定 `DRIVEZONE_ONLY`，T03/T04/T05 是中间监督，T06 Road/Node 是最终标签。`USE_RCSD` 的非 T01 候选覆盖为 `2190/2190`，可用 Segment、最终 Road/Node 与联合 exact 均为 `100%`。这证明现有 Case 数据与离线候选足够进入 scorer 方案设计；不等于 scorer 已训练，也不等于在线 proposal 性能或生产接入已通过。

[P05-Scheme-A-P2-P1](../../specs/p05-scheme-a-p2-p1-object-conditioned-junction-carrier-scorer-20260723/) 已于2026-07-23完成并判定 `P05_SCHEME_A_P2_P1_SAFETY_NO_GO`。Road endpoint/JunctionUnit条件化使Node exact达到`0.9965~0.9985`，三个seed均保持49+2；但每seed仍有`9~17`个错误自动接受，`USE_RCSD` safe coverage最高仅`0.2658`，异常precision低于`0.40`。因此模型仅保留离线排序/review研究价值，不允许自动替换、在线proposal或生产接入。

[P05-Scheme-A-P2-P2-P0](../../specs/p05-scheme-a-p2-p2-p0-safety-separability-audit-20260723/) 已完成并判定 `P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO`。只读审计把对象级错误接受分解为真正accepted Segment根错误`2/0/3`及Node传播/fallback口径；单一阈值在零错误下最多保留`20.03%`正确USE，但完整现有feature无跨truth精确碰撞。其建议的独立Segment safety head 后续已在 P2-P2-P1 完成验证。

[P05-Scheme-A-P2-P2-P1](../../specs/p05-scheme-a-p2-p2-p1-segment-safety-head-20260723/) 已完成并判定 `P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`。独立 Segment safety head 已按 3 seeds × 5 Case folds 训练，但零错误 seed 的总体/USE 覆盖只有约`7%/7%`，另两 seed 提高覆盖后仍接受`5/4`个错误；因此不允许自动替换 SWSD。Node 条件化和49+2 RoadGraph安全门全部通过，当前模型只保留离线排序/review研究价值。

[P05-Scheme-A-P2-P2-P2-P0](../../specs/p05-scheme-a-p2-p2-p2-p0-safety-evidence-audit-20260723/) 已完成并判定 `P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`。202维合法推理证据完整覆盖9个一致错误proposal和40 Review；线性probe仍放过2个错误，浅层MLP全局零错误但0/5 held-out fold通过完整recall/coverage门。两种probe的Node条件化和49+2 RoadGraph安全门全部通过。当前不得在同一证据和已见Case上继续调参，只保留离线Review/异常辅助价值。

[P05-Scheme-A-P2-P2-P2-P1](../../specs/p05-scheme-a-p2-p2-p2-p1-missing-evidence-attribution-20260723/) 已完成并判定 `P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`。9 个一致错误、13 个残留 unsafe accepted 与 40 Review 合并后的 62 个对象已全部直接归因：40 个 Review 已有 T01 access 硬门；剩余 22 个对象只由当前 label-only 的 T06/联合真值直接解释，完全不可观测为 0，但新增获准推理证据仍为 0。P2-P1 joint fallback 只保留辅助线索角色；不得直接提升 T06 终态事实或启动下一轮训练。

[P05-Scheme-A-P2-P2-P2-P2](../../specs/p05-scheme-a-p2-p2-p2-p2-pre-t06-source-contract-audit-20260723/) 已完成并判定 `P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`。13 个旧 residual unsafe 已重解释为 carrier 正确、clue 漏报；22/22 正确候选与 Pre-T06 分层监督路线均存在，26→57 Junction 闭包确定性通过，但现有浅层 MLP 只有 2/5 fold 达到完整安全/覆盖门。下一模型应分开 carrier、clue 和 Junction consistency；本阶段未授权训练或提升 T03–T06 推理角色。

[P05-Scheme-A-P2-P3-P0](../../specs/p05-scheme-a-p2-p3-p0-hierarchical-carrier-clue-junction-model-20260723/) 已完成并判定 `P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`。2.818M 分层模型和通用 Node/Junction decoder 已完整实现，三 seed 整图均为 49 `LEGAL` + 2 `EXPECTED_FAIL` 且无 conflict/repair；但 carrier 仍有 `1/1/0` 个错误自动接受，fold 2 三 seed覆盖稳定约 `0.29`，clue-only 只捕获 `9/8/12`。当前证明的是“合法整图生成链路成立、业务自动发布能力未通过”，不得在已见 held-out 上继续调阈值或挑 seed。

[P05-Scheme-A-P2-P3-P1](../../specs/p05-scheme-a-p2-p3-p1-failure-attribution-inference-evidence-audit-20260723/) 已完成并判定 `P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`。稳定 false-use 与 13 个 clue-only 已逐对象归因，当前允许的 T01/T07/truth-free proposal/compatibility 证据没有新增直接事实；POC_Data 也没有独立冻结的未使用端到端验证集。fold 2 中 1,795/3,037 个 expected baseline failure 还使全分母 50% coverage 数学不可达。当前先不重训模型；下一步需业务确认 coverage 分母，并另行建设新推理表征或验证合同。

[P05-Scheme-A-P1](../../specs/p05-scheme-a-p1-object-conditioned-carrier-scorer-20260722/) 已完成并判定 `P05_SCHEME_A_P1_MODEL_NO_GO`：对象级 scorer 的 Segment/Movement 能力很强且 RoadGraph 安全门通过，但三 seed accepted coverage 只有 `0.3533~0.3637`，当前逐对象 carrier truth 无法在整图组合时达到 50% 自动接受覆盖率。P1 未修改 T01–T12、不接生产；后续如启动应先建设 JunctionUnit 级一致 carrier-set truth，而不是直接扩大同一模型。

`P05-Scheme-A-P2-P0` 的历史 `USE_RCSD retention=0.165753` 现在只解释为当时受限 carrier bundle 的联合安全保留率，不再解释为 T01/proposal 数据中缺少正确 RCSD carrier。Dataset-P0 已使用模块职责正确的分母证明正确 carrier 可达；旧 P2-P0 run 和 NO-GO 仍完整保留。

## 历史实验

P05 用于验证神经网络能否从基础地图证据直接生成符合 T06 Step3 语义的 F-RCSD Road/Node。R2 已完成：Road/Node `COPY/UPDATE/SPLIT/CREATE/DROP` edit-set 与精确 T05 pointer 在 51 Case 上达到 `100%` 可表达和精确重建，40.19M 联合模型也通过 small-batch 门禁；但 grouped 5-fold OOF 的最终 Road F1=`0`、Node F1≈`0.0001`，因此当前 ordinal slot-query 基础模型正式 **NO-GO**。T07 默认关闭，推理未执行 T03-T06 业务规则。

M2R 结论为 **当前表示与基础模型 no-go**：OOF Road F1 `0.64653`、最差 Case `0.2466`、51/51 Case 有有向拓扑 hard failure；但 18.32M 模型各必选 Head small-batch 均达到 `0.95`，所以 R2 处理的是表示与生成结构问题，不是放宽门槛或简单增大模型。

R2 将表示问题排除后，进一步定位出模型结构问题：训练 loss 持续下降，但 10 epoch 到累计 40 epoch 的 held-out RoadGraph 指标没有实质改善。当前模型用全局 scene pooling 加 ordinal slot embedding 生成对象，缺少每个输出/edit/pointer query 与输入 Road/Node 实体之间的匹配机制。若继续 POC，应保留 R2 表示、数据和评价合同，改用带 object cross-attention/bipartite matching 的 graph/set decoder；当前不优先要求用户补更多 Case。

PTO-P0 已完成：登记 commit 的 T03-T06 策略重放只从 raw/T01 生成有限候选，候选 artifact 先冻结并哈希；随后 label-only Oracle cost 在 51 Case 上证明全部 truth 可达，通用图约束均以 `OPTIMAL/gap=0` 精确选出 RoadGraph。语义门禁通过，但含策略 replay 的端到端 P95/max 超过预算。P0 没有训练 scorer；PTO-P1 只允许先使用冻结/缓存候选进行 object-conditioned learned scoring，当前在线全链和生产接入仍为 NO-GO。

`P05-JSG-PTO-P0` 已完成。Junction、StandardSegment、Junction—Segment relation、PhysicalMovement、SegmentConnector、Terminal 与 loop 已固化为 canonical JSG truth；`JSG -> carrier realization -> R2 edit IR -> Road/Node` 在 51 Case 上完成双跑验证。P0 不训练模型、不生成推理候选、不修改 T01-T09 接口，也不进入生产主链；其 GO 不等于模型泛化或生产 GO。

`P05-JSG-PTO-P1` 已完成。P1 从 truth-free EvidenceGraph 生成有限 JSG/PTO-B 候选，candidate manifest 冻结后才使用 P0 truth 计算 Oracle cost，并已通过 PTO-A 业务结构、PTO-B carrier/RoadGraph edit、编译和双跑确定性门禁。M1/M2R/R2/RoadGraph PTO-P0 只保留为历史实验结论；P1 未训练 scorer。

`P05-JSG-PTO-P3` 已完成。正式 51 Case、3 seeds × 5 folds 中，object-conditioned scorer 的 JSG Top-1/macro 为 `0.9390~0.9395 / 0.8471~0.8817`，显著优于 P2；但 SegmentConnector 与 Review/Unknown 未达主门禁，正式判定 `P3_MODEL_NO_GO`。PTO-A/PTO-B、RoadGraph、GIS、资源与确定性门禁通过；结论指向 inference 输入的 carrier evidence 缺口。后续阶段和生产接入均未授权。

## 文档入口

- [SPEC.md](SPEC.md)：业务需求、范围和验收标准。
- [INTERFACE_CONTRACT.md](INTERFACE_CONTRACT.md)：M0 callable、输入和输出契约。
- [architecture/](architecture/)：数据模型、方案、审计、质量和风险。
- [M0 SpecKit 工件](../../specs/p05-neural-frcsd-m0-20260721/)：数据与度量底座。
- [M1 SpecKit 工件](../../specs/p05-neural-frcsd-m1-20260721/)：模型实验、验证证据和 M2 no-go 结论。
- [M2R SpecKit 工件](../../specs/p05-neural-frcsd-m2r-20260721/)：分层监督、联合模型、双解码和 OOF 验收。
- [R2 SpecKit 工件](../../specs/p05-neural-frcsd-r2-20260721/)：可完备 graph edit、精确 pointer、oracle 门禁和新一轮模型/OOF 验收。
- [PTO-P0 SpecKit 工件](../../specs/p05-pto-p0-candidate-oracle-20260721/)：无 truth 候选、Oracle cost、通用约束求解和 51 Case 门禁。
- [JSG-PTO-P0 SpecKit 工件](../../specs/p05-jsg-pto-p0-ontology-oracle-compiler-20260721/)：JSG 本体、51 Case Oracle、evaluator 与 Road/Node compiler 证明。
- [JSG-PTO-P1 SpecKit 工件](../../specs/p05-jsg-pto-p1-candidate-oracle-20260722/)：无 truth 候选、PTO-A/PTO-B Oracle、物化与确定性证明。
- [JSG-PTO-P2 SpecKit 工件](../../specs/p05-jsg-pto-p2-explainable-scoring-20260722/)：V0/V1 可解释评分、grouped OOF、PTO 与 RoadGraph 验收。
- [JSG-PTO-P3 SpecKit 工件](../../specs/p05-jsg-pto-p3-object-conditioned-scorer-20260722/)：object-conditioned neural scorer、3 seeds × 5 folds 与 JSG/Review 主门禁。
- [方案 A Carrier 基线 SpecKit](../../specs/p05-scheme-a-carrier-baseline-20260722/)：冻结骨架、策略基线、carrier-only 标签、RealityChangeClue 与 fallback。
- [P05-Scheme-A-P1 SpecKit](../../specs/p05-scheme-a-p1-object-conditioned-carrier-scorer-20260722/)：零 truth carrier candidate、object-conditioned scorer、OOF、fallback 与 RoadGraph 安全验收。
- [P05-Scheme-A-Dataset-P0 SpecKit](../../specs/p05-scheme-a-dataset-p0-module-semantic-reachability-20260722/)：模块语义化训练合同、非 T01 carrier 可达性、49+2 安全与双跑验收。
- [P05-Scheme-A-P2-P1 SpecKit](../../specs/p05-scheme-a-p2-p1-object-conditioned-junction-carrier-scorer-20260723/)：Segment/Node联合candidate、object-conditioned scorer、3 seeds × 5 folds和整图安全验收。
- [P05-Scheme-A-P2-P2-P0 SpecKit](../../specs/p05-scheme-a-p2-p2-p0-safety-separability-audit-20260723/)：accepted-wrong错误链、Review、feature collision和安全可分性审计。
- [P05-Scheme-A-P2-P2-P1 SpecKit](../../specs/p05-scheme-a-p2-p2-p1-segment-safety-head-20260723/)：Segment-only safety/abstention head、嵌套 Case cross-fit、Node 条件化闭包与整图安全验收。
- [P05-Scheme-A-P2-P2-P2-P0 SpecKit](../../specs/p05-scheme-a-p2-p2-p2-p0-safety-evidence-audit-20260723/)：T01/T07/proposal/compatibility 增量证据、线性/浅层probe、逐fold安全门与49+2整图验收。
- [P05-Scheme-A-P2-P2-P2-P1 SpecKit](../../specs/p05-scheme-a-p2-p2-p2-p1-missing-evidence-attribution-20260723/)：9 error、残留 unsafe 与 40 Review 的逐对象直接归因、源事实边界和确定性审计。
- [P05-Scheme-A-P2-P2-P2-P2 SpecKit](../../specs/p05-scheme-a-p2-p2-p2-p2-pre-t06-source-contract-audit-20260723/)：carrier safety/clue visibility 双指标、22 对象 candidate/source route 与 Junction 闭包审计。
- [P05-Scheme-A-P2-P3-P0 SpecKit](../../specs/p05-scheme-a-p2-p3-p0-hierarchical-carrier-clue-junction-model-20260723/)：2.818M 分层 carrier/clue/auxiliary 模型、3×5 OOF、通用 Junction decoder 与 49+2 整图验收。
- [P05-Scheme-A-P2-P3-P1 SpecKit](../../specs/p05-scheme-a-p2-p3-p1-failure-attribution-inference-evidence-audit-20260723/)：稳定误接受、fold 2、clue-only、字段角色和独立验证库存的只读双跑审计。

## 当前边界

- 目标语义固定为 T06 Step3 F-RCSD Road/Node。
- 实验 Case 仅来自 `E:\TestData\POC_Data`。
- canonical T10 baseline 只作为上述 Case 的可追溯标签来源。
- 不修改 T01-T06 正式算法、接口或正式输出。
- 不新增仓库级正式 CLI、脚本或 T10 stage。
- 不执行 silent fix；异常进入结构化审计，必要时交用户重新人工评估。
- 通用图约束只在解码时屏蔽形式非法动作，不执行 Segment 归属、SPLIT、方向、路口映射或补路业务策略。
- JSG-P0 的 R2 Oracle carrier 仅为 label-only 编译真值，不得解释为候选或模型推理输出；无法解释的结构保持 `REVIEW/UNKNOWN`。
- 当前 source-of-truth 以方案 A 为准；上述 JSG-P0/P1/P2/P3 对象、PTO-A 和指标均为历史实验，不得覆盖 T01 Segment/ADVANCE_RIGHT/PhysicalMovement 冻结骨架。

## 可选训练环境

核心依赖不包含 PyTorch。需要复现实验时使用锁定的可选 extra：`uv sync --python 3.10 --extra dev --extra p05-neural`。M1 实测 GPU 环境为隔离的 Python 3.12、`torch 2.9.1+cu128` 和 RTX 5090；正式锁文件固定同版本 CUDA 12.8 wheel，不改变默认 `dev` 同步命令。

## 历史阶段：P13-P0 提右候选集合模型 NO-GO

`P05-Scheme-A-P2-P3-P8` 已完成并判定
`P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`。51个
eligible Case的T03/T04正式T05 handoff来源、Case-local T01 `junc_nodes`关联和
双跑审计通过；稳定carrier wrong得到2个train-only
`KEEP_SWSD + clue=true`同类证据，carrier来源值得字段级二次评审。但T03/T04只覆盖
1/6稳定Clue错误，不能作为完整Clue来源。T03/T04仍为`label-only`，当前未训练模型；
生产/在线接入和自动替换SWSD继续禁止。

P9已按批准目标完成602维Movement-free Control与冻结Control后的source residual
adapter严格A/B，正式decision为
`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`。隔离和整图安全成立：无来源及Clue
差异为0，每seed RoadGraph保持49 `LEGAL`+2 `EXPECTED_FAIL`；但适用对象分类没有
增益，稳定错误在三seed仍选`USE_RCSD`。该adapter不得进入生产或自动替换，后续阶段
需重新授权。

P10随后用用户逐对象裁决重解释P9：609对象的`USE_RCSD`正确，两个RCSD数据缺失对象
为`KEEP_SWSD + RealityChangeClue=false`，P9旧稳定carrier错误归因失效，但adapter
仍无严格增益。P11冻结人工复核接受集。旧P12把提右两端误当T05锚定目标，已保留为
历史实验且不得实施；提右不经过T05。

P12R按正式业务链重建474个`ADVANCE_RIGHT Segment`：先读取相邻普通Segment的T06
替换结果决定两侧RCSD/SWSD来源，再用T06 final Road/Node及
attachment/closure/topology审计重建`RCSD_ONLY/SWSD_ONLY/MIXED_SPLICE`或安全
fallback。40个`access_valid=false`保持Review，T05提右标签、Movement决策、
T06终态推理候选、geometry写入和T01–T12修改均为0；挂接Segment缺失、独立Road
丢失和unsafe auto publish均为0。

正式双跑
`p05_scheme_a_p2_p3_p12r_advance_right_audit_20260724_03/_04`的content signature
均为`320a8216a3e3592c9037f32300af7162b10d615277130d132bd410bb68e825e7`，
Run B reference match=true。396个eligible对象命中377个，总体candidate oracle
recall=`0.952020`；最差fold为T10:706247的`21/24=0.875`，低于0.90门。19个漏候选
均为`RCSD_ONLY`：其中17个正确RCSD有直接lineage但距原SWSD提右约
`5.15–43.55m`，另2个缺少可直接消费的原始RCSD lineage。正式decision为
`P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED`。下一阶段不得训练
scorer，应先另行授权建设Road endpoint/JunctionUnit条件化候选扩召回，并保持
5m局部候选作为审计层而非直接放宽成业务规则。

P12R-R1已在不读取T05提右标签、不把T06终态作为推理输入的前提下，用冻结T01
骨架、原始RCSD Road/Node和相邻普通Segment端点关系构造truth-free候选bundle。
Control完整复现P12R的474个对象；Treatment新增180条候选后，396个eligible对象
命中从377提升到388，总体candidate oracle recall由`0.952020`提升到
`0.979798`，最差fold由`0.875000`提升到`0.916667`，没有fold下降。

正式双跑
`p05_scheme_a_p2_p3_p12r_r1_endpoint_candidates_20260724_01/_02`
的candidate frozen signature均为
`84344d11cdc168cea42cdaacd0c36f83f9f4b57e45dd01b802a9c35ce064f734`，
content signature均为
`244b81957cf4eb39889fd88b61bdccb296707a901f8240580c46061aeb2a1e5b`，
Run B reference match=true。候选数P95/max=`4/12`，歧义bundle自动加入、证据不完整
自动加入、unsafe publish、geometry写入、Movement决策、训练和T01–T12修改均为0；
正式decision为`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`。

该GO只证明“正确提右carrier在推理期候选集合中基本可达”，不证明任何神经模型
已经能正确排序或自动发布。下一阶段如继续，需另行确认以R1候选为冻结输入的
scorer训练与安全验收目标；不得把R1的10m候选关联阈值解释为业务锚定规则。

P13-P0已按用户授权在R1候选上完成3 seeds × 5 Case folds训练。模型为480,739参数
的candidate encoder、mean/max set pooling、Road子集decoder、object head和独立
safety head；5m Local候选作为固定先验，网络只学习加/删候选的残差。50维输入只
来自冻结T01、原始RCSD及R1 truth-free endpoint/geometry证据，Movement、T05/T06
终态、Case/fold身份、路径和绝对坐标均未进入模型。

正式Run为`p05_scheme_a_p2_p3_p13_p0_oof_20260724_05/_06`。两轮共同feature
signature为`949d15ff4d0a87cce8c1be0f742aa921110e08baf6a288af7b38730f6c9c4e53`，
共同content signature为
`c219be6609e0bc0a9dfccb9077a2a19de20f23fc10059839313dd28679fa3925`，
Run F reference match=true；15个确定性NPZ checkpoint逐文件hash一致。

模型raw exact-set accuracy=`0.646907`，低于Local Control的`0.680412`
（delta=`-0.033505`），最差fold=`0.363636`；candidate/object macro-F1为
`0.750984/0.791407`。安全层仍有14次unsafe RCSD发布、2次Review RCSD发布和1次
R1不可达对象发布，零错误accepted coverage仅`0.017677`，最差fold为0。正式
decision为`P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO`。

该NO-GO不否定神经网络整体，也不重新打开R1候选补强。它否定的是“只用当前R1
候选级关系/几何特征独立选择提右Road集合”的方案。普通提右业务本来依赖相邻普通
Segment替换后的RCSD/SWSD状态；下一阶段若继续，应先讨论使用普通Segment OOF soft
carrier状态做joint conditioning，而不是继续调整本模型seed、epoch或held-out阈值。
