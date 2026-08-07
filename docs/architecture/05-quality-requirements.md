# 05 质量要求

## 文档定位

本文档维护项目级质量要求。模块验收指标、case 基线和具体算法检查由模块级文档承载。

## GIS 与拓扑质量

- CRS 与坐标变换必须明确、可复核，不允许默认坐标系假设进入正式规则。
- 拓扑关系必须与输入契约一致，不允许 silent fix 或未记录的几何修补。
- 几何语义必须可解释，过滤、锚定、替换和 fallback 需要有审计原因。
- 空间窗口、缓冲、相交、覆盖、方向和连通性判断必须能追溯参数来源。

## 数据契约质量

- 字段启用必须有项目级或模块级 source-of-truth 依据。
- 未确认字段不得进入强规则；字段冲突必须先形成审计证据。
- 模块输出不得只依赖隐式约定，正式成果、review-only 成果和中间审计应明确区分。
- 跨模块编排不得只依赖上游结果目录推断关键文件；T10 负责把端到端 handoff 显式化到文件级 slot。
- T12 不允许把 SWSD 与原始 1V1 F-RCSD 的等价假设直接用作修复；只展开选中 `base_id` mainNode 的 canonical raw alias group，其它显式 grouped raw node 不递归扩组。成员必须落回 raw identity endpoint 图，source/target 只接受当前方向的 outgoing/incoming Road，锚定 alias 距离只作审计，非锚定 spatial fallback 不放宽。必需方向缺失候选只有在 raw endpoint failure 无法被受信 portal-constrained semantic carrier 或 T07 Road-surface portal carrier 解释，并通过标准路口、方向/几何和锚点可信度门禁后，才能自动进入正式问题层。Road-surface carrier 必须包含方向正确的物理 Road，并由唯一 T07 标准面的 Road 相交或锚点组一跳 frontier 证明；距离指标只作审计。非预期反向候选必须同时证明 F-RCSD raw 反向物理载体满足几何阈值，并保守排除 SWSD 全图的等价反向替代路径；还必须证明第一/最后 Road 在 `1m` 容差内接触双端唯一 T07 标准面，且锚点间每条 raw RCSD Road 按 `20m/50m coverage + distance` 唯一归属于当前 Segment。其它 Segment 更强覆盖、归属并列和弱锚点不得自动发布。canonical 零长度折叠、无物理 Road 或任意近邻端点不能形成正式载体，全部 raw/semantic/surface/锚点区间/Segment 归属/反向替代排除与可选 review override 证据必须保留。
- T12 Junction 层必须把 T03 rejected 限制为正式 eligible 候选并以原始 1V1 F-RCSD 重验，只有 terminal-collapse 或 unmatched-support 完整强门禁通过才可确认；`6m/50m` 距离只作 endpoint 投影、局部 support 检索与审计。同 endpoint 的其它 Segment Road 不得自动并入当前 Junction support。T07 只直接发布正式 1:N/N:1 稳定失败，duplicate 只审计。Segment 线几何族（`LineString/MultiLineString`）与 Junction Point 的结果、计数和根因 evidence 独立，任何输入不得 repair、snap 或 silent fix。
- 混源数据结果必须能解释 SWSD、RCSD、F-RCSD 各自承担的语义角色。
- P05 训练样本必须能证明人工检查边界与 T06 artifact lineage；同一业务对象不同版本不得跨 train/validation/test，缺失标签应 task-mask 而非补造。
- P05 方案 A 必须逐 Case证明 T01 Segment 集合、`pair_nodes/junc_nodes`、Junction relation 和 PhysicalMovement 存在性未被修改；骨架 mutation 数必须为零。
- 当前 P05 业务输出不得含 `SegmentConnector`；全部普通提右必须保留为具有独立 Road 的 `ADVANCE_RIGHT Segment`。旧 Connector 指标只作历史证据。
- P05 fallback 必须按模型明确的 Segment/Junction 有限作用域执行：Segment 级只含自身，Junction 级只含模型列出且经冻结 T01 验证的直接关联 Segment；不得沿 `Junction—Segment—Junction` 传递，跨边界扩张计数必须为零。原始 SWSD Road/Node 不合法、mainnode 分组冲突或证据与先验冲突必须生成 `RealityChangeClue` 并失败，禁止 silent fix。
- P05 M1/M2R 必须阻止不同局部 Case 中相同业务对象、Road 实体及门禁邻域跨 split；任务目标字段只作 label/evaluation，不能进入模型输入，物化器不允许业务 fallback 或 silent fix。M2R 的通用约束不得编码 Segment 归属、SPLIT、方向、路口映射或补路。
- P05 R2 必须先通过 oracle 表示门禁：Road truth edit coverage 至少 `99.9%`、Node/SPLIT/pointer 可表达率 `100%`，51/51 Case 的归一化 Road/Node 与有向拓扑精确重建；未通过不得进入模型泛化声明。oracle payload 只能 label-only，模型推理不得读取。
- P05 R2 已通过表示和 small-batch 门禁，但当前 ordinal slot-query 模型未通过 grouped OOF；在另立架构实验并重新通过相同门禁前，不得以训练 loss、资源合规或通用合法性约束替代最终 RoadGraph 泛化指标。
- P05 PTO-P0 必须先冻结 51 Case 无 truth 候选 manifest，再读取 label-only truth；Road `23,224`、最终 Node `27,553`、T05 Node `24,739`、pointer `4,760`、SPLIT child `1,730` 可达率均为 `100%`，51/51 Case须 OPTIMAL/gap=0 且 Road/Node/属性/有向拓扑精确一致。任一 truth leakage、relaxation、内容修复或 silent fix 均 hard fail。
- P05 PTO-P0 已满足上述语义与确定性门禁，但含策略 replay 的端到端 P95/max 未满足 `60s/300s`，且 replay CPU time 不完整。PTO-P1 只能先使用冻结/缓存候选做 grouped OOF learned scoring；在线或生产化必须以新 proposal generator 重新证明端到端性能。
- P05 JSG-PTO-P0 固定 51 Case并排除 `T10-Error / 1213556_1263661`。实际出现的 Junction/Segment/Relation/Movement/Connector/Terminal/loop 实例可表达率、canonical 语义往返和 compiler 成功率必须为 `100%`；零真实实例类型必须显式报告。Road/Node CRS、ID、引用、几何与有向拓扑 hard failure 为零，多 THROUGH 自动选择为零，`content_repair=false`、`silent_fix=false`。单 Case P95/max 分别不超过 `30s/120s`，RSS 不超过 `16GB`，无需 GPU，总 CPU 不超过 `1h`。

JSG-PTO-P0 实测通过上述门禁：51/51 JSG 往返和 compiler 精确，hard failure=0；Run A/B 的单 Case P95 为 `6.278s/6.320s`、max 为 `18.314s/21.840s`、峰值 RSS 约 `1.054GiB`，无需 GPU。loop 为真实零实例，只计 schema/合成边界验证。

- P05 JSG-PTO-P1 必须先冻结零 truth candidate manifest；实际可确认 JSG 语义候选 reachability 和 PTO-B RoadGraph edit reachability 为 `100%`，PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0、relaxation=false，compiler hard failure=0。多 THROUGH 只允许 Review，candidate/selection 双跑 signature 一致。P1 增量链 P95/max `<=60s/300s`、RSS `<=16GB`、总 CPU `<=2h`；历史 replay 性能必须另列。

JSG-PTO-P1 实测通过：两轮均 51 Case，候选 417,493 个、72,318 groups，truth/派生/label-only candidate 均为零；PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0，RoadGraph 51/51 精确，hard failure=0。P95 为 `7.397s/8.892s`，max 为 `26.294s/24.906s`，峰值 RSS 约 `3.677GB`，无需 GPU；历史 replay 5,751.192s 仍不满足在线 proposal 成本。

- JSG-PTO-P2 必须复用 M0 business-ID grouped 5-fold，每个 Case 恰好一次 held-out，fold/ID/truth/oracle feature leakage 为零。V0/V1 score 和 explanation 覆盖 100% 候选。
- P2 PTO-A Top-1 总体/各对象类型至少 `0.90/0.80`，JSG semantic micro/macro F1 至少 `0.90/0.85`，Review/Unknown recall 至少 `0.90`。
- P2 grouped OOF Road/Node F1 至少 `0.85/0.90`，最差 Case Road F1 至少 `0.70`，direction/source 至少 `0.95`，每类 SPLIT recall 至少 `0.70`；图 hard failure 和事后修复为零。
- P2 score P95/max `<=5s/20s`，完整冻结候选链 P95/max `<=60s/300s`、RSS `<=16GB`、训练 CPU `<=2h`；双跑 score/selection/JSG/RoadGraph signature 一致。

P2 实测：V1 JSG Top-1/macro F1/Review recall 为 `0.7243/0.6173/0.0130`，排序门禁失败；RoadGraph safety gate 通过。P3 后续已完成：JSG Top-1/macro 提升至 `0.9390~0.9395 / 0.8471~0.8817`，但 Connector 和 Review/Unknown 未达下列主门禁，判定 `P3_MODEL_NO_GO`；RoadGraph、GIS、资源与确定性门禁继续通过。

- JSG-PTO-P3 固定 51 Case、191,331 groups、712,799 candidates 与 M0 business-ID grouped 5-fold；context/outer/inner leakage 为零。
- 参数目标 `0.5M~3M`、上限 `5M`；正式 3 seeds × 5 folds，三个 seed 均须通过。
- JSG Top-1/micro `>=0.90`、macro `>=0.85`、五种对象类型均 `>=0.80`；Review/Unknown recall `>=0.90`、precision `>=0.80`、ECE `<=0.10`。
- PTO-A/PTO-B 51/51 `OPTIMAL`；Road/Node、最差 Case Road、direction/source、SPLIT 均保持 `1.0`；全部 hard failure/repair 为零。
- 单 seed 5-fold `<=2h`，3 seeds 总计 `<=6h`，RAM `<=16GB`、VRAM `<=8GB`；score 与完整链沿用 P2 `5s/20s`、`60s/300s` 门禁。

上述 JSG-PTO-P0/P1/P2/P3 以及 P1–P13 门禁均为历史实验门禁。当前 Target A
首先继承冻结骨架、完整标签作用域、`RealityChangeClue`、fallback 正确性、
双跑确定性和 no-silent-fix，再按联合业务目标验收：锚定对象、完整 Road 清单及
用途/所有权、access、Node、方向、打断/衔接与最终拓扑必须正确；正向
`KEEP_SWSD` 与 `ABSTAIN -> fallback` 分开；同时报告自动决策整图 exact 和
fallback 后最终 RoadGraph exact，并与完整现有策略做 paired comparison。任一
unsafe auto RCSD、Review auto、unreachable auto、skeleton mutation、silent fix
或新增 RoadGraph hard failure 非零即为 NO_GO。

Target A 当前先执行独立路口门。Gold 冻结测试必须达到 raw 完整路口 exact
`>=0.85`、自动业务决策覆盖 `>=0.80`、自动接受完整正确率 `=1.0`、危险自动接受
和真值未知自动接受 `=0/0`；已证明异常不得自动判正常，`异常或安全 ABSTAIN`
recall 必须为 `1.0`。T10 留出集按 0.7 标签计算的完整路口 exact 必须
`>=0.75`。完整路口 exact 同时比较 surface、锚定状态、RCSD 对象集合、聚合/打断、
重构拓扑和质量状态。相同输入/输出/环境下，包含一次性索引构建的模型链总耗时不得
超过现有 T07+T03+T04+T05 规则链的 1.5 倍，且城市输入不得按路口重复全量读取。

方案 A baseline 已通过：51 Case、8,863 Segment、474 ADVANCE_RIGHT、24,779 PhysicalMovement 全量覆盖，双跑五类业务 signature 一致；40 个不可发布 ADVANCE_RIGHT 显式 `REVIEW_FALLBACK`，不补造 access 或 Road。Run A/B P95/max 均远低于 `30s/120s`，RSS 低于 16GB，CPU 低于 1h，无需 GPU。

Scheme-A-P1 的 RoadGraph safety gate 以51 Case确定终态为分母：`T10:74155468`、`T10:609214532` 必须为可复现的 `EXPECTED_FAIL`，输出 `RealityChangeClue` 且不发布；其余49 Case必须全部 `LEGAL`。expected failure 只豁免“最终图合法”这一项，不豁免模型指标、异常召回、lineage、确定性、no-repair、no-silent-fix或资源门禁；任何额外失败均使 Gate 4失败。

Scheme-A-P1 正式结果为 Gate 0/4/5 PASS、Gate 1/2/3 FAIL，结论 `P05_SCHEME_A_P1_MODEL_NO_GO`。三 seed accepted coverage 为 `0.3637/0.3589/0.3533`，seed 29/43 anomaly precision 为 `0.7684/0.7472`；49+2 RoadGraph 终态、安全、确定性和资源门禁全部通过。

Scheme-A-Dataset-P0 已通过范围/角色隔离、标签完整性、候选可达性、Oracle/RoadGraph safety、GIS/资源五类门禁：T01 RCSD label、truth-derived candidate、Movement 决策、骨架 mutation、CRS 冲突、重复 truth ID、repair/silent-fix 均为零；`USE_RCSD` 非 T01 candidate、可用 Segment Road、T06 final Road/Node 与联合 exact 均为 `100%`，并保持 49 `LEGAL` + 2 `EXPECTED_FAIL`。该门禁不包含 scorer OOF 或在线性能。

Scheme-A-P2-P1正式门禁为：candidate/label隔离和JunctionUnit compatibility Oracle 100%；3 seeds × 5-fold中每seed Segment macro-F1 `>=0.98`、`USE_RCSD` recall `>=0.85`、JunctionUnit Node exact `>=0.90`、ECE `<=0.10`；自动接受错误=0，总体与`USE_RCSD` safe accepted coverage均`>=0.50`，hard conflict recall=1.0、anomaly precision `>=0.80`；每seed49 `LEGAL` + 2 `EXPECTED_FAIL`且无repair/silent-fix。在线proposal不在本门禁。

正式实测中，数据/泄漏、Node exact、ECE、RoadGraph、确定性和资源门通过；错误接受、coverage、anomaly precision及seed43 Segment macro-F1失败，故判定`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`。资源证据为3 seeds训练`471.231s`、单Case scoring P95/max=`0.300s/0.968s`、峰值working set约`1.063GB`、CPU-only。

Scheme-A-P2-P2-P0 不改写 P2-P1 门禁，只审计错误根和安全信号。正式结果将 `17/9/17` 对象级 accepted wrong 分解为 accepted Segment 根错误 `2/0/3`，并证明 49 个可发布 Case 的最终有效 Segment→Node requirement 无 conflict/target mismatch；但任何 seed 的根错误仍须为零。单一 probability/margin/entropy/anomaly 信号的最佳零错误 `USE_RCSD` 覆盖为 `0.200275 < 0.50`，所以 calibration-only NO-GO；现有完整 feature 跨 truth 精确碰撞为零，只放行独立 safety head 的后续技术讨论，不构成模型 GO。

Scheme-A-P2-P2-P1 沿用每 seed accepted wrong=`0`、precision=`1.0`、总体与`USE_RCSD` coverage均`>=0.50`、unsafe fallback recall=`1.0`、Review/稳定false-use自动发布=`0`的门禁。正式三seed结果分别为`5/0.998495/0.374817/0.431714/0.979893`、`0/1.0/0.069841/0.066911/1.0`、`4/0.998477/0.296288/0.380843/0.980786`，故模型门失败。RoadGraph门全部通过：每seed49 `LEGAL`+2 `EXPECTED_FAIL`，conditioned Node requirement mismatch、payload conflict、unexpected failure均为0。正式结论`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`。

Scheme-A-P2-P2-P2-P0 要求两个预登记 probe 的每个 held-out fold 都达到 accepted wrong/9 error auto/Review auto=`0/0/0`、unsafe fallback recall=`1.0`、总体和`USE_RCSD` coverage均`>=0.50`。正式线性 probe 全局为`2/2/0/0.969169/0.525217/0.741980`，只有1/5 fold通过；浅层MLP全局为`0/0/0/0.994191/0.548686/0.755729`，但0/5 fold通过。两个 probe 的 RoadGraph 均为49 `LEGAL`+2 `EXPECTED_FAIL`，conditioned Node conflict/mismatch和新增失败为0。正式结论`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`。

Scheme-A-P2-P2-P2-P1 要求 9/9 一致错误、13/13 残留 unsafe accepted 和 40/40 Review 全部具有唯一直接终态；每个直接/辅助候选必须记录 source role、生成时点、推理可用性、成本和 lineage，相关信号不得冒充直接事实。正式结果 62/62 完成归因，终态 `40/22/0`，新增获准直接推理证据为 0，Run A/B signature 一致；因此质量门判定 `P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`，而不是模型 GO。

Scheme-A-P2-P2-P2-P2 将 carrier safety 与 clue visibility 分门验收：错误 carrier/Review 自动发布必须为0、carrier safety recall必须为1，同时每fold总体与`USE_RCSD` coverage均须`>=0.50`；clue recall独立报告，不得反向把正确 KEEP 判为错误 Road。浅层MLP全局为`carrier wrong=0 / carrier recall=1.0 / clue miss=13 / clue recall=0.994189 / coverage=0.548686 / USE coverage=0.755729`，但只有fold 1/3通过，fold 0/2/4覆盖门失败。22/22候选可达、26冲突/57 fallback闭包、49 `LEGAL`+2 `EXPECTED_FAIL`、双跑与资源门通过，故正式判定`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`。

Scheme-A-P2-P3-P0 沿用并收紧双指标门：3 seeds × 5 folds 均须 carrier wrong/Review auto=`0/0`、carrier recall=`1.0`、总体与USE coverage均`>=0.50`；clue recall=`1.0`、precision`>=0.80`、macro-F1`>=0.85`且13个clue-only全部捕获。正式结果 carrier wrong=`1/1/0`，seed整体 coverage=`0.5917/0.5917/0.1327`、USE=`0.7626/0.7626/0.2333`；clue recall=`0.9844/0.9852/0.9987`、13对象捕获=`9/8/12`。RoadGraph、source-role、参数、确定性、资源与性能门通过，但业务模型门失败，故为`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`。

Scheme-A-P2-P3-P1 要求输入/分母、逐对象归因和字段角色门全部通过；只有同时发现至少一类新增、已授权、truth-free 的直接推理证据，并冻结至少一个独立未使用的端到端验证集，才允许 `MODEL_RESTART_GO`。正式审计的前三门通过、字段角色违规为0，但新增直接证据=`0`、独立验证集=`0`，因此为`P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`。fold 2 frozen overall coverage门因1,795个expected baseline failure而数学不可达，eligible-only coverage仅作诊断，未获授权替代原门槛。

Scheme-A-Dataset-P1 要求45/45 Segment包完成direct ID或无歧义Road partition lineage；8,863个当前Segment只能唯一归入label或context-only，context进入label/loss/metric必须为0；两个expected-failure Case必须保持49+2终态，但全Case scorer级联mask必须为0。正式结果为41 direct ID（5 Road drift审计）+4 partition、6,275 label+2,588 context、context leakage=0、corrected cascade mask=0，Run A/B signature一致，故判定`P05_SCHEME_A_DATASET_P1_GO`。该GO只覆盖标签范围，不继承放行旧模型或训练。

Scheme-A-P2-P3-P2在eligible-only逐seed/逐fold分母继续要求carrier wrong/Review auto=`0/0`、carrier safety recall=`1.0`、总体与USE coverage均`>=0.50`；clue recall=`1.0`、precision`>=0.80`、macro-F1`>=0.85`且5/5 eligible clue-only捕获。正式accepted wrong=`1/13/0`、Review auto=`0/12/0`，seed317虽零错误但总体/USE coverage=`0.1506/0.2757`；三个seed的clue也没有同时通过。49+2 RoadGraph、scope、确定性、资源和无泄漏门通过，故判定`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`。

Scheme-A-P2-P3-P3要求6,275对象与冻结Segment清单全量匹配、40个invalid access只对应40 Review、非Review误触发为0；重放后Review auto=`0/0/0`、accepted wrong=`1/1/0`且49+2不变。正式双跑全部通过，残余对象三个seed稳定错误排序、60/60近邻均为`USE_RCSD`，因此只放行硬安全资格并判定下一表征必需，不放行scorer或生产。

Scheme-A-P2-P3-P4要求`8,863=6,275 label+2,588 context`、context标签贡献为0、
初始Node冲突10、Junction fallback Segment 21（eligible 10）、最终Node标签
28,240且无冲突；旧/新标签delta必须为`436=435 context+1 eligible`。唯一eligible
delta必须精确恢复残余对象为`USE_RCSD` candidate
`sap1:918ffd80e766808f8a6b516c`。正式结果三seed accepted wrong/Review auto均为0，
但coverage/clue逐seed逐fold门仍失败，故只放行真值重基线，不放行模型或生产。

## 工程质量

- 运行结果必须可定位输入、参数、输出目录、运行环境和版本状态。
- 性能问题必须可测量、可定位、可复现，不以主观“慢/快”作为结论。
- 仓库级入口、体量、目录规则以 `docs/repository-metadata/` 为准，architecture 不重复维护。
- 项目级文档不得复制模块级实现细节，避免形成并行 source-of-truth。

## P05 P2-P3-P5 质量结果

P5 继续要求每 seed 整体和每 fold 同时达到：错误/Review自动接受为0、carrier safety
recall=1.0、总体与 `USE_RCSD` safe coverage 均不低于0.50；clue recall=1.0、
precision不低于0.80、macro-F1不低于0.85且clue-only全部捕获。

正式三 seed 的 safe coverage=`0.4290/0.5498/0.1374`，`USE_RCSD` safe
coverage=`0.6918/0.7044/0.2310`；clue recall/precision/macro-F1分别为
`0.9805/0.6614/0.8512`、`0.8831/0.9985/0.9596`、
`0.9960/0.3605/0.5751`。这些coverage是final publication层；P6复算的scorer层
coverage为`0.6524/0.7952/0.3469`，wrong accepted=`1/1/1`，final wrong
published=`0/0/0`。模型安全与coverage/clue门仍失败，故正式判定
`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。

P2-P3-P6质量门要求18,825条唯一join、双层指标精确回算、两个expected-failure
Case每seed原子阻断1,954个eligible对象、稳定FP/FN=`2/4`、全部clue error相反标签
exact collision=0、train-only邻域无held-out Case泄漏及正式双跑一致。全部通过，
阶段归因GO；该门不包含模型训练或生产放行。

## P05 P2-P3-P7 质量结果

P7要求6,275/6,275对象具备`EPSG:3857` T01相对几何，602维表征中
truth/identifier/absolute-coordinate/T03–T06/Movement feature均为0；稳定wrong
的top-20至少出现1个`KEEP_SWSD`和1个`clue=true`才允许表征路线GO。正式结果仍为
`20/20 USE_RCSD + 20/20 clue=false`。校准合同的15个inner pool均满足每类至少500
且held-out Case贡献为0，但三个seed在recall=1时的最佳precision/macro-F1仅约
`0.241/0.238`、`0.239/0.229`、`0.361/0.582`，均未达到`0.80/0.85`。审计门通过、
两条技术路线失败，故为`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`。

## P05 P2-P3-P8 质量结果

P8来源/hash/CRS/角色、663个核心工件、6,275条Case-local精确join、禁止字段为0、
双跑和资源门全部通过。稳定carrier wrong命中T04来源，train-only同类对象为2，
全部`KEEP_SWSD + clue=true`且`USE_RCSD=0`，carrier来源门通过。稳定Clue错误来源
覆盖仅`1/6`，故Clue门失败；阶段只能是carrier-only部分GO，不允许把absence编码为
Clue，也不允许自动提升T03/T04角色或启动训练。

carrier-only promotion获批后，P9必须证明无来源零差异、Clue零source消费、稳定
wrong自动选择正确KEEP、每seed carrier wrong=0及safety recall=1.0；完整carrier
GO仍须逐seed/逐fold总体与USE coverage均`>=0.50`。

P9正式结果中隔离、RoadGraph、确定性和资源门通过，但promotion门失败：三seed
稳定对象均仍选`USE_RCSD`，scorer层错误自动接受均为1，safety recall分别为
`0.97778/0.97778/0.97619`；Control/Treatment适用子集pooled macro-F1和KEEP recall
均为`0.9986769935/0.99609375`，无严格增益。Control/Treatment seed coverage也
完全相同，且seed311总体coverage=`0.49816`、seed317总体/USE coverage=
`0.12077/0.16123`，完整carrier门同样失败。正式decision为
`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`。

P10对事后人工裁决只允许冻结输出复算：五个对象必须在Control/Treatment和三seed
唯一命中；未裁决对象保持candidate-exact，裁决对象分allowed/preferred/clue；
wrong accepted、Review auto publish、Junction fallback violation必须为0，carrier
safety recall必须为1.0。正式结果满足这些安全门，适用对象合法准确率为1.0；但两臂
优选命中率同为`0.9980158730`、strict gain=false，故只能判
`P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`。Clue pooled
precision/recall/macro-F1=`0.583278/0.987197/0.804359`、FP/FN=`3140/57`，稳定漏报
为0但稳定误报为50，继续阻断完整模型GO。
