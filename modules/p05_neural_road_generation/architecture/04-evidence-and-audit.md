# 04 证据与审计

Target A 的每个不可变 run 必须先记录路口阶段：原始 DriveZone/RCSDIntersection 与 T07/T03/T04/T05 label store 的物理隔离及 hash、Step1 无 RCSDIntersection 通道证明、Case-grouped split/checkpoint、T07 evidence、T03/T04 surface/relation evidence、T05 unique relation/graph-consumable/junctionization、完整锚定对象、逐类最差结果和零危险门。路口门通过后才记录 Segment/AR/RoadGraph 指标。所有阶段继续记录 CRS/几何/拓扑、城市级一次读取缓存和资源；候选 ID 只作映射与审计，不进入模型数值特征。

M0 的每个输出 run 必须不可变，并记录：

- POC_Data 根、Case manifest 路径与 hash；
- baseline 根、baseline summary、Case run summary 与 artifact hash；
- 标签权重、任务 mask、分组 ID、fold 和异常原因；
- Python、操作系统、GIS 库版本、参数、开始/结束时间与耗时；
- evaluator 匹配方法、fallback 原因、指标和 hard failures；
- 所有 CSV/JSON/报告的 SHA-256。
- 用户确认排除的 family、business ID、reason 与 decision source；approved exclusion 与 pending quarantine 分层。

原始 Case 与 baseline 只读。重新归档应生成新路径和新 lineage，不覆盖旧证据。无法自动消歧的异常保留到 `p05_data_anomalies.csv`，由用户决定是否重新人工评估。

M1 额外记录 `t01_roads` 输入 hash、candidate/operation schema、uncovered truth、跨 split entity guard、train-only normalization、模型参数量、checkpoint、seed、PyTorch/CUDA/GPU、训练曲线、逐 Case 预测 GPKG 和 M0 evaluator 原始结果。固定 test 的首次运行时间和冻结配置必须可定位。

M1 固定 test 仅由 `p05_m1_fixed_test_final_20260721_01` 访问一次，模型与 keep-all 在同一调用中评估。全量 dataset、训练、评价 manifest 和逐 Case GPKG hash 复核为零 mismatch；失败结论和拓扑 hard failure 同样属于必须保留的正式证据。

M2R 额外记录每个样本、任务和目标类型的 `available/unknown/invalid/excluded`、trust tier、权重、人工确认 scope、artifact hash、CRS 和 mask 原因。主要泛化证据使用 grouped out-of-fold；已访问的 M1 固定 test 只作历史回归。free/constrained 每次约束触发都必须记录模型原动作、分数、约束代码、替代动作与 `content_repair=false`。

R2 Gate 1 额外记录每个 Case 的 base/truth artifact、Road/Node edit、T05 pointer、action coverage、reconstructed GPKG、M0 evaluator 原始结果和全部 hash。oracle payload 必须显式 `label_only=true`。Gate 2/3 记录 query target、分 loss/梯度、checkpoint、grouped OOF、双解码、确定性、最差 Case 和资源；任何失败门禁同样是正式证据。R2 正式证据根为 `p05_r2_oracle_20260721_03`、`p05_r2_dataset_20260721_01`、`p05_r2_gate2_20260721_05` 和 `p05_r2_oof_20260721_03`，最终 validation summary 逐项关联这些不可变 run。

PTO-P0 分成 candidate 与 solve 两个不可变 run。前者记录策略 commit、T10 Case/stage 状态、外部输入/策略输出 hash、候选/变量/分组/约束数及泄漏计数；后者固定引用 candidate manifest hash，记录 label-only cost、coverage、选择、最优性证书、逐 Case GPKG/M0 evaluation、确定性和 replay/build/solve 性能。正式证据根为 `p05_pto_candidate_20260721_01/_02`、`p05_pto_solve_20260721_04/_05`、确定性 audit 和 GIS audit；语义通过与性能 no-go 同时保留。

JSG-PTO-P0 使用两个不可变 run。每个 run 记录 51 Case T01/T05/T06/R2 输入路径和 hash、canonical JSG truth、对象类型覆盖、REVIEW/anomaly、语义 signature、carrier realization、R2 edit IR、编译 Road/Node、M0 evaluator 原始结果、环境和资源。两轮比较不包含时间/绝对输出目录的 semantic signature，并单列 provenance signature；零实例类型、Review 和失败都不得从分母隐藏。

正式 run 为 `p05_jsg_p0_20260721_04` 与 `p05_jsg_p0_20260721_05`。两轮各 51 Case，semantic/compiled/provenance signature 一致，逐 Case 选择字段差异为零，carrier missing reference 为零；SpecKit `validation_summary.md` 和 `determinism_audit.json` 为完成态索引。

P1 使用不可变 candidate run 与 solve run 两级证据。candidate run 不记录 truth path，只记录 candidate/group/lineage/hash 和零泄漏计数；solve run 记录 truth manifest、Oracle cost、PTO-A/PTO-B certificate、selected JSG、carrier feasibility、compiler/M0 原始结果。历史 strategy replay 与 P1 增量资源分开统计。

P1 正式证据根为 `p05_jsg_p1_candidate_20260722_01/_02`、`p05_jsg_p1_oracle_20260722_02/_03` 与 `p05_jsg_p1_validation_20260722_01`；候选/选择/JSG/RoadGraph 双跑签名一致。

Dataset-P0 正式证据根为 `p05_scheme_a_dataset_p0_20260722_04/_05`，确定性审计为 `p05_scheme_a_dataset_p0_determinism_20260722_02.json`。两轮完整保存 module role contract、sample/artifact/task 清单、candidate source、Segment/Case reachability、summary/manifest 和 artifact hash；七类内容 signature、全部 Gate 与 `P05_SCHEME_A_DATASET_P0_GO` decision 一致。

P2-P1正式证据为dataset `p05_scheme_a_p2_p1_dataset_20260723_01`、OOF `p05_scheme_a_p2_p1_oof_20260723_01/_02` 和audit `p05_scheme_a_p2_p1_audit_20260723_02`。dataset保留候选manifest、feature/label/fold、77,964条truth-free compatibility edge、forbidden-feature和compatibility Oracle；OOF逐seed/fold保留词表、归一化、checkpoint、score、threshold、accepted/fallback和RoadGraph；audit证明双跑内容一致以及GIS/CRS/资源门通过。失败对象和seed43波动完整保留。

P2-P2-P0正式证据为`p05_scheme_a_p2_p2_p0_audit_20260723_01/_02`。两轮从相同P2-P1冻结artifact生成truth-free safety signal、accepted-wrong传播链、Review审计、feature collision和separability summary，六类内容hash一致；不修改P2-P1 checkpoint、score、threshold、selection或RoadGraph。

P2-P2-P1正式证据为`p05_scheme_a_p2_p2_p1_oof_20260723_03/_04`。两轮均覆盖3 safety seeds×5 folds、8,863 Segment和153张RoadGraph；scores/decisions/evaluation/effective selections hash一致，路径归一化后的RoadGraph index与业务signature一致。每fold保留checkpoint、只由训练Case建立的vocabulary/normalization、内层阈值和train/inner/held-out Case清单。正式decision均为`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`。

P2-P2-P2-P0正式证据为`p05_scheme_a_p2_p2_p2_p0_audit_20260723_02/_04`。两轮覆盖8,863×202 evidence、9 error/40 Review ledger、10个fold checkpoint、decision/evaluation、conditioned Node selection和102张RoadGraph；规范化signature均为`b04485a71f05df15d36135a3193edcf8db150855ae24878b435faead028142e3`，Run B reference match为true。`_01`为全局metric对齐修正前诊断，`_03`为墙钟字段移出determinism payload前重放，二者不作正式指标来源。

P2-P2-P2-P1正式证据为`p05_scheme_a_p2_p2_p2_p1_attribution_20260723_01/_02`。两轮对62个唯一对象输出逐对象直接原因、辅助信号、推理可用性、成本、lineage和source contract；终态为40 inference available、22 source fact blocked、0 unobservable。规范化signature均为`b7abcf3c68f6d2ee6bc36ff2ba38d28d785c2e7461e8617b7eb6f5a4edcb3bce`，Run B reference match为true。

P2-P2-P2-P2正式证据为`p05_scheme_a_p2_p2_p2_p2_audit_20260723_01/_02`。两轮重算8,863 Segment双指标，检查22个candidate/source route，并重建26个初始Node payload conflict与57个Junction fallback Segment；规范化signature均为`f50389a9d87522dd14bda8def879a815425a2cfb96f6f4cb99ff304cbba264d3`，Run B reference match为true。两轮wall=`88.48s/85.74s`、RSS约`1.67GB`、GPU为0。

P2-P3-P0正式证据为`p05_scheme_a_p2_p3_p0_oof_20260723_01/_02`。两轮记录15个fold的词表/标准化/model signature/threshold、26,589条Segment决策、Node/Junction effective carrier和153张seed×Case RoadGraph；内容signature均为`d6974ccaa140442412cf793d1379dc3a3232a1bba9b874207dcb12d7faddff59`，Run B reference match为true。两轮wall=`403.32s/373.59s`、peak RSS=`2.43GB/2.44GB`、GPU为0。

P2-P3-P1正式证据为`p05_scheme_a_p2_p3_p1_audit_20260723_04/_05`。两轮核验全部输入manifest/hash，输出3,049个唯一重点对象、17类字段角色和776条验证库存；其中cohort分母为fold2=`3,037`、stable false-use=`1`、clue-only=`13`。两轮五类核心工件逐字节一致，signature均为`177344821e1b8b932a7b19bf16248ede1f6293d622c16570ba301ea9a7384311`，Run B reference match为true；wall=`26.04s/26.13s`、peak RSS约`0.463GB`、GPU为0。

Dataset-P1正式证据为`p05_scheme_a_dataset_p1_20260723_01/_02`。两轮保存
45条package lineage、8,863条唯一label scope、6条expected-failure seed scope
与9条历史指标失效记录；41 direct ID、5 Road drift、4 Road partition及
6,275/2,588标签/上下文分母完全一致。核心四工件逐字节一致，signature均为
`bc848a8a0eeda04c14b358d505bc70258deaf36bb40cb617611ba7c4d205065c`，
Run B reference match=true；CRS=`EPSG:3857`，geometry read/write=0，
wall约4.96s、RSS约0.362GB、GPU=0。

P2-P3-P2正式证据为`p05_scheme_a_p2_p3_p2_oof_20260723_04/_05`。两轮保存
6,275个eligible OOF score/decision/evaluation、2,588个context-only fallback、
8,863 Segment effective selection、15个fold模型和153张RoadGraph；规范化
signature均为`e1bc5b5e55ddeaba8f87cbaa36f8a6261461e206a72aa8d240385c46c30d534f`，
Run 05 reference match=true。核心scope/score/decision/effective/closure工件逐字节
一致；wall约305.92s/289.69s、RSS约2.44/2.43GB、GPU=0。Run 01/02为signature
审计修正前诊断，空Run 03为宿主中断残留，均不作正式指标来源。

P2 dataset run 记录 P1/M0 输入 hash、fold、label weight、feature vocabulary 与 forbidden-token audit。OOF run 记录五个 fold model、全部 V0/V1 score、可重建 explanation、group margin、逐 Case certificate/GPKG/GIS 指标、资源和双跑 signature。失败 fold/对象类型/Case 不得从分母隐藏。

正式 P2 证据根为 `p05_jsg_p2_dataset_20260722_02`、`p05_jsg_p2_oof_20260722_02/_03` 与 `p05_jsg_p2_validation_20260722_01`。两轮业务签名与模型 hash 一致；204 个 GPKG、101,554 个几何的 CRS/有效性/类型审计通过，无拓扑 hard failure、relaxation、content repair 或 silent fix。

P3 context dataset 记录 P1/P2 输入 hash、191,331 groups/712,799 candidates 范围、dependency/reverse-dependency context、forbidden token 和 truth-use audit。每个 fold/seed 模型记录 train/inner/held-out Case、fold vocabulary、checkpoint/hash、参数量、history 与资源；正式 validation 汇总 3 seeds × 5 folds、同 seed 双跑、PTO/RoadGraph/GIS 与 no-repair 证据。

正式 P3 证据根为 `p05_jsg_p3_dataset_20260722_04`、`p05_jsg_p3_formal_20260722_01`、同 seed 确定性对照 `p05_jsg_p3_dev_seed17_20260722_03` 与最终 `p05_jsg_p3_validation_20260722_02`。candidate-only 消融、三个 seed 的失败类型、全部 153 个 Case-seed RoadGraph/GIS、资源与 104 项 P05 回归均保留；验证 manifest 的决策为 `P3_MODEL_NO_GO`。

方案 A 使用两个独立不可变 baseline run。每个 run 记录 51 Case 的 T01 Segment/Road/Node、T06 relation、M0 fold/weight、历史 JSG-P0 manifest/hash，输出冻结 skeleton、三态 strategy baseline、carrier-only labels、RealityChangeClue、fallback plans、CRS/Road/Node/mainnode 审计、资源和全部 artifact hash。双跑比较 skeleton/baseline/label/clue/fallback signature；`skeleton_mutation_count=0`、`content_repair=false`、`silent_fix=false`。

方案 A 正式证据根为 `p05_scheme_a_baseline_20260722_12` 与 `_13`，修正前 `_10/_11` 仅保留历史证据。两轮各 51 Case、60 个声明 artifact，8,863 Segment/24,779 Movement 全量覆盖；五类业务 signature 完全一致。913 条 clue 与 1,222 条 fallback plan 保留逐对象 lineage；Segment 单元的 679 条 plan 不再包含 Movement，40 个 access 不可确认 ADVANCE_RIGHT 显式 mask/失败，未用几何近邻补造。

Scheme-A-P1 正式 OOF 必须逐 Case记录 RoadGraph `LEGAL/EXPECTED_FAIL/FAIL`、clue、publish、failure signature 与输入 lineage。`T10:74155468`、`T10:609214532` 是唯一允许的 expected-failure manifest；双跑必须精确复现其缺失端点 Node 证据，且其余49 Case均为合法图。

Scheme-A-P1 已完成。正式 candidate/dataset 双跑、3 seeds × 5 folds OOF `p05_scheme_a_p1_oof_formal_20260722_01`、seed 17重放 `_02` 和 QGIS 审计均已冻结；三个 seed 均为 `49 LEGAL + 2 EXPECTED_FAIL`。candidate、dataset、model state、score、prediction、fallback 与 RoadGraph 内容确定性通过，最终模型结论为 `P05_SCHEME_A_P1_MODEL_NO_GO`。

P2-P3-P3正式证据为`p05_scheme_a_p2_p3_p3_audit_20260723_02/_03`。两轮保存
6,275条安全资格ledger、120条硬门决策、全量effective selection、153张RoadGraph
及残余false-use近邻审计；signature均为
`0f7d4ee09835afb408efa986f54ed980ca941484a3ca62c7f3805f8d684fa97c`，
Run B reference match=true。wall约107.23s/130.52s、RSS约1.82GB、GPU=0；
training/threshold/T06 inference/Movement/geometry/repair/silent fix/mutation均为0。
Run 01口径修正前工件只作诊断。

P2-P3-P4正式证据为
`p05_scheme_a_p2_p3_p4_rebaseline_20260723_01/_02`。两轮保存8,863条
scope-first Segment truth、28,240条Node truth、10条初始Node conflict、21条
Junction closure、436条label delta、三seed指标和残余重解释；signature均为
`3f2f2399a11a1b4675bc5b30d29043e764bd7991a71c2d06f6fccbdde265ed37`，
Run B reference match=true。wall约129.26/127.38s、RSS约2.25GiB、GPU=0；
training/threshold/T06 inference/Movement/geometry/repair/silent fix/mutation均为0。
RoadGraph未重建，既有49+2和closure安全工件按hash验证。

P2-P3-P5 Dataset正式证据为
`p05_scheme_a_p2_p3_p5_dataset_20260723_01/_02`，signature均为
`5efbe66318f818dd705dbd10acd48366e328d2f8e61bae51812a46d5cf61fb46`。
OOF正式证据为`p05_scheme_a_p2_p3_p5_oof_20260723_01/_02`，训练引擎为
`p05_scheme_a_p2_p3_p5_engine_20260723_02/_03`；OOF/engine signature分别为
`de6c92d0bde80f2d0690af76a340931d802cdf5def7bc63601406040720dce02`和
`349111b038332620260fdea390dfcf500a794a714e457594167cd67c7750a94f`，
Run B reference match均为true。全部manifest output hash复核通过，正式decision
为`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。

P2-P3-P6正式证据为
`p05_scheme_a_p2_p3_p6_attribution_20260724_03/_04`，共同signature为
`e753bb817be16841adf4832dbfe3d68ed579e7b851364dd54a4569bbbf180a1c`，
Run B reference match=true。两轮保存18,825条逐对象归因、3,587条clue error、
双层carrier指标、expected-failure原子阻断审计和18组稳定对象train-only邻域；
wall约18.97/16.50s、RSS约0.621/0.619GiB。训练、调阈值、GPU、T06 inference、
Movement、geometry、repair、silent fix和mutation均为0。

P2-P3-P7正式证据为
`p05_scheme_a_p2_p3_p7_audit_20260724_01/_02`，共同signature为
`3154e4bb6af8358efcfff6f6dd5ed7ca90189f0d915d654d86fb1cbcdac2bcee`，
Run B reference match=true且representation signature一致。两轮各保存6,275条
602维表征与source/feature/neighborhood/calibration审计；geometry read=51、
write/transform=0，wall约11.24s、RSS约0.559GiB、GPU=0。

P2-P3-P8正式证据为
`p05_scheme_a_p2_p3_p8_source_audit_20260724_02/_03`，共同signature为
`4b3002494b6c33400907751aca44c375481a3602bb3cff1f8cad45bce8852508`，
Run B reference match=true。两轮各核验663个核心工件、2,710条来源事实、6,275条
Segment applicability；wall约48秒、RSS约0.274GiB、GPU=0，训练/拟合/调阈值、
geometry write/transform、空间join和mutation均为0。

P9正式证据根为`p05_scheme_a_p2_p3_p9_oof_20260724_01/_02`，四分组记录了
Control/Treatment、applicable/non-applicable及scorer/final结果。两轮signature均为
`e8f19d737a27e5789ea861e18730f11d192a9b97635ca25a8fd4ac299f37871b`，
Run B匹配；隔离、RoadGraph、资源和完整回归证据均通过。

P10三对象中间证据`p05_scheme_a_p2_p3_p10_adjudication_20260724_01/_02`保留；
五对象正式证据根为`p05_scheme_a_p2_p3_p10_adjudication_20260724_03/_04`。五条裁决
manifest按group/case/object唯一join到Control/Treatment三seed，逐行保留旧真值、
allowed/preferred/clue、接受、合法性和fallback violation。正式两轮content
signature均为`ef779bfaf89c2bbfc0ef27d8e0e52cbd9075f145c9c54cf100c350bc0557d9cc`
且Run D匹配；训练、权重变化和几何写入均为0。

P12R正式证据根为
`p05_scheme_a_p2_p3_p12r_advance_right_audit_20260724_03/_04`。两轮共同content
signature为`320a8216a3e3592c9037f32300af7162b10d615277130d132bd410bb68e825e7`，
Run B reference match=true。每轮保存474条条件化真值、474条候选上限与474条
attachment审计；总体oracle为377/396，最差fold为21/24。训练、GPU、Movement、
T05提右label、T06推理候选、geometry写入、silent fix和T01–T12 mutation均为0；
完整P05回归253项通过。

P12R-R1正式证据根为
`p05_scheme_a_p2_p3_p12r_r1_endpoint_candidates_20260724_01/_02`。共同candidate
signature为`84344d11cdc168cea42cdaacd0c36f83f9f4b57e45dd01b802a9c35ce064f734`，
共同content signature为
`244b81957cf4eb39889fd88b61bdccb296707a901f8240580c46061aeb2a1e5b`，
Run B reference match=true。每轮保存候选、逐对象delta、endpoint证据、fold、
metrics、summary、输入manifest和8项artifact hash；Run B wall=`13.726s`、
峰值RSS=`446832640` bytes、GPU/训练=0。两轮artifact hash自校验均为0 mismatch，
完整P05回归257项通过。

P13-P0正式证据根为
`p05_scheme_a_p2_p3_p13_p0_oof_20260724_05/_06`。共同feature signature为
`949d15ff4d0a87cce8c1be0f742aa921110e08baf6a288af7b38730f6c9c4e53`，
共同content signature为
`c219be6609e0bc0a9dfccb9077a2a19de20f23fc10059839313dd28679fa3925`，
Run F reference match=true。两轮各15个NPZ checkpoint逐文件hash一致，27项
artifact各自hash自校验无异常；训练wall=`31.419/32.603s`，峰值RSS约
`414.9/414.5MB`，GPU=0。完整P05回归262项通过。

Target A v229–v241r1 正式研究证据位于
`outputs/_work/p05_neural_road_generation/`，模型 checkpoint 与运行工件
继续 ignored，不进入 Git。v231/v233 是两个独立 ordinary set-expansion
strict Case-OOF seed；首次 v234 因 USE 绕过 required-anchor 已废止。
v234r1 只接受二者业务状态、完整 Road set、逐 Road ownership/角色完全一致
且通过锚定前置门的结果。v235r2 对 AdvanceRight feature store 单次流式读取并索引 ordinary
OOF，feature/teacher/label 原文件使用 hardlink；v237/v239 是两个独立
final-state-conditioned AdvanceRight strict OOF seed；v240 只接受二者完整
条件方案交集；v241r1 对该交集执行 51 Case 最终 materializer 审计。

正式摘要工件：

- `target_a_ordinary_set_expansion_two_seed_release_gate_20260730_v234r1/summary.json`：
  自动 `113/3160`、全部 KEEP、selected business exact=`1.0`、
  unsafe/unverifiable=`0`；
- `target_a_advance_right_final_state_two_seed_release_gate_20260730_v240/summary.json`：
  自动 `414/474`、coverage=`0.873418`、plan exact=`1.0`、unsafe=`0`；
- `target_a_final_state_two_seed_materializer_audit_20260730_v241r1/summary.json`：
  414/414 自动提右可物化，Road/Node/attachment=`14,193/12,745/868`，
  ordinary USE/preflight fallback=0，hard failure/mutation/silent fix/
  content repair 均为 0。

每个正式 gate 均保存输入路径、size、SHA-256、fold mismatch、truth-use 和
raw-ID embedding 计数。v240r1 不平均两个 seed 的分数；v241r1 不修补内容，只
执行已确认配方或局部 fallback。当前证据不能外推到 ordinary USE 完整执行、
AdvanceRight RCSD_ONLY/MIXED_SPLICE 或完整 T03–T06 替代。

Target A v339–v350 的锚定结构证据继续位于
`outputs/_work/p05_neural_road_generation/`。用户确认
`T10:605415675 / SWSD semantic Junction 1633165` 的唯一正确锚定为
六条 RCSD Road 的 road-only split；附近 RCSD Node
`5391330021350570` 不可接受。该人工真值以权重 `1.0` 写入 label-only
store，推理 feature store 未改变。六条 Road 为：

- `5391329551450177`
- `5391329551450189`
- `5391329551450260`
- `5391329551450265`
- `5391330021350944`
- `5391330021350949`

v348r2 正式结构 decoder 为 794,892 参数，outer relation exact=
`0.841727`、type exact=`0.900568`、member exact=`0.685879`、
member macro F1=`0.777820`。v349r1 的 ordinal cardinality outer
exact=`0.832853`、member exact=`0.688761`、member macro F1=
`0.783146`；1633165 的 relation/type 与六条 Road 排序方向正确，但发布
cardinality 仍为 `1`。v350r1 因 threshold cardinality=`1` 与
expected-floor cardinality=`4` 不一致，只把该自动结果降级。对 v340 的
22 个自动候选最终接受 21 个，21/21 正确、危险 0，保留率 `95.45%`。
这是结构化锚定安全门禁的集成 GO，不是 Target A 整体 GO；ordinary USE、
RCSD_ONLY/MIXED_SPLICE 与完整 RoadGraph 仍须继续验收。

v351r5 将结构锚定 loss 接入 v327 Case-joint 共享 object embedding，模型
共 `24,926,558` 参数。ordinary free-plan exact=`0.868644`、member
exact=`0.779821`，但 relation/type exact 退化到
`0.727901/0.893274`；1633165 再次错选
`NODE:5391330021350570`，20 个自动候选中出现 1 个危险结果。该错误不能
解释为同类监督缺失：outer fold2 的训练范围包含 426 条
`B + ROAD + 多 Road`，其中 27 条为 6 Road。v350 与 v351 的自动结果取
交集后为 19/19 正确，但覆盖没有增加。证据支持保留原始锚定 evidence
分支、冻结已确认的 anchor proposal 语义，并只训练下游条件化 adapter；
不支持继续让 ordinary loss 直接微调锚定语义表示。

v352 将 raw-evidence teacher 压缩至 324,108 参数。总体
relation/type/member exact 为 `0.784173/0.872159/0.648415`，低于 v348，
但 held-out 1633165 首次实现 `B + ROAD + cardinality 6 + 六 Road exact`。
v353r3 冻结该 teacher、v327 anchor/base encoder 和 ordinary heads，只训练
25,696 参数条件化 stem；总参数 `24,929,538`，free/all-plan exact 提升到
`0.881356/0.917355`，anchor exact 维持 `0.801444` 且 inconsistency=0。
v354 迁移旧 inner 阈值并叠加 v350 正式门后，安全接受从 21 增至 24，
24/24 正确、全部 KEEP。outer-truth 零危险上限为 34，其中 USE 4，但该
阈值不可发布；必须补齐严格 inner 校准。冻结条件桥已经进入独立源码模块，
carrier loss 无法反向进入结构锚定 teacher。
