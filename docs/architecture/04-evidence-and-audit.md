# 04 证据与审计

## 文档定位

本文档说明项目级证据组织和内外网协作口径。具体模块输出文件、summary 字段和审计表结构，以模块契约和模块 architecture 为准。

## 当前正式口径

项目当前以文件证据包和结构化摘要作为主要协作方式：

- 本地 case 分析使用模块提供的文件证据包打包 / 解包能力。
- 端到端 case 分析由 T10 以 SWSD 语义路口 ID 与半径组织 Case 证据包；v1 支持 manifest-only、空间切片 Case 包、Case 级 replay、T06 数据漏斗、可选 T12 质检和上游反馈包。
- 内网执行结果通过 `summary`、`audit`、`review` 等文件化成果回传和分析。
- 当内网成果过大或需要聚焦问题时，由 Codex 提供命令或脚本，在内网成果中提炼关键信息后反哺外网分析。
- 文本片段只作为证据提炼结果，不再作为唯一正式交付协议。

## 证据要求

| 类型 | 要求 |
|---|---|
| 输入证据 | 能定位输入路径、数据版本、关键参数和运行环境。 |
| 中间证据 | 能解释候选选择、过滤、锚定、替换和回退原因。 |
| 输出证据 | 能定位正式成果、review-only 成果和被拒绝 / 待审计对象。 |
| 摘要证据 | 能快速回答总量、成功、失败、跳过、异常、性能和主要原因。 |
| 复核证据 | 能支持目视检查、GIS 叠加、拓扑抽查和问题 case 追踪。 |
| Case 证据包 | T10 以外部输入全集为主体，模块间中间产物只作为 handoff audit，不作为外部输入证据。 |
| 全量编排 manifest | T10 内网全量总控记录阶段顺序、显式输入输出、日志路径和最终 handoff；`t11` 固定位于 `t06_step3` 后，启用 T12 时顺序固定为 `t06_step3 -> t11 -> t12 -> t09`。F-RCSD 专用 profile 的 manifest 不登记未运行的 T08 stage。 |
| T12 质量审计证据 | 显式记录原始 1V1 F-RCSD、SWSD、RCSDIntersection、T05/T06 交叉证据、CRS、参数、运行环境、耗时，以及候选种类、canonical 候选、raw endpoint carrier、portal-constrained semantic carrier 的端点/内部 alias 门禁、F-RCSD 反向载体、SWSD 反向替代路径、自动 decision、confirmed/excluded 和可选 review override 分层输出。 |
| P05 M0 基准证据 | 显式记录限定 Case manifest、canonical baseline/run summary、artifact hash、标签权重、任务 mask、业务分组、fold、异常、Oracle/破坏测试、环境与性能；不得覆盖原始 Case 或 baseline。 |
| P05 M1 训练证据 | 显式记录推理时输入与 label-only artifact、候选操作、entity guard、train-only normalization、基线、模型参数/checkpoint、逐 Case 预测、固定 test 首次运行、环境与 RAM/VRAM；`silent_fix=false`。 |
| P05 M2R 证据 | 显式记录每个任务目标的可用性、trust tier、scope、artifact hash、CRS、mask、grouped OOF checkpoint/预测、free/constrained intervention、逐 Case GPKG 和资源；事后内容修复必须为零。 |
| P05 R2 证据 | Gate 1 显式记录 base/truth/edit/reconstructed lineage、Road/Node action coverage、精确 pointer、逐 Case GPKG 与归一化语义图；Gate 2/3 记录 query target、checkpoint、分 loss/梯度、grouped OOF、双解码、确定性和资源；oracle payload 必须 `label_only=true`，事后内容修复为零。正式 R2 结果为 Gate 1/2 通过、Gate 3 no-go；no-go 及失败 Case/GPKG 与成功证据同等保留。 |
| P05 PTO-P0 证据 | candidate run 记录策略 commit、POC 输入/输出 hash、候选来源/去重、Case/action/变量/约束数和 `truth_input_count=0`；solve run 固定引用 candidate manifest hash，再记录 label-only cost、coverage、objective/lower bound/gap、逐 Case GPKG/M0 指标、确定性和 replay/build/solve 资源。正式结果为 51 Case 语义门通过、candidate/solve signature 确定，proposal replay 性能门失败；成功与性能 no-go 证据同等保留。 |
| P05 JSG-PTO-P0 证据 | 两个不可变 run 分别记录 51 Case T01/T05/T06/R2 input hash、canonical JSG truth、对象覆盖、REVIEW/anomaly、语义 signature、carrier realization、编译 IR、逐 Case Road/Node GPKG/M0 指标、环境与性能；零实例类型单独报告，`label_only=true`、`content_repair=false`、`silent_fix=false`。 |
| P05 JSG-PTO-P1 证据 | candidate run 先记录零 truth EvidenceGraph、候选/group/lineage/hash；solve run 后记录 Oracle cost、PTO-A/PTO-B certificate、selected JSG、carrier feasibility、编译 GPKG/M0 指标和资源。candidate 与 selection signature 分离，历史 replay 成本单列。 |
| P05 方案 A 证据 | 不可变 run 记录 51 Case 的冻结 T01 Segment/Junction/PhysicalMovement 骨架、ADVANCE_RIGHT、策略三态基线、carrier-only 标签、RealityChangeClue、最小闭包 fallback、CRS/Road/Node/mainnode 审计、输入输出 hash 和资源；`skeleton_mutation_count=0`、`content_repair=false`、`silent_fix=false`。 |
| P05 Scheme-A-P1 证据 | candidate run 先记录零 truth strategy replay、Segment/Movement carrier candidates、feature 与 hash；dataset run 固定引用 candidate manifest 后再记录 label/fold/weight/reachability；OOF run 记录 3 seeds × 5 folds checkpoint/score/fallback/RoadGraph、train-only baseline、资源和确定性。candidate、label、model、selection 与 RoadGraph signature 必须分层。 |
| P05 Scheme-A-Dataset-P0 证据 | 不可变 run 记录九模块 role contract、741 sample、520 artifact、11,856 task target、T01 fallback/非 T01 proposal 来源、8,863 Segment 与51 Case Road/Node 可达性、49+2 safety、CRS/资源和七类内容 signature；候选 manifest 冻结后才连接 label-only truth。 |
| P05 Scheme-A-P2-P1 证据 | dataset run分层记录Segment/Node candidate、forbidden-feature、fold、label和compatibility Oracle；OOF run记录3 seeds × 5 folds词表、归一化、checkpoint、score、accepted/fallback、RoadGraph、GIS和资源；同seed重放单列内容signature。 |

JSG-PTO-P1 正式证据根为 `p05_jsg_p1_candidate_20260722_01/_02`、`p05_jsg_p1_oracle_20260722_02/_03` 与 `p05_jsg_p1_validation_20260722_01`。候选、PTO-A/PTO-B 选择、JSG 语义和 RoadGraph signature 双跑一致。

Scheme-A-P2-P1 正式证据根为 `p05_scheme_a_p2_p1_dataset_20260723_01`、`p05_scheme_a_p2_p1_oof_20260723_01/_02` 与 `p05_scheme_a_p2_p1_audit_20260723_02`。15个model state、checkpoint、词表、阈值、history、score、selection、effective selection和规范化RoadGraph内容双跑一致；`p05_scheme_a_p2_p1_audit_20260723_01`为Windows峰值内存API句柄声明错误导致的不完整开发审计，不进入正式结论。

Scheme-A-P2-P2-P0 正式证据根为 `p05_scheme_a_p2_p2_p0_audit_20260723_01/_02`。两轮只读相同 P2-P1 dataset/OOF，完整保存 8,863 条 truth-free safety signal、43 条 accepted-wrong 传播链、120 条 Review seed 记录、feature collision 与 score-only separability；六类输出内容 hash 全部一致。P2-P1 原始 artifact、阈值、RoadGraph 和 checkpoint 未修改。

Scheme-A-P2-P2-P1 正式证据根为 `p05_scheme_a_p2_p2_p1_oof_20260723_03/_04`。两轮保存 15 个 safety checkpoint、fold vocabulary/threshold/history、全部 Segment score/decision/label-only evaluation、effective Segment/Node selection 和 153 张 RoadGraph；determinism signature 均为 `8fbb0e25e706ca4edc064fc39356f8d6f7c904dbb505372db178f8780a681742`，路径归一化后的 RoadGraph index/signature 一致。`_01` 为 expected-failure guard 接入前中断工件，`_02` 为 Node QA 尚未按有效 Road 条件化的被替代工件，均不得作为正式指标来源。

Scheme-A-P2-P2-P2-P0 正式证据根为 `p05_scheme_a_p2_p2_p2_p0_audit_20260723_02/_04`。两轮独立重建 8,863×202 evidence、label-only join、9 error/40 Review ledger、10 个 fold probe checkpoint、decision/evaluation、conditioned Node selection 和 102 张 RoadGraph；规范化 determinism signature 均为 `b04485a71f05df15d36135a3193edcf8db150855ae24878b435faead028142e3`，Run B `reference_run_match=true`。`_01` 为全局 metric group 顺序修正前的无效诊断运行，`_03` 为资源墙钟移出 determinism payload 前的无效重放运行，不得作为正式结论来源。

Scheme-A-P2-P2-P2-P1 正式证据根为 `p05_scheme_a_p2_p2_p2_p1_attribution_20260723_01/_02`。两轮验证全部输入 manifest/hash，重建 9 error、13 residual unsafe accepted、40 Review 的 62 个唯一对象并输出逐对象 attribution、evidence candidate、source contract 和完整 lineage；规范化 determinism signature 均为 `b7abcf3c68f6d2ee6bc36ff2ba38d28d785c2e7461e8617b7eb6f5a4edcb3bce`，Run B `reference_run_match=true`。结论为 `40 INFERENCE_EVIDENCE_AVAILABLE / 22 SOURCE_FACT_BLOCKED / 0 UNOBSERVABLE_FALLBACK`。

Scheme-A-P2-P2-P2-P2 正式证据根为 `p05_scheme_a_p2_p2_p2_p2_audit_20260723_01/_02`。两轮验证 P0/P1/dataset/candidate/baseline manifest/hash，重算 8,863 Segment 的 carrier/clue 双指标，流式检查 22 个对象候选，并从冻结 Segment label、P1 candidate、PTO payload 和 lineage 重建 26 个初始 Node payload 冲突及 57 个 Junction fallback Segment。两轮规范化 signature 均为 `f50389a9d87522dd14bda8def879a815425a2cfb96f6f4cb99ff304cbba264d3`，Run B `reference_run_match=true`；wall=`88.48s/85.74s`、peak RSS约`1.67GB`、GPU=`0`。

Scheme-A-P2-P3-P0 正式证据根为 `p05_scheme_a_p2_p3_p0_oof_20260723_01/_02`。每轮记录 fold-local 词表/标准化、2.818M 参数模型、candidate/correctness/clue/auxiliary score、inner-validation threshold、held-out decision、effective Node/Segment carrier、Junction closure 和 153 张 seed×Case RoadGraph。两轮内容 signature 均为 `d6974ccaa140442412cf793d1379dc3a3232a1bba9b874207dcb12d7faddff59`，Run B `reference_run_match=true`；wall=`403.32s/373.59s`、peak RSS=`2.43GB/2.44GB`、GPU=`0`，Case inference p95=`0.0539s/0.0437s`。

Scheme-A-P2-P3-P1 正式证据根为 `p05_scheme_a_p2_p3_p1_audit_20260723_04/_05`。两轮核验 P2-P3-P0、P2-P2-P2-P2 和 Dataset-P0 manifest/hash，输出 3,049 个唯一重点对象的逐 seed ledger（cohort 分母为 fold2=`3,037`、stable false-use=`1`、clue-only=`13`）、17 类字段角色和 776 条 POC_Data 验证库存。五类核心工件逐字节一致，内容 signature 均为 `177344821e1b8b932a7b19bf16248ede1f6293d622c16570ba301ea9a7384311`，Run B `reference_run_match=true`；wall=`26.04s/26.13s`、peak RSS约`0.463GB`、GPU=`0`，Case审计p95=`0.103s/0.108s`。

Scheme-A-Dataset-P1 正式证据根为 `p05_scheme_a_dataset_p1_20260723_01/_02`。两轮各输出45条 Segment package lineage、8,863条唯一 Segment label scope、6条 expected-failure seed scope和9条历史指标失效记录；41个包按direct ID映射（5个Road drift单列审计），4个包按冻结Road集合精确分区为3/4/7/13个当前Segment。新标签/上下文分母=`6,275/2,588`，上下文标签泄漏=0；历史Case级联mask=`5,862`个seed-object行，修正后=0。四类核心工件逐字节一致，内容signature均为`bc848a8a0eeda04c14b358d505bc70258deaf36bb40cb617611ba7c4d205065c`，Run B `reference_run_match=true`；wall约`4.96s`、peak RSS约`0.362GB`、GPU=0、CRS=`EPSG:3857`、geometry read/write=0。

Scheme-A-P2-P3-P2 正式证据根为`p05_scheme_a_p2_p3_p2_oof_20260723_04/_05`。两轮各记录6,275个eligible OOF score/decision/evaluation、2,588个context-only fallback、全部8,863 Segment effective selection、15个fold模型和153张seed×Case RoadGraph；scope、score、decision、effective和closure核心工件逐字节一致，规范化signature均为`e1bc5b5e55ddeaba8f87cbaa36f8a6261461e206a72aa8d240385c46c30d534f`，Run 05 `reference_run_match=true`。两轮wall约`305.92s/289.69s`、peak RSS约`2.44/2.43GB`、GPU=0；CRS=`EPSG:3857`，geometry read/write、context auto accept、Case非目标级联、骨架mutation、repair和silent fix均为0。中断的空Run 03及signature修正前Run 01/02只作诊断，不作为正式指标来源。

Scheme-A-P2-P3-P3正式证据根为`p05_scheme_a_p2_p3_p3_audit_20260723_02/_03`。两轮保存6,275条安全资格ledger、120条硬门决策、三seed全量effective selection、153张RoadGraph和残余false-use held-out近邻审计；signature均为`0f7d4ee09835afb408efa986f54ed980ca941484a3ca62c7f3805f8d684fa97c`，Run B `reference_run_match=true`。wall约`107.23s/130.52s`、peak RSS约`1.82GB`、GPU=0；训练、阈值修改、geometry read/write、T06 inference、Movement、repair、silent fix和骨架mutation均为0。Run 01使用修正前对象级accepted口径，只作诊断，不作为正式结论来源。

JSG-PTO-P2 使用 dataset 与 OOF 两级不可变 run。dataset 记录 P1/M0 manifest/hash、fold、label weight、feature vocabulary 和 forbidden-token audit；OOF 记录每 fold 模型权重、全部候选 score、可重建 explanation、margin/confidence/uncertainty、selected JSG/RoadGraph、GIS 指标与资源。训练 Case 与 held-out Case 必须逐 fold 审计为零交集。

JSG-PTO-P2 正式证据根为 `p05_jsg_p2_dataset_20260722_02`、`p05_jsg_p2_oof_20260722_02/_03` 与 `p05_jsg_p2_validation_20260722_01`。51 Case、712,799 candidates、5 folds 的 forbidden feature hit 为零；两轮 V0/V1 score、PTO-A/PTO-B 与 RoadGraph signature 一致，204 个输出 GPKG 的 CRS/几何审计通过。P2 结论为可解释基线 NO-GO、P3 技术合理性成立；P3 后续已获独立授权。

JSG-PTO-P3 使用 context dataset、fold/seed model、OOF/seed run 和 final validation 四级不可变证据。正式证据根为 `p05_jsg_p3_dataset_20260722_04`、`p05_jsg_p3_formal_20260722_01`、同 seed 对照 `p05_jsg_p3_dev_seed17_20260722_03` 与 `p05_jsg_p3_validation_20260722_02`。51 Case、191,331 groups、712,799 candidates 的 truth/ID/绝对坐标泄漏为零；3 seeds × 5 folds、同 seed双跑、PTO/RoadGraph/GIS/资源审计完整。最终 `P3_MODEL_NO_GO` 只作为历史模型结论，不能覆盖当前方案 A 的本体和门禁。

JSG-PTO-P0 的正式证据为 `p05_jsg_p0_20260721_04` 与 `p05_jsg_p0_20260721_05`。两轮各 51 Case，semantic/compiled/provenance signature 一致，逐 Case 选择字段差异为零；完整验收摘要与 determinism audit 位于对应 SpecKit。

P05 方案 A baseline 的正式证据为 `p05_scheme_a_baseline_20260722_12` 与 `_13`；它们按“Segment 不连带 Movement”口径取代 `_10/_11`，旧 run 仅保留历史证据。两轮各覆盖 51 Case、8,863 Segment、474 ADVANCE_RIGHT、24,779 PhysicalMovement，骨架 mutation 为零；五类业务 signature 一致，artifact hash 全量复核通过。完整业务指标、40 个不可发布 ADVANCE_RIGHT、913 条 clue 与资源证据见 `specs/p05-scheme-a-carrier-baseline-20260722/validation-summary.md`。

Scheme-A-P1 RoadGraph 审计必须逐 Case记录 `LEGAL` 或 `EXPECTED_FAIL` 终态。`T10:74155468` 与 `T10:609214532` 的 SWSD baseline 端点缺失证据、`RealityChangeClue`、禁止发布结果和稳定 failure signature 必须完整保留；其余49 Case必须记录合法图 signature。任何未登记失败都属于 hard failure，不能并入 expected-failure 分子。

Scheme-A-P1 正式证据为 `p05_scheme_a_p1_candidate_20260722_09/_10`、`p05_scheme_a_p1_dataset_20260722_06/_07`、`p05_scheme_a_p1_oof_formal_20260722_01` 与 seed 17重放 `_02`。candidate/dataset、model state、score、prediction、fallback 和51个 RoadGraph 内容确定性已通过；正式结论 `P05_SCHEME_A_P1_MODEL_NO_GO` 及 QGIS/资源证据见对应 SpecKit `validation-summary.md`。

Scheme-A-Dataset-P0 正式证据为 `p05_scheme_a_dataset_p0_20260722_04/_05` 与 `p05_scheme_a_dataset_p0_determinism_20260722_02.json`。两轮 decision 均为 `P05_SCHEME_A_DATASET_P0_GO`，module role、sample、artifact、task、candidate source、Segment reachability 和 Case reachability 七类 signature 完全一致；两轮 wall 为 `5.159s/5.123s`，峰值 RSS 为 `281,288,704/295,366,656 bytes`，无需 GPU。

## 内外网协作边界

- Agent 默认可执行外网验证、外网数据检查和当前本地工作区操作。
- 内网环境、内网数据拉取和内网命令默认由用户执行，除非当轮明确提供可执行能力。
- Agent 不得把未实际执行的内网操作表述为已完成。
- 内网问题可通过 summary、audit、review、case bundle 和用户执行脚本的输出反哺分析。

## 历史文本协议

旧 `TEXT_QC_BUNDLE v1` 是早期文本粘贴回传方案，当前已退出正式项目协议，仅作为历史兼容工具和入口登记事实保留。若需要追溯旧方案，见 `docs/archive/ARTIFACT_PROTOCOL_RETIRED.md`。

## P05 P2-P3-P4 正式证据

正式双跑为 `p05_scheme_a_p2_p3_p4_rebaseline_20260723_01/_02`，规范化
signature 均为 `3f2f2399a11a1b4675bc5b30d29043e764bd7991a71c2d06f6fccbdde265ed37`，
Run B `reference_run_match=true`。工件记录 8,863 个 scope-first Segment 标签、
28,240 个 Node 标签、10 个初始冲突、21 个 Junction fallback Segment、436 个
旧/新标签 delta 和三 seed 指标重算；未重建 RoadGraph，只校验 P2-P3-P3 的
49 `LEGAL` + 2 `EXPECTED_FAIL` 工件 hash。两轮 wall 约 129.26/127.38 秒，
峰值 RSS 约 2.25 GiB，GPU、训练、geometry、Movement、repair、mutation 均为 0。

## P05 P2-P3-P5 正式证据

训练数据双跑为 `p05_scheme_a_p2_p3_p5_dataset_20260723_01/_02`，共同 signature
为 `5efbe66318f818dd705dbd10acd48366e328d2f8e61bae51812a46d5cf61fb46`。
正式 OOF 为 `p05_scheme_a_p2_p3_p5_oof_20260723_01/_02`，共同 signature 为
`de6c92d0bde80f2d0690af76a340931d802cdf5def7bc63601406040720dce02`，
Run B 与训练引擎 reference match 均为 true。全部声明输出 size/SHA-256 已复核，
三 seed × 5 folds、26,589 条 all-Segment decision、153 张 RoadGraph 与资源证据
完整。正式 decision 为 `P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`，不是审计失败。

## P05 P2-P3-P6 正式证据

正式双跑为 `p05_scheme_a_p2_p3_p6_attribution_20260724_03/_04`，共同 signature
为 `e753bb817be16841adf4832dbfe3d68ed579e7b851364dd54a4569bbbf180a1c`，
Run B reference match=true。工件覆盖18,825条seed-object attribution、3,587条
clue error、双层指标、两个expected-failure发布审计和18组稳定对象train-only邻域。
wall为18.97/16.50秒，峰值RSS为0.621/0.619GiB，GPU、训练、调阈值、geometry、
Movement、T06 inference、repair和mutation均为0。正式decision为
`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`。

## P05 P2-P3-P7 正式证据

正式证据根为
`p05_scheme_a_p2_p3_p7_audit_20260724_01/_02`，共同signature为
`3154e4bb6af8358efcfff6f6dd5ed7ca90189f0d915d654d86fb1cbcdac2bcee`，
Run B `reference_run_match=true`且representation signature一致。每轮输出6,275条
602维表征、feature/source/neighborhood/calibration审计和完整lineage；52条T01
inventory路径hash通过，51个eligible Case GPKG读取均为`EPSG:3857`，
geometry read=51、write/transform=0。单轮wall约11.24秒、
peak RSS约0.559GiB、GPU=0；训练、calibrator fit、阈值调优、Movement feature、
T03–T06推理、repair、silent fix和骨架mutation均为0。

## P05 P2-P3-P8 正式证据

正式证据根为
`p05_scheme_a_p2_p3_p8_source_audit_20260724_02/_03`，共同signature为
`4b3002494b6c33400907751aca44c375481a3602bb3cff1f8cad45bce8852508`，
Run B `reference_run_match=true`。每轮核验663个T03/T04核心工件、2,710条来源
事实和6,275条Segment applicability；255个来源GPKG layer与51个T01 Segment GPKG
均为`EPSG:3857`。单轮wall约48秒、peak RSS约0.274GiB、GPU=0；训练、拟合、调阈值、
geometry write/transform、空间join、silent fix和骨架mutation均为0。

P9正式证据根为`p05_scheme_a_p2_p3_p9_oof_20260724_01/_02`。两轮均分开保存
Control/Treatment、source-applicable/`NOT_APPLICABLE`、scorer/final和RoadGraph
工件；规范化signature均为
`e8f19d737a27e5789ea861e18730f11d192a9b97635ca25a8fd4ac299f37871b`，
Run B `reference_run_match=true`。无来源score/decision差异、Clue概率差异、
conflict、repair、mutation均为0；完整P05回归为242 passed。

P10三对象中间证据`p05_scheme_a_p2_p3_p10_adjudication_20260724_01/_02`保留；
五对象正式证据根为`p05_scheme_a_p2_p3_p10_adjudication_20260724_03/_04`。输入固定为
P9 Run B五个hash校验工件和五条对象级人工裁决manifest；输出保留逐arm/seed的旧真值、
allowed/preferred/clue、选择、接受、fallback violation和裁决依据。正式两轮content
signature均为`ef779bfaf89c2bbfc0ef27d8e0e52cbd9075f145c9c54cf100c350bc0557d9cc`，
Run D匹配；训练、模型权重变化、Movement decision和geometry write均为0，完整P05
回归245项通过。
