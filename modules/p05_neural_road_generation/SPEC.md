# SPEC：P05 神经网络 F-RCSD Road 直出 POC

## 1. 模块定位

P05 是 `Active POC / 成果模块`。其长期研究目标是用神经网络从业务证据直接生成符合 T06 Step3 语义的 F-RCSD Road/Node；它不替代 T01-T06 正式业务契约，也不把实验指标提升为生产质量口径。

当前正式研究路线是 2026-07-22 授权的方案 A：冻结 T01 Segment 集合、Junction—Segment 关系和 PhysicalMovement 存在性，模型只负责 carrier 候选评分/排序、Road/Node carrier 选择、异常线索和失败概率。模型不得新增、删除、合并、拆分 Segment，不得改变 Junction 归属或 PhysicalMovement 存在性，不得使用 PTO-A 改写业务骨架。

方案 A baseline 已于 2026-07-22 完成。按“Segment 不连带 Movement”口径重跑的正式 Run A/B 为 `p05_scheme_a_baseline_20260722_12/_13`：51 Case、8,863 Segment、474 ADVANCE_RIGHT、24,779 PhysicalMovement 全量覆盖，骨架 mutation 为零，五类业务 signature 完全一致；修正前 `_10/_11` 只保留为历史证据。该完成状态只放行冻结骨架下的 carrier 数据、clue 和 fallback 合同，不代表神经 scorer 已训练或可接入生产。

`P05-Scheme-A-P1` 已于 2026-07-22 完成，正式判定 **`P05_SCHEME_A_P1_MODEL_NO_GO`**。candidate/dataset Gate 0、同 seed 确定性、Gate 4 RoadGraph 安全和 Gate 5资源通过；三 seed Segment macro-F1 为 `1.0000/1.0000/0.9869`、Movement exact 均为 `1.0`，但 accepted coverage 为 `0.3637/0.3589/0.3533`，seed 29/43 anomaly precision 为 `0.7684/0.7472`。truth-exact 执行 coverage 也只有 `0.36933`，主要问题是逐对象 carrier truth 在整图组合时存在真实跨来源冲突。本结论不授权生产接入。

`P05-Scheme-A-P2-P0` 已于 2026-07-22 完成，正式结论为 **`P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO`**。本阶段未训练模型，Movement candidate/decision/evaluation 均为零；Segment 独立 Road carrier 与 JunctionUnit 共享 Node carrier 已完成 truth-free candidate 和 label-only Oracle 隔离。正式 Candidate A/B 为 `p05_scheme_a_p2_candidate_20260722_01/_02`，正式 Oracle A/B 为 `p05_scheme_a_p2_oracle_20260722_05/_06`；两轮 candidate、Segment、Junction、clue、RoadGraph 和指标 signature 一致。joint truth exact=`4,844/8,863=0.546542`，但当时受限 carrier bundle 的 `USE_RCSD` truth retention=`363/2,190=0.165753`，低于 `0.50`，因此该阶段未启动 P2-P1 训练；其数据可达性含义以后续 Dataset-P0 为准。

## 9.12 Scheme-A-Dataset-P0 已完成结论

`P05-Scheme-A-Dataset-P0` 已于 2026-07-22 完成，正式结论为 **`P05_SCHEME_A_DATASET_P0_GO`**。正式 Run A/B `p05_scheme_a_dataset_p0_20260722_04/_05` 对 741 sample、520 artifact、11,856 task target、51 Case 和 8,863 Segment 建立了模块语义化训练合同；T01 RCSD label、truth-derived candidate、Movement candidate/decision/evaluation 和骨架 mutation 均为零，T07 固定 `DRIVEZONE_ONLY`。2,190/2,190 `USE_RCSD` Segment 的目标 Road 均由非 T01 candidate 可达；8,823 个可用 Segment Road、T06 final Road `23,224/23,224`、final Node `27,553/27,553` 和联合 exact 均为 `1.0`，40 个不可确认 ADVANCE_RIGHT 保持 mask/归因，RoadGraph 为 49 `LEGAL` + 2 `EXPECTED_FAIL`。七类内容 signature 双跑一致。历史 P2-P0 的 `0.165753` 继续保留，但只描述其受限 carrier bundle 的联合安全保留能力，不再解释为 Case 数据或正确 RCSD carrier 不足。

## 9.13 Scheme-A-P2-P1 已完成结论

P2-P1已按用户批准的Road endpoint/JunctionUnit条件化Node口径完成，正式结论为 **`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`**。正式dataset包含8,863 Segment、28,240 Node group、23,758/79,334个Segment/Node candidate和77,964条truth-free兼容边；PTO Oracle不作Node标签，Segment/Node reachability与51 Case compatibility Oracle均为1.0。三seed JunctionUnit Node exact=`0.9963/0.9966/0.9981`、ECE均通过，且每seed49 `LEGAL` + 2 `EXPECTED_FAIL`；但错误接受=`17/9/17`，总体coverage=`0.3102/0.3502/0.5150`、`USE_RCSD` coverage=`0.0999/0.0027/0.2658`，anomaly precision=`0.3460/0.2851/0.3936`，seed43 Segment macro-F1=`0.8190`。双跑确定性、GIS/CRS、资源、体量和入口审计通过。Movement继续为零，T07固定`DRIVEZONE_ONLY`；当前模型不得自动替换SWSD、接在线proposal或生产。

## 9.14 Scheme-A-P2-P2-P0 已完成结论

P2-P2-P0已完成并判定 **`P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO`**。本阶段未训练模型，只读P2-P1正式dataset/OOF，将`17/9/17`个对象级错误接受完整追踪为raw Segment错误`12/10/37`、accepted Segment根错误`2/0/3`以及Node传播/fallback口径。8个稳定`KEEP_SWSD -> USE_RCSD`无法用单一confidence/margin/entropy/anomaly阈值在零错误下保留超过`0.200275`的正确`USE_RCSD`；8,863 Segment的完整truth-free feature跨truth精确碰撞为0，40 Review自动发布始终为0。正式审计双跑内容一致，49个可发布Case的最终有效Segment→Node requirement无conflict/target mismatch。该阶段当时只给出 safety-head 技术启动理由；后续 P2-P2-P1 已另行授权并完成，其结果见 9.15。

## 9.15 Scheme-A-P2-P2-P1 已完成结论

P2-P2-P1 已按用户授权完成并判定 **`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`**。410,786 参数 Segment-only safety head 只接受/回退冻结 P2-P1 proposal，不改选 candidate；三 safety seed 的 accepted wrong/总体 coverage/USE coverage 为`5/0.374817/0.431714`、`0/0.069841/0.066911`、`4/0.296288/0.380843`，没有 seed 同时满足零错误和两个 0.50 覆盖门。40 Review 自动发布为0。Node 条件化和 RoadGraph gate 均通过，每seed为49 `LEGAL` +2 `EXPECTED_FAIL`，effective requirement conflict/mismatch与unexpected failure为0。正式Run A/B内容确定；Movement继续为0、T07继续`DRIVEZONE_ONLY`。本阶段不授权在线proposal、生产接入或T01-T12改造。

## 9.16 Scheme-A-P2-P2-P2-P0 已完成结论

P2-P2-P2-P0 已完成并判定 **`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`**。本阶段未修改P2-P1/P2-P2-P1模型，只把T01冻结骨架、T07 `DRIVEZONE_ONLY`、truth-free proposal/KEEP Road有向结构差、Segment→Node compatibility/Junction共享压力和三base-seed OOF统计冻结成202维evidence；T03/T04/T05/T06 model-input、truth/ID/绝对坐标和Movement feature均为0。203参数线性probe放过2/9错误proposal；15,105参数浅层MLP的全局accepted wrong/Review auto为`0/0`，coverage/USE coverage为`0.548686/0.755729`，但unsafe recall=`0.994191`且0/5 held-out fold通过完整门。两probe的conditioned Node与RoadGraph均为49 `LEGAL`+2 `EXPECTED_FAIL`，conflict/mismatch/新增失败为0。正式Run A/B `p05_scheme_a_p2_p2_p2_p0_audit_20260723_02/_04`的规范化signature均为`b04485a71f05df15d36135a3193edcf8db150855ae24878b435faead028142e3`。当前仅保留离线排序、Review和RealityChangeClue辅助价值；自动发布研究必须引入新的推理期信息源或独立预训练表征，label-only字段提升须用户二次确认。

## 9.17 Scheme-A-P2-P2-P2-P1 已完成结论

P2-P2-P2-P1 已完成并判定 **`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`**。本阶段不训练模型、不调整阈值，对 9 个一致错误 proposal、浅层 MLP 残留 13 个 unsafe accepted 和 40 Review 的 62 个唯一对象完成直接根因归因。40 Review 全部是冻结 T01 `ADVANCE_RIGHT access_valid=false`，保留既有确定性 fallback；其余 22 个对象为 16 个 truth-conditioned Junction fallback、5 个 T06 `RCSD_CARRIER_ROAD_MISSING` 和 1 个 T06 `MIXED_CARRIER`，直接来源均只允许在 label/evaluation 层使用。完全不可观测对象为 0，但新增且已授权的直接推理证据为 0。P2-P1 joint fallback 的任一 seed unsafe precision 仅 `0.208295~0.298102`，只能作为辅助信号。正式 Run A/B `p05_scheme_a_p2_p2_p2_p1_attribution_20260723_01/_02` signature 均为 `b7abcf3c68f6d2ee6bc36ff2ba38d28d785c2e7461e8617b7eb6f5a4edcb3bce`。本结论不授权提升 T06 终态事实、训练模型、修改 T01–T12 或接入生产。

## 9.18 Scheme-A-P2-P2-P2-P2 已完成结论

P2-P2-P2-P2 已完成并判定 **`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`**。本阶段将旧 unsafe 指标拆成 Road/Carrier 安全与 RealityChangeClue 可见性：浅层 MLP 全局 carrier wrong accepted=`0`、carrier safety recall=`1.0`，13 个残留对象全部是正确 `KEEP_SWSD` 后 clue 漏报；但 cross-case 只有 2/5 fold 通过覆盖率门。22/22 正确候选可达，源路径为 16 个 Junction 一致性依赖、5 个 no-USE candidate 的 safe KEEP+clue head、1 个已有 `MIXED_CARRIER` 候选的评分错误。初始 26 个 Node payload 冲突闭包为 57 个 Junction fallback Segment，冻结 target 为 `36 KEEP/13 MIXED/8 USE`。正式 Run A/B `p05_scheme_a_p2_p2_p2_p2_audit_20260723_01/_02` signature 均为 `f50389a9d87522dd14bda8def879a815425a2cfb96f6f4cb99ff304cbba264d3`。本阶段只证明分层模型路线存在，不放行现有浅层模型、训练、源角色提升、生产接入或 T01–T12 修改。

## 9.19 Scheme-A-P2-P3-P0 已完成结论

P2-P3-P0 已完成并判定 **`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`**。2.818M 参数分层模型按 3 seeds × 5 Case folds 训练 carrier candidate/correctness、独立 RealityChangeClue 和 7 个 T03/T04/T05 label-only auxiliary target；推理只使用 P2-P1 truth-free candidate 与冻结 202 维 T01/T07/结构证据。三个 seed 的通用 Node compatibility/Junction decoder 均得到 49 `LEGAL` + 2 `EXPECTED_FAIL`，conflict、mismatch、repair、silent fix 和 skeleton mutation 为零。业务门仍失败：carrier wrong accepted=`1/1/0`，seed 317 总体/USE coverage=`0.1327/0.2333`，fold 2 三 seed coverage 均约 `0.29`；clue recall=`0.9844/0.9852/0.9987`，13 个 clue-only 捕获=`9/8/12`。正式 Run A/B `p05_scheme_a_p2_p3_p0_oof_20260723_01/_02` signature 均为 `d6974ccaa140442412cf793d1379dc3a3232a1bba9b874207dcb12d7faddff59`，Run B `reference_run_match=true`。结论不授权自动替换、在线/生产接入、T01–T12 修改或在当前 held-out 51 Case 上继续调参重报 GO。

## 9.20 Scheme-A-P2-P3-P1 已完成结论

P2-P3-P1 已完成并判定 **`P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`**。本阶段未训练模型、未调整阈值。稳定 false-use 是 `T10-Error:1029603_1043020` 的 Segment `1049466_991125`，seed 311/313 均错误接受 `USE_RCSD`，其直接原因是只存在于 label-only 联合真值层的 `TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE`。13 个 clue-only 对象中 8 个同属 Junction fallback、5 个为 `T06_RCSD_CARRIER_ROAD_MISSING`，模型捕获为 `9/8/12`；T03/T04/T05 auxiliary 只提供相关监督，不能独立生成上述直接事实。

fold 2 的 3,037 个 Segment 中，`T10:609214532` 贡献 1,795 个 `expected_swsd_baseline_failure`。在全部 Segment 分母上，即使其余对象全部接受，coverage 理论上限也只有 `1,242/3,037=0.408956`，所以 frozen `>=0.50` 门在该 fold 数学不可达；eligible-only coverage 为 `0.714976/0.712560/0.706119`，但 `USE_RCSD` coverage 仍为 `0.323923/0.323923/0.319465`。该诊断不自动改变度量合同，expected failure 继续进入安全、fallback 和 clue 分母。

字段审计把 17 类潜在证据归为 9 `INFERENCE_ALLOWED`、4 `LABEL_ONLY`、3 `FORBIDDEN_LEAKAGE`、1 `UNAVAILABLE`，违规提升为零。T07 Step1 `has_evd` 正式为 DriveZone-only；RCSDIntersection 只在 Step2 产生 `is_anchor/anchor_reason`，两者都是已使用的合法 T06 前证据，不是新增直接事实。POC_Data 的 741 个登记样本已全部进入现有辅助监督、51 个端到端 Case或批准排除；额外 11 个 T10 anchor slice、9 个 T06 local diagnostic、5 个 T01 bundle、3 个 T02 anchor 和7个 legacy Intersection bundle均不构成独立冻结RoadGraph验证集。

正式 Run A/B `p05_scheme_a_p2_p3_p1_audit_20260723_04/_05` 的归因、字段角色、fold 2统计、验证库存和POC scope逐字节一致，signature均为`177344821e1b8b932a7b19bf16248ede1f6293d622c16570ba301ea9a7384311`，Run B `reference_run_match=true`。新增合法直接证据=`0`、独立冻结验证集=`0`，因此不启动下一轮训练；该结论不否定神经逐对象评分价值，也不授权修改T01–T12、源角色、正式入口或生产接入。

## 9.21 Scheme-A-Dataset-P1 已完成结论

Dataset-P1 已完成并判定 **`P05_SCHEME_A_DATASET_P1_GO`**。T10 继续作为
Case-level truth；T10-Error/T10-Error-2 只允许 manifest
`scope.swsd_segment_id` 对应当前 Segment或 lineage 可证明的 T01 后继 Segment作为
标签，包内其它 Segment固定为 `CONTEXT_ONLY_MASKED`，`0.3` 只作 context input。

45 个启用包全部映射成功：41 个 direct ID，其中 5 个旧包 Road 清单与当前 T01
存在 drift 但业务 ID 未变；另 4 个 ID 已消失的目标通过冻结 Road集合无遗漏、
无重复地分区到 3/4/7/13 个当前 Segment。8,863 个当前 Segment的新标签/上下文
分母为 `6,275/2,588`，其中 T10 Case truth=`6,207`、Segment 包
target/descendant=`68`，上下文进入 label/loss/metric 数为 0。

`T10:609214532` 与 `T10:74155468` 仍为 Case `EXPECTED_FAIL` 并禁止发布，但
每个 Case/seed 只对一个 `failure_group_id` 执行对象级失败/fallback，不再将全 Case
1,795/159 个 Segment级联覆盖为拒绝。正式 Run A/B
`p05_scheme_a_dataset_p1_20260723_01/_02` signature 均为
`bc848a8a0eeda04c14b358d505bc70258deaf36bb40cb617611ba7c4d205065c`，
Run B `reference_run_match=true`。旧 8,863 标签分母下的模型指标、stable-wrong
和 fold 2 coverage-ceiling 解释只作历史证据；冻结骨架、candidate inventory、
通用图合法性与 49+2 安全事实继续保留。本阶段未训练模型。

## 9.22 Scheme-A-P2-P3-P2 已完成结论

P2-P3-P2 已按用户继续授权完成并判定
**`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`**。本阶段复用 P2-P3-P0 的网络、202维
T01/T07推理证据、超参数、3 seeds × 5 Case folds与通用Node/Junction闭包，只把
训练、inner threshold、held-out评价重建为Dataset-P1的6,275个eligible Segment。
2,588个context-only Segment不进入任何监督、阈值、校准或metric，整图执行时固定
`KEEP_SWSD` fallback；两个expected-failure Case只对各自登记的failure group局部
fallback。

三个seed的accepted wrong/Review auto/总体coverage/USE coverage分别为
`1/0/0.353970/0.633867`、`13/12/0.549479/0.703661`、
`0/0/0.150601/0.275744`。clue recall/precision/macro-F1分别为
`0.980524/0.543964/0.775080`、`0.867025/0.997682/0.953598`、
`0.995970/0.368447/0.587883`。可靠目标
`T10-Error-2:89387685_507565991` 在seed311/313均被错误
`KEEP_SWSD→USE_RCSD`；seed313另将`T10:605415675`的12个
`ADVANCE_RIGHT` Review错误自动接受为`KEEP_SWSD`。

每seed的RoadGraph仍精确为49 `LEGAL`+2 `EXPECTED_FAIL`；2,588 context的自动
接受、expected-failure非目标级联、requirement conflict、Node mismatch、repair、
silent fix与skeleton mutation均为0。正式Run
`p05_scheme_a_p2_p3_p2_oof_20260723_04/_05`的规范化signature均为
`e1bc5b5e55ddeaba8f87cbaa36f8a6261461e206a72aa8d240385c46c30d534f`，
Run 05 `reference_run_match=true`；参数量为`2,818,234–2,818,810`，peak RSS约
`2.43GB`、GPU为0。

该结果证明Dataset-P1标签修正是必要条件，但不是当前基础模型GO的充分条件。
本地数据已经足以稳定暴露一个可靠target false-use和Review少数类失控；当前不得
挑选seed317、在已见held-out上继续调阈值/epoch或自动发布。后续若继续研究，应先
把Review/ADVANCE_RIGHT硬安全资格与carrier scorer解耦，并为剩余可靠target
false-use引入新的、T06前可用的表征或独立验证合同；不得把T06 final事实直接提升为
推理输入。

## 9.23 Scheme-A-P2-P3-P3 已完成结论

P2-P3-P3已完成并判定
**`P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED`**。
本阶段未训练模型、未改变阈值。6,275个eligible对象与方案A冻结Segment清单全量
1:1匹配；恰好40个`access_valid=false`对象全部是
`ADVANCE_RIGHT + REVIEW_FALLBACK`，非Review命中为0。把该T01冻结事实作为
scorer后、通用Junction/Node闭包前的硬安全资格后，三seed共120条Review决策全部
回退，Review auto=`0/0/0`，最终accepted wrong=`1/1/0`；2,588个context-only、
两个局部expected-failure和每seed49 `LEGAL`+2 `EXPECTED_FAIL`均保持不变。

剩余可靠对象
`SCHEME_A_P1:SEGMENT:T10-Error-2:89387685_507565991:89387685_507565991`
在三个seed均错误选择`USE_RCSD`，score margin为
`13.58/12.87/15.99`。按每个seed的held-out训练Case独立标准化后，前20个202维
近邻合计60个全部是`USE_RCSD`真值。现有表征没有提供支持该对象跨Case正确泛化的
关系结构。

正式Run `p05_scheme_a_p2_p3_p3_audit_20260723_02/_03`的规范化signature均为
`0f7d4ee09835afb408efa986f54ed980ca941484a3ca62c7f3805f8d684fa97c`，
Run B `reference_run_match=true`；wall约`107.23s/130.52s`、peak RSS约
`1.82GB`、GPU为0。下一阶段应先建设并冻结T06之前可用的新关系/共享上下文表征，
再决定继续逐对象scorer还是采用跨Segment/Junction图模型；不得从单Case创建业务
强规则、提升T06终态字段、继续训练同一表征或进入自动发布。

P1 RoadGraph hard gate 按51 Case确定终态验收。`T10:74155468`（缺端点 Node `953982`）与 `T10:609214532`（缺端点 Node `987665`）是冻结 SWSD baseline 的登记预期失败，必须输出 `FAIL + RealityChangeClue`、不得发布或修复；其余49 Case必须全部合法。两个 Case不从模型、fallback或异常指标分母剔除，任何额外 RoadGraph 失败均为 Gate 4失败。

普通提右统一为 `segment_type=ADVANCE_RIGHT` 的 Segment，必须以 `source_segment_access/target_segment_access` 直接连接两个普通 Segment、拥有独立 Road并保留真实 `junc_nodes`；当前业务层废止 `SegmentConnector`。若 T01 未显式给出 access，只允许由独立 Road 的唯一有向端点和端点处唯一普通 Segment owner 形成可追溯 access；端点或 owner 不唯一时不得猜测，必须生成 `RealityChangeClue` 并失败/fallback。Junction 冲突回退关联全部 Segment，Segment 冲突只回退该 Segment，且不得自动改变或回退相关 PhysicalMovement；Movement 仅因自身问题回退，carrier 确实共享或影响 Junction 内部拓扑时才升级为 Junction fallback，否则保持单 Movement fallback。fallback 后不满足 access、独立 Road、Road/Node 引用、方向、CRS、拓扑或 lineage 时仍为失败。

本文件后续 M1/M2R/R2/PTO/JSG-PTO-P0/P1/P2/P3 章节全部是历史实验事实，用于追溯表示、模型、候选、编译和资源结论，不再定义当前业务本体或当前门禁。旧 Connector 与 Review/Unknown 指标必须在方案 A carrier-only 标签下重建。

M0 已回答两个问题：现有本地 Case 能否形成可信训练真值，以及后续模型输出能否被同一把可复现的尺子评价。M1 使用冻结 M0 run 建立无泄漏候选 RoadGraph、规则/MLP 基线和首个小型图神经网络，并已完成最终 Road 操作与 T06 语义 Road/Node 物化验证。M1 未达门槛后，用户于 2026-07-21 授权 M2R 重新立项：不再把 T03/T04/T05 只当输入 artifact，而是由同一神经系统学习 T03、T04、T05、T06 分层语义，T07 作为可选辅助任务。

## 2. M1 已完成目标与结论

1. 模型输入只来自推理时可用的 T01/T03/T04/T05/T07 artifact；T06 Road/Node/relation 仅用于监督和评价。
2. 候选 Road 由 T01 Road 与 T05 RCSD Road 并集形成；神经网络预测 `DROP/KEEP/SPLIT_1/SPLIT_2/SPLIT_3`、方向、source 和切分几何/端点。
3. 确定性物化器只执行模型指定操作、schema 写出和 hard validation，不执行 T06 业务 fallback 或 silent fix。
4. 在 M0 Case split 之上增加实体泄漏门禁；跨 split 重复 Road及其一跳邻域只允许归属最高优先级集合。
5. 开发期使用 train/validation 和 group CV；模型与阈值冻结后才运行固定 test，并单独报告标准 T10 shadow holdout。

M1 仍是可学习性 POC，不进入正式主链，也不等价于替代 T06。

M1 已于 2026-07-21 完成一次性固定 test。最终 Road F1 `0.6436`、相对 keep-all `-0.0084`、最差 Case `0.4949`，5/5 Case 均存在有向拓扑差异，因此本里程碑状态为 `failed / M2 no-go`。方向与 source 准确率超过 `0.99`，说明属性头可学习，但不能抵消 Road 召回、操作选择和拓扑闭合不足。

## 3. M2R 当前目标

1. 模型必须学习 T03、T04、T05、T06 四个任务；T07 可作为可关闭的辅助 Head，T01 保持基础输入边界。
2. 单点 Case 与完整 RoadGraph 使用任务级 `Gold/Silver/Unknown`、权重和 mask。用户已于 2026-07-21 明确确认：仅限 `E:\TestData\POC_Data` 的 T03/T04 单点 Case，可用当前正式策略算法重放，成功与失败终态及其 surface/relation 均视为人工确认真值；每次重放仍必须记录 Case manifest、代码版本、参数、终态和 artifact hash。
3. 共享编码器与任务 Head 只消费推理时可获得的基础事实；当前样本目标 artifact 和 T06 reason/status 不得进入输入特征。
4. 最终 T06 Head 决定 Road operation、SPLIT、方向、source、端点和有向连接；确定性物化只执行模型动作和 schema 写出。
5. 同一模型 logits 同时进入完全自由解码和通用图约束解码。约束只能保证 schema、引用、ID、几何和生成状态合法，不得编码 Segment 归属、SPLIT、方向、路口映射或补路业务判断。
6. 已访问的 M1 固定 test 只作历史回归；M2R 主要结论使用 business-ID grouped out-of-fold 预测。
7. M2R 仍为可学习性 POC，不修改或替代正式 T03-T06，不进入 T10/生产主链。

## 4. M0 冻结输入范围

本次实验仅接受 `E:\TestData\POC_Data` 下以下 Case 家族：

- `T03`、`T03_Error`
- `T04`、`T04_Error`
- `T10`、`T10-Error`、`T10-Error-2`

canonical baseline 可以位于仓库 `outputs/baselines` 或显式传入的其它位置，但每个标签必须通过 run summary 回指以上 Case 根。`POC_QA`、内网 D 盘和无法回指指定 Case 的 outputs 不得进入 M0。

## 5. 真值与权重

| 样本范围 | 目标标签权重 | 上下文标签权重 | 语义 |
|---|---:|---:|---|
| T03/T04 单点 Case 目标对象 | `1.0` | `0.3` | 逐对象人工确认/修正 |
| T10 Case 级 | `0.7` | `0.7` | 整体 Case 人工检查通过 |
| T10 Segment 级目标 Segment 及可追溯后继/Road/Node | `0.7` | `0.3` 仅作输入上下文 | 指定 Segment 整体检查通过；其它 Segment不得成为标签 |

权重提升只允许使用 manifest 中的业务 ID 与已审计 lineage。`T10-Error/T10-Error-2`
的非目标 Segment即使位于同一 Case，也必须 mask 掉 carrier/clue label、loss 和 metric；
其 `0.3` 只允许作为上下文输入权重。目标 ID 在当前 T01 消失时，只接受冻结 SWSD
Road 集合到当前 Segment的无遗漏、无重复精确分区，不得根据空间接近、geometry
overlap、文件同目录或单次运行成功自行提升标签可信度。

T03/T04 Case 目录若尚无 surface/relation artifact，可按本轮用户授权调用当前正式 T03/T04 策略重放生成标签。该标签必须明确登记为 `user_confirmed_strategy_replay_truth`，不得冒充历史原始产物；运行级失败必须与业务 `rejected` 分开，只有具备完整输入 lineage 和正式终态的 Case 才可用。此授权不扩展到 T10、其它目录或未来新增数据。

## 6. M0 功能需求

1. 扫描登记根，输出稳定 `sample_id`、`sample_group_id`、scope、输入 hash、标签任务 mask 和异常原因。
2. 解析显式 baseline roots 中 passed T10 run 的 handoff，登记 T01-T07 辅助标签和 T06 F-RCSD Road/Node 主标签的绝对路径与 hash。
3. 使用业务 ID 形成 `junction:<id>`、`segment:<id>` 或 `case:<id>` group；同一业务对象的不同归档版本不得跨 fold。
4. 用固定 seed 生成确定性五折切分，并提供固定 train/validation/test 视图。
5. 统一评估 candidate 与 canonical T06 Road/Node 的对象、属性、几何和有向拓扑差异。
6. truth-vs-truth Oracle 必须满分；删除 Road、反转方向、改变 source、移动端点或断开 Node 的破坏测试必须被对应指标或 hard gate 检出。
7. 所有产物写入不可变 run root，记录输入、参数、环境、耗时和输出 hash。
8. canonical truth 若自身存在缺失端点、重复 ID、CRS 冲突或其它 Road-Node integrity hard failure，必须保留 lineage、进入异常清单并关闭 RoadGraph task mask；不得修补 baseline 后继续训练。
9. 用户可确认排除异常样本；决定必须作为参数化审计记录进入新 run，关闭全部训练 task mask但不得删除样本，且 approved exclusion 与 pending quarantine 必须分别统计。

## 7. 非目标

- M0 本身不安装或训练 PyTorch 模型，也不定义网络架构和正式模型参数量；这些只属于独立 M1 run。
- M0 不新增 repo CLI、root script、T10 stage 或内网执行入口。
- M0 不修改原始 Case、canonical baseline 或 T01-T06 产物。
- M0 不自动修复 CRS、几何、端点或拓扑异常。
- M2R 不把 `Error` 目录名直接当作负类，不把缺失任务当作负样本。
- M2R 不允许事后业务修图；通用约束必须在解码动作层审计。

## 8. M1 验收摘要

- 最终 dataset 输入/监督中跨 split 实体与门禁邻域交集为零。
- Road 操作表示必须覆盖至少 `99.9%` 完整 truth，未覆盖对象仍计入最终评价分母。
- 固定 test Road F1 至少 `0.85`，并比最强确定性基线高至少 `5` 个百分点；direction/source 至少 `0.95`。
- Road/Node 引用、重复 ID、CRS 和有向拓扑 hard failure 为零；无效模型预测计失败，不自动修补。
- 图模型目标参数量 `8M~15M`，训练环境、checkpoint、逐 Case GPKG 和全部 hash 可追溯。

## 9. M2R 验收摘要

- 使用标签的 lineage、hash、CRS、trust tier、weight 和 task mask 完整率为 `100%`；`Unknown` 误作负样本为 `0`。
- 每个必选 Head 的 small-batch 拟合指标至少 `0.95`，并独立报告真实 grouped OOF 指标。
- T03/T04 可评价 surface Dice 至少 `0.80`；T05 relation 完全正确率至少 `0.90` 且 cardinality error 为 `0`。
- grouped OOF Road F1 至少 `0.85`、高于最强基线至少 `5` 个百分点、最差 Case 至少 `0.70`，direction/source 至少 `0.95`。
- constrained decoder 最终合法图比例 `100%`；Road/Node 引用、重复 ID、CRS、有向拓扑 hard failure、物化失败和事后内容修复均为 `0`。
- 模型参数量 `8M~20M`、峰值 VRAM 不超过 `16GB`，输入、checkpoint、逐 Case GPKG、约束触发和资源证据可追溯。

### 9.1 2026-07-21 M2R POC 实测结论

本轮 M2R 已完成 5-fold grouped OOF、T07 on/off 消融、free/constrained 同 logits 解码和 51 Case Road/Node 物化，结论为 **NO-GO（当前表示与基础模型方案）**，不外推为“神经网络整体不适用”。18.32M 模型的必选 Head small-batch overfit 均达到 `0.95`，但 T06 truth operation coverage 仅 `86.79%`；OOF Road F1 为 `0.64653`，略低于 keep-all `0.64657`，最差 Case `0.2466`，51/51 Case 有有向拓扑 hard failure。T07 只提升 `0.54` 个百分点且最差 Case 下降，按 SC-013 决定关闭。完整逐项证据位于 `outputs/_work/p05_neural_road_generation/p05_m2r_validation_20260721_01/validation_summary.md`。

## 9.2 R2 冻结目标

用户于 2026-07-21 正式授权 R2。R2 不继续优化 M2R 候选分类表示，而是建立 Road `COPY/UPDATE/SPLIT/CREATE/DROP`、Node `COPY/UPDATE/CREATE/DROP` edit-set 与精确 T05 `target_id -> base_id/NO_MATCH` pointer。第一门禁使用 truth 生成 label-only oracle edit 并从相同基础输入重建全部 51 Case；Road coverage 至少 `99.9%`，Node/SPLIT/pointer 可表达率 `100%`，归一化 Road/Node 与有向拓扑必须逐 Case完全一致。只有 Gate 1 通过后才实现 `20M~50M` 联合模型；T07 默认关闭，模型推理不得读取 oracle payload 或调用 T03-T06 业务规则。

R2 Gate 2 要求必选任务和图编辑 small-batch 指标均至少 `0.95`，small-batch Road/Node F1 至少 `0.98` 且拓扑完全一致。Gate 3 延续 grouped OOF Road F1 `>=0.85`、基线增益 `>=5pp`、最差 Case `>=0.70`，并新增 Node F1 `>=0.90`、edit macro-F1 `>=0.75`、每类 SPLIT recall `>=0.70`、全部拓扑/引用/物化 hard failure 为零。任一门禁失败必须在该层形成 no-go 归因，不得借后处理业务修图继续宣称成功。

## 9.3 R2 完成结论

R2 Gate 1 与 Gate 2 已通过：51 Case 的 Road、Node、T05 阶段 Node、SPLIT 和 T05 pointer 可表达率均为 `100%`，归一化语义与有向拓扑逐 Case 完全一致；40.19M 模型的必选 Head、graph edit、pointer 和 normalized topology small-batch 指标满足冻结门槛。Gate 3 未通过：grouped 5-fold OOF Road F1=`0`、Node F1=`0.0001223`、pointer accuracy=`0`、edit macro-F1=`0.25584`，51/51 Case 存在 topology hard failure，且低于 keep-all Road F1=`0.64657`。资源和确定性门槛通过，`content_repair=false`、`silent_fix=false`。

因此 R2 结论是 **当前 ordinal slot-query 基础模型 NO-GO**，不是“神经网络整体不适用”。Gate 1 已排除表示语言缺口，Gate 2 已排除完全不可学习；累计 40 epoch 时训练 loss 继续下降而 held-out RoadGraph 指标仍近零，说明当前 decoder 学到 fold 内 slot/layout 先验，缺少输出对象与输入图实体之间可迁移的 object-conditioned matching。后续不得继续以增加当前模型 epoch 作为主方案；应保留 R2 edit/pointer、label lineage 和门禁，另立 object-conditioned graph/set decoder POC。

## 9.4 PTO-P0 冻结目标

用户于 2026-07-21 正式授权 P05-PTO-P0。P0 复用 R2 edit/pointer，但将策略 proposal 与最终选择分离：登记 commit 且输入 lineage 完整的 T03/T04/T05/T06 重放只从 `E:\TestData\POC_Data` raw/T01 生成候选；登记历史 T10 replay 可包含 T07 可选辅助 stage，但只计入 replay lineage/成本，不形成独立候选或最终选择。候选 manifest 完成并哈希后，label/evaluation 层才允许读取 truth 计算 Oracle cost。候选层不得接收 truth/oracle path；独立重放内容恰好等于 truth 可以作为可达性证据，但不能称为模型输出。

P0 数据范围为 51 个 RoadGraph Case，显式排除 `T10-Error / 1213556_1263661`。Gate 1 要求 Road `23,224`、最终 Node `27,553`、T05 Node `24,739`、pointer `4,760`、SPLIT child `1,730` 全量可达，truth-derived candidate/feature/ID 泄漏为零。Gate 2 只使用通用 action/schema/ID/base/endpoint/有限几何/生成状态约束，要求 51/51 Case `OPTIMAL`、gap=0，Road/Node/属性/有向拓扑全部精确一致，`relaxation=false`、`content_repair=false`、`silent_fix=false`。P0 不训练 scorer；只有 Gate 1/2 均通过才允许 PTO-P1 训练 object-conditioned scorer 并执行 grouped 5-fold。

## 9.5 PTO-P0 完成结论

PTO-P0 的语义门禁均已通过。51 Case 共生成有限候选 `295,357` 个、变量 `295,357` 个、component/group 与约束各 `119,064` 个，`truth_input_count=0`、`truth_derived_candidate_count=0`。Road `23,224`、最终 Node `27,553`、T05 Node `24,739`、pointer `4,760`、SPLIT-derived child `1,730` 全量可达；51/51 Case 均为 `OPTIMAL`、gap=0，Road/Node/属性/有向拓扑精确一致，hard failure、relaxation、content repair 和 silent fix 均为零。两轮候选、选择、归一化 RoadGraph 与指标 signature 完全一致。

成本门禁未通过。候选 build+solve P95=`1.489s`、max=`4.278s`，P0 峰值 RSS=`3,125,002,240 bytes`、无需 GPU；但包含登记策略 replay 后端到端 P95=`284.809s`、max=`684.902s`，且历史 replay 没有完整 CPU time，不能证明全链 `2 CPU-hours` 门槛。因此 **PTO-P1 离线 learned-scoring 研究 GO，当前在线全链与生产接入 NO-GO**。PTO-P1 必须先消费本次冻结/缓存候选并执行 grouped 5-fold；并行实现轻量、缓存或增量 proposal generator。P1 OOF 与新 proposal 性能门均未通过前，不得宣称神经网络已直接生成最终 RoadGraph。

## 9.6 JSG-PTO-P0 完成结论

用户于 2026-07-21 明确授权的 `P05-JSG-PTO-P0` 已完成。该阶段没有直接学习 Road/Node edit，也没有训练 scorer，而是把 Junction、StandardSegment、JunctionSegmentRelation、PhysicalMovement、SegmentConnector、TerminalJunction 与显式 loop 固化为业务本体。从冻结 T01/T05/T06/R2 lineage 构建 51 Case label-only canonical JSG truth，并通过 `JSG -> carrier realization -> R2 edit IR -> Road/Node` compiler 验证可编译性。

JSG-P0 数据范围仍为 51 个 RoadGraph Case，显式排除 `T10-Error / 1213556_1263661`。实际出现对象的可表达率、canonical 往返和编译成功率必须为 `100%`；零实例类型必须单列。多 THROUGH 冲突只允许 `REVIEW`，自动选择为零；方向不得从 pair 字符串顺序推断；Connector/Terminal/loop 缺少明确证据时不得补造。Road/Node CRS、ID、引用、几何与有向拓扑 hard failure 必须为零，`content_repair=false`、`silent_fix=false`。

P0 只新增 P05 Python callable，不登记 CLI/root script/T10 stage，不修改 T01-T09 接口，不接生产，不训练任何模型。R2 Oracle carrier 和 edit IR 只作为 label-only compiler truth；P0 成功只能说明本体和编译合同成立，JSG 候选可达与 PTO 选择留给独立 P1。

正式 Run A/B 均为 51/51 canonical 往返精确、51/51 compiler 精确、hard failure=0、排除项零出现。实际对象为 Junction 9,042、StandardSegment 8,389、Relation 19,682、PhysicalMovement 24,779、SegmentConnector 69、Terminal 1,418；真实 loop 为零实例。7 个多 THROUGH 冲突全部保持 `REVIEW`，121 个缺失 frozen final carrier 的 StandardSegment 和 26 个 access 不唯一的 Connector 未被补造。两轮 semantic/compiled/provenance signature 一致，资源门禁通过。结论为 **JSG-PTO-P0 GO**；候选/PTO 未包含在 P0 中，现由已授权 P1 承接，模型训练和生产接入仍未授权。

## 9.7 JSG-PTO-P1 完成结论

用户于 2026-07-22 明确授权并已完成 `P05-JSG-PTO-P1`，M1/M2R/R2/RoadGraph PTO-P0 为历史实验结论。P1 候选层只接受 manifest 已证明 `truth_input_count=0`、`truth_derived_candidate_count=0` 的推理证据和 RoadGraph proposal；P0 JSG truth、T06 冻结 truth 和 R2 Oracle 只能在 candidate manifest 冻结后产生 label-only Oracle cost。

PTO-A 选择 Junction、StandardSegment、Relation、PhysicalMovement、SegmentConnector 与 Review/Unknown；PTO-B 选择 Unit carrier/access 和 RoadGraph edit/pointer。P1 要求可确认 JSG 语义与 PTO-B RoadGraph edit 候选 reachability 均为 `100%`，51/51 PTO-A/PTO-B `OPTIMAL`、gap=0、relaxation=false，compiler/RoadGraph hard failure=0，两轮 candidate/selection signature 一致。

正式 Candidate A/B 均为 51 Case、417,493 candidates、72,318 groups，候选层 `truth_input_count=0`、`truth_derived_candidate_count=0`、`label_only_candidate_count=0`，候选 JSONL/group/lineage 字节级一致。Solve A/B 均为 PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0，RoadGraph 51/51 精确，hard failure、carrier missing、multi-THROUGH auto select、relaxation、content repair、silent fix 均为零；candidate/PTO-A/PTO-B/JSG/RoadGraph 五类 signature 一致。

P1 增量 P95 为 `7.397s/8.892s`，max 为 `26.294s/24.906s`，峰值 RSS 约 `3.677GB`，CPU 各约 `152s`，无需 GPU。历史 strategy replay 总耗时 5,751.192s，继续判为在线 proposal 性能 NO-GO。结论为 **JSG-PTO-P1 GO（离线候选与 Oracle 语义证明）**；神经 scorer、OOF 泛化和生产接入均未启动。

P1 不训练神经网络或其它 scorer，不重跑或修改 T01-T09 业务规则，不新增正式入口，不接生产。历史策略 replay 成本必须单列；即使 P1 增量链通过，也不自动改写 RoadGraph PTO-P0 在线性能 no-go。

## 9.8 JSG-PTO-P2 完成结论

用户于 2026-07-22 明确授权启动 `P05-JSG-PTO-P2`。P2 固定使用 `p05_jsg_p1_candidate_20260722_02`、`p05_jsg_p1_oracle_20260722_03` 和 `p05_m0_20260721_06` 的 manifest/hash，构建 V0 显式证据代价和 V1 ID-free 可解释加性线性评分；每个 Case 按 M0 business-ID grouped 5-fold 恰好一次 held-out。

feature 只允许 candidate payload 的枚举/结构、source kind、role、复杂度和证据状态；Case/business/object/candidate/group ID、坐标值、truth、Oracle cost、truth signature 和 held-out fold 统计不得进入 feature。M0 target/context 权重继续为正式监督权重，Unknown 不得编码为负样本。

P2 使用统一 `candidate_id/cost/confidence/uncertainty/score_source` 合同进入 PTO-A/PTO-B。V0/V1 必须共用相同 candidate、constraint、compiler 和 evaluator；任何 infeasible 或 hard failure 直接保留，禁止回退 Oracle、Case 特判、relaxation、内容修复或 silent fix。

P2 的 grouped OOF 门禁为 PTO-A Top-1 总体/各类型 `>=0.90/0.80`、JSG micro/macro F1 `>=0.90/0.85`、Review recall `>=0.90`、Road/Node F1 `>=0.85/0.90`、最差 Case Road F1 `>=0.70`、direction/source `>=0.95`、每类 SPLIT recall `>=0.70`，全部图 hard failure为零。

正式 dataset 为 51 Case、712,799 candidates、5 folds，forbidden feature hit=0；`T10-Error / 1213556_1263661` 按批准排除。V1 JSG Top-1/macro F1/Review recall 为 `0.7243/0.6173/0.0130`，SegmentConnector 最低为 `0.0907`，因此 ranking gate 失败。Road/Node、direction/source、SPLIT 均为 `1.0`，最差 Case Road F1=`1.0`，PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0、hard failure=0；解释覆盖率 100%，资源与双跑确定性门禁通过。

结论为 **P2 实验完成、V0/V1 baseline NO-GO、评分瓶颈成立**。P2 完成时只形成 object-conditioned P3 scorer 的技术启动理由；用户随后已另行授权 P3。在线 proposal 和生产接入仍未授权。

## 9.9 JSG-PTO-P3 完成结论

用户于 2026-07-22 正式授权并已完成 `P05-JSG-PTO-P3`。P3 固定 P1/P2 candidate、label、M0 business-ID grouped 5-fold、PTO-A/PTO-B、compiler 和 evaluator，只新增由同组备选、dependency/reverse-dependency、Case profile 与已登记 T01 相对方向证据构建的 ID-free context，以及约 `0.88M~0.90M` candidate/context interaction neural scorer。

P3 使用 outer grouped 5-fold 和 outer train 内的 inner validation；fold vocabulary、class weight、early stopping 均不得读取 outer held-out Case。正式验收为 3 seeds × 5 folds，JSG Top-1/micro `>=0.90`、macro `>=0.85`、五种对象类型均 `>=0.80`、Review/Unknown recall/precision `>=0.90/0.80`、ECE `<=0.10`，三个 seed 均须通过。

RoadGraph 只作 safety gate：PTO-A/PTO-B 51/51 `OPTIMAL`，Road/Node、最差 Case Road、direction/source、SPLIT 均保持 `1.0`，hard failure/repair 为零。P3 不修改候选、约束、compiler 或 T01-T09；不解决在线 proposal 性能，不授权生产接入。

正式 context dataset 为 51 Case、191,331 groups、712,799 candidates，ID/truth/Oracle/绝对坐标泄漏为零。三个 seed 的 JSG Top-1/macro 分别落在 `0.9390~0.9395 / 0.8471~0.8817`，ECE `0.0065~0.0174`；candidate-only 消融 Top-1 为 `0.7692`，证明 object-conditioned context 提供约 `+0.1701` 的有效增益。但 SegmentConnector 仅为 `0.4283~0.5992`，Review/Unknown recall/precision 仅为 `0.4389~0.4952 / 0.6886~0.7828`，三个 seed 均未通过 JSG 主门禁。

PTO-A/PTO-B 三个 seed 均 51/51 `OPTIMAL`，Road/Node/direction/source/SPLIT 均为 `1.0`，hard failure、relaxation、content repair 与 silent fix 为零；同 seed 双跑、GIS、资源与完整 P05 回归通过。结论为 **`P3_MODEL_NO_GO`**：当前 inference 输入缺少区分 carrier realization/access-resolved outcome 的对象级证据，不等于神经网络整体不适用。在线 proposal 与生产接入继续为 NO-GO；该结论现作为历史模型证据保留。

## 9.10 方案 A Carrier 基线目标

方案 A 首阶段在冻结 51 Case 上重建完整 T01 Segment 骨架、当前策略 `SUCCESS_DIRECT/SUCCESS_WITH_FALLBACK/FAIL` 基线、Segment/Movement carrier-only 标签、RealityChangeClue 和最小依赖闭包 fallback。全部 `advance_right` 必须作为 Segment 表达，当前 `SegmentConnector` 数为零；策略和标签覆盖率、lineage 完整率为 100%，骨架 mutation、content repair 和 silent fix 为零。两轮独立 run 的 skeleton/baseline/label/clue/fallback signature 必须一致。本阶段不训练模型，完成条件以对应 SpecKit 为准。

## 9.11 Scheme-A-P1 已完成结论

P1 从冻结业务骨架和登记 strategy replay 生成零 truth Segment/Movement carrier candidates；candidate manifest/hash 完成后才允许读取方案 A baseline label。候选 exact reachability、forbidden feature 和 fold 隔离先作为 Gate 0；通过后训练 `1M~5M` object-conditioned scorer，以 3 seeds × 5 folds 评价 Segment carrier、Movement exact carrier、异常/fallback、稳定性、资源和 RoadGraph 安全。模型不得读取 canonical relation status/reason、truth payload、ID 或绝对坐标特征，不得改变骨架或借 hard gate 做内容修复。

P1 RoadGraph hard gate 对同 ID 跨来源 payload 使用严格 carrier 语义等价：二维几何和 T01 核心 Road/Node 字段必须精确一致，只有 proposal 独有审计扩展字段可忽略。等价时确定性保留原始已选 payload 并记录逐 ID coalesce 审计，不合并属性；任何核心字段或几何差异仍触发最小闭包 fallback，不属于 content repair。

RoadGraph 安全的成功形态为每个 seed `49 LEGAL + 2 EXPECTED_FAIL`，且51 Case均有可审计终态；预期失败集合必须与冻结 manifest 精确匹配，失败 Case必须有对应 `RealityChangeClue` 且发布数为零。

正式 run `p05_scheme_a_p1_oof_formal_20260722_01` 已完成 3 seeds × 5 folds；`p05_scheme_a_p1_oof_replay_seed17_20260722_02` 完成同 seed 内容重放。Gate 0/4/5 通过，Gate 1/2/3 失败，最终为 `P05_SCHEME_A_P1_MODEL_NO_GO`。完整证据见对应 SpecKit `validation-summary.md`。

## 9.24 Scheme-A-P2-P3-P4 已完成结论

P2-P3-P4 已完成并判定
**`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`**。
旧 P2-P1 在 Dataset-P1 scope 之前使用全部 8,863 个 Scheme-A Segment label
计算 Road endpoint/JunctionUnit 条件化 Node 真值，context-only carrier 来源冲突
因此污染了可靠 target。P4 把顺序冻结为：

1. Dataset-P1 先唯一划分 6,275 eligible 与 2,588 context-only；
2. context-only 保留 0.3 输入权重，但标签贡献为 0，整图安全实现固定
   `KEEP_SWSD`；
3. 之后才计算 Node carrier 与 Junction fallback。

修正后初始 Node payload conflict 为10，Junction fallback Segment为21（eligible
10），最终28,240个Node真值无冲突。相对历史P2-P1的436个Segment delta中，
435个属于context-only，唯一eligible变化为
`SCHEME_A_P1:SEGMENT:T10-Error-2:89387685_507565991:89387685_507565991`；
它由错误`KEEP_SWSD/anomaly=true`恢复为`USE_RCSD/anomaly=false`，正确candidate
为`sap1:918ffd80e766808f8a6b516c`。

既有P2-P3-P3三seed决策在修正真值下accepted wrong/Review auto均为0，carrier
safety recall均为1.0；因此P2-P3-P3“残余false-use要求新表征”只保留为旧闭包
顺序历史证据。模型仍因safe coverage和clue门跨seed/fold不稳定而NO-GO。
本阶段未训练、未调阈值、未重建RoadGraph、未修改T01–T12；下一阶段重训/复验
必须另行授权。

## 9.25 Scheme-A-P2-P3-P5 已完成结论

P2-P3-P5 已完成并判定 **`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`**。

P5 只将 P4 修正后的 scope-first Segment/Node 真值覆盖到历史 P2-P1
truth-free candidate/feature/payload/compatibility 工件上，从头重训既有
`p05-scheme-a-p2-p3-p0-network-v1`。训练分母固定为6,275个eligible Segment，
2,588个context-only Segment监督、阈值和指标贡献均为0；参数量为
2,818,234–2,818,810，仍使用202维T01/T07证据、3 seeds × 5 Case folds。

P6 后续双层审计确认：三seed的final publication wrong/Review auto均为`0/0`，
但scorer decision wrong accepted=`1/1/1`、carrier safety recall=
`0.975610/0.975610/0.976744`。scorer safe coverage为
`0.6524/0.7952/0.3469`；RoadGraph原子阻断后的final safe coverage为
`0.4290/0.5498/0.1374`，`USE_RCSD` final safe coverage为
`0.6918/0.7044/0.2310`；clue recall/precision/macro-F1为
`0.9805/0.6614/0.8512`、`0.8831/0.9985/0.9596`、
`0.9960/0.3605/0.5751`，clue-only捕获为`5/5、4/5、5/5`。只有seed313的
整体carrier门通过，逐fold仍未闭合；三个seed的clue门均失败。

40个`ADVANCE_RIGHT access_valid=false`与40个Review精确对应，非Review误触发
为0。每seed均物化49 `LEGAL`+2 `EXPECTED_FAIL`，requirement conflict、Node
mismatch/conflict、非目标Case级联、repair、silent fix和skeleton mutation均为0。
正式Dataset A/B signature为
`5efbe66318f818dd705dbd10acd48366e328d2f8e61bae51812a46d5cf61fb46`；
正式OOF Run A/B signature为
`de6c92d0bde80f2d0690af76a340931d802cdf5def7bc63601406040720dce02`，
两项Run B reference match均为true。

本结论关闭旧稳定false-use与真值carrier冲突，但证明当前同架构模型仍只能用较多
fallback维持安全，且RealityChangeClue跨域不稳定。不得挑seed、在当前held-out
Case上调阈值、恢复旧真值或接入生产。

## 9.26 Scheme-A-P2-P3-P6 已完成结论

P2-P3-P6 已完成并判定
**`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`**。P6只读校验
P5 manifest/hash并唯一join 18,825条seed-object记录，不训练、不调阈值、不改写
P5工件。

每seed完整审计6,275个eligible Segment；safe coverage排除40 Review，以6,235为
分母。两个`EXPECTED_FAIL` Case在scorer层只局部失败2个group，在final
publication层原子阻断1,954个eligible对象。三seed唯一共同wrong accepted均为
`T10:609214532 / 505101583_506183080`，真值`KEEP_SWSD`、选择`USE_RCSD`；
final wrong published为0仅因为整图阻断。

clue FP/FN为`747/29`、`2/174`、`2629/6`，稳定FP/FN=`2/4`。15个fold threshold
跨`0.000296–0.998983`；全部3,587条clue error无相反标签exact evidence或完整
group-signature碰撞，但稳定wrong的top-20训练邻域均为
`USE_RCSD + clue=false`。这同时证明clue calibration和当前truth-free表征存在
独立问题。

正式Run `p05_scheme_a_p2_p3_p6_attribution_20260724_03/_04` signature均为
`e753bb817be16841adf4832dbfe3d68ed579e7b851364dd54a4569bbbf180a1c`，
Run B reference match=true。P6 GO只放行归因结论；P5模型NO-GO、生产边界和
T01–T12冻结边界不变，下一训练阶段尚未授权。

## 9.27 Scheme-A-P2-P3-P7 已完成结论

P2-P3-P7 已完成并判定
**`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`**。历史202维evidence只读保留；
经用户二次确认，实际非零的14个Movement命名维及其28个邻域派生维从P7表征排除，
以188维无Movement base、377维compatibility-neighborhood和37维T01相对几何组成
602维。6,275/6,275对象几何完整，52条T01 inventory路径hash通过，51个eligible
Case输入读取均为`EPSG:3857`；truth、ID、绝对坐标、T03–T06和Movement推理维为0。

稳定wrong `T10:609214532 / 505101583_506183080` 的top-20 train-only邻域仍为
`20/20 USE_RCSD + 20/20 clue=false`，未满足至少1个KEEP和1个clue=true的门。
三个seed在clue recall固定为1时，最佳precision/macro-F1约为
`0.241/0.238`、`0.239/0.229`、`0.361/0.582`，均低于`0.80/0.85`。

正式Run `p05_scheme_a_p2_p3_p7_audit_20260724_01/_02` signature均为
`3154e4bb6af8358efcfff6f6dd5ed7ca90189f0d915d654d86fb1cbcdac2bcee`，
Run B reference match=true；完整P05测试231项通过。本结论不否定神经网络路线，
但禁止在当前来源上启动下一训练轮。T03/T04推理角色提升或新增确定性T06前关系
生成器必须由用户另行授权。

## 9.28 Scheme-A-P2-P3-P8 已完成结论

P2-P3-P8 已完成并判定
**`P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`**。
本阶段只读核验51个eligible Case的T03/T04正式T05 handoff工件，663个核心工件
存在、hash可冻结；255个来源GPKG layer和51个T01 Segment GPKG均为`EPSG:3857`。
6,275个eligible Segment只按Case-local T01 `junc_nodes`精确关联，504个适用来源、
192个多来源、5,771个`NOT_APPLICABLE`，空间join、cross-Case join和silent merge
均为0。

稳定carrier wrong `T10:609214532 / 505101583_506183080`命中T04
`no_related_rcsd`来源。T04 `merge/diverge`保留为上下文候选，但carrier安全状态
signature对方向不变；held-out-fold之外2个完全同类对象均为
`KEEP_SWSD + clue=true`且`USE_RCSD=0`，故carrier来源门通过。P7的6个稳定Clue
错误只有1个具备T03/T04适用来源，Clue来源门失败。

正式Run `p05_scheme_a_p2_p3_p8_source_audit_20260724_02/_03` signature均为
`4b3002494b6c33400907751aca44c375481a3602bb3cff1f8cad45bce8852508`，
Run B reference match=true；完整P05测试236项通过。T03/T04继续
`model_input=false/label_only=true`，本结论只放行carrier-only字段promotion
二次评审，不自动提升字段、不授权训练、T01–T12改造、自动替换或生产接入。

## 9.29 P9 Carrier-only Promotion 已完成，模型 NO-GO

用户于2026-07-24批准将P8白名单内T03/T04正式T05 handoff字段提升为P05
carrier-only软判断输入。该promotion通过P9 overlay表达，不回写历史Dataset-P0/P8
工件；Clue source feature/loss/decision必须为0，`NOT_APPLICABLE`不能编码为负样本，
T01骨架、fallback、Node/Junction decoder和T01–T12实现不变。

P9已执行602维Movement-free Control与冻结Control后的source residual adapter
3 seeds × 5 Case folds严格A/B。adapter参数为`30,721~31,105`，总参数为
`3,054,043~3,054,715`；504个适用对象的Control/Treatment pooled macro-F1和KEEP
recall均为`0.9986769935/0.99609375`，没有严格增益。稳定对象三seed仍选
`USE_RCSD`，scorer层错误自动接受均为1。5,771个无来源对象score/decision差异为0，
Clue source消费与Clue概率差异为0；RoadGraph、确定性、资源和242项P05回归通过。
正式decision为`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`。P8历史工件与白名单
保留，但P9 adapter不进入后续自动化或生产链。

## 9.30 P10 人工裁决集合真值校准已完成

用户于2026-07-24逐对象确认：`T10:609214532 / 505101583_506183080`为
`USE_RCSD + RealityChangeClue=false`；`T10:706247 / 706317_706319`按路口级
冲突最终只允许`KEEP_SWSD + RealityChangeClue=true`并执行Junction fallback；
`T10:706247 / 706346_706349`允许`KEEP_SWSD/USE_RCSD`、优先
`USE_RCSD + RealityChangeClue=false`；`T10:609214532 / 513242335_523239407`
与`T10:609214532 / 606102026_609617028`均只允许并优先`KEEP_SWSD`，且
`RealityChangeClue=false`：RCSD数据缺失不代表当前道路结构冲突。对象级人工裁决
权重1.0覆盖T10 Case级0.7，业务合法性、优选命中和Clue分开验收。

P10未重训或调阈值，只对冻结P9 Run B的Control/Treatment evaluation/decision复算。
504个source-applicable对象、三seed合计1,512条记录的合法准确率在两臂均为1.0，
优选命中率均为`0.9980158730`、preferred macro-F1均为`0.9986771185`；三seed
scorer wrong accepted、Review auto publish和Junction fallback violation均为0，
carrier safety recall均为1.0。因此P9关于609“稳定模型错误”的归因失效，但两臂
strict gain仍为false，adapter依然没有promotion价值。Clue pooled
precision/recall/macro-F1为`0.583278/0.987197/0.804359`、FP/FN为`3140/57`；
对象级三seed稳定Clue漏报已归零，但P9冻结的逐seed/逐fold coverage门和稳定Clue
误报未因只读复算关闭，完整模型继续阻断。

三对象中间Run `_01/_02`保留为历史证据；五对象正式Run
`p05_scheme_a_p2_p3_p10_adjudication_20260724_03/_04` content signature均为
`ef779bfaf89c2bbfc0ef27d8e0e52cbd9075f145c9c54cf100c350bc0557d9cc`，Run D
reference match=true。训练、模型权重变化、Movement decision和geometry write均为0，
完整P05回归245项通过。正式decision为
**`P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`**。
本结论不授权生产接入、自动替换SWSD或使用本次事后裁决重训后重报同一held-out结果。

## 9.31 P12R 提右条件化真值与候选上限审计已完成

P12R纠正旧P12的业务边界：普通提右不经过T05。474个`ADVANCE_RIGHT Segment`
全部以冻结`source_segment_access/target_segment_access`关联普通Segment；普通
Segment的T06 relation先决定两侧RCSD/SWSD来源，随后才用T06 final Road/Node及
advance-right attachment/closure/topology audit重建提右carrier、混源拼接、
附着后处理或安全fallback。T06仅作label-only重放，推理候选只来自T01 SWSD
identity和原始RCSD；模型、Movement、骨架、geometry和T01–T12均未改变。

实现将`t06_split_reason=topology_supplement_from_swsd`保留为SWSD业务来源，
不得因终态`source=1`误解释为原始RCSD；attachment audit中的
`replacement_segment_ids`是动作上下文，不等同于“挂在提右Road上的Segment”。
挂接Segment只能由实际目标Road lineage反查正式Segment owner。正式审计中40个
`access_valid=false`全部Review，自动真值396个，两侧来源一致396/396；
`RealityChangeClue`的RCSD缺失误报、T05提右anchor label、挂接关系缺失、正式
Segment独立Road丢失、unsafe auto publish均为0。

396个eligible对象candidate oracle命中377个，总体recall=`0.952020`；五个
Case-grouped fold中最差为T10:706247的`0.875`，未达到`>=0.90`。19个漏候选均为
`RCSD_ONLY`，按Case为T10:1885118 12个、T10:605415675 1个、
T10:609214532 3个、T10:706247 3个；17个有原始RCSD直接lineage但正确Road距原
SWSD提右`5.15–43.55m`，2个还缺少可直接消费的原始RCSD lineage。因此失败点是
5m局部邻近候选与lineage闭包不足，不是提右真值缺失，也不是神经网络整体不适用。

正式Run为
`p05_scheme_a_p2_p3_p12r_advance_right_audit_20260724_03/_04`，共同signature
`320a8216a3e3592c9037f32300af7162b10d615277130d132bd410bb68e825e7`，Run B
reference match=true；wall约22.12/22.29s、峰值RSS约0.417/0.416GiB，GPU和训练
均为0，完整P05回归253项通过。正式decision为
**`P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED`**。该结论只授权
讨论下一轮Road endpoint/JunctionUnit条件化候选补强；不授权训练P13、生产接入、
自动替换SWSD或直接放宽5m为业务阈值。

## 9.32 P12R-R1 endpoint/Junction条件化候选补强已完成

R1保留P12R 5m局部候选为Control，只用冻结T01 Segment/Road/Node、原始RCSD
Road/Node及相邻普通Segment端点关系生成Treatment候选。原始RCSD提右Road先按
精确Node连通形成component，再以顺序端点间隙`<=1m`或平行两侧端点间隙`<=5m`
形成bundle；bundle两侧incident普通Road与T01普通Segment Road的候选关联距离
必须`<=10m`。该10m只用于候选发现，不构成正确锚定、替换合法性或发布规则。

候选、证据和对象清单先冻结并生成candidate signature，之后才读取P12R/T06
label-only工件计算Oracle。歧义owner方向不自动加入；T05提右标签、T06终态候选或
feature、Movement、case hardcode、跨Case候选、geometry写入和训练均为0。

正式双跑
`p05_scheme_a_p2_p3_p12r_r1_endpoint_candidates_20260724_01/_02`
共同candidate signature为
`84344d11cdc168cea42cdaacd0c36f83f9f4b57e45dd01b802a9c35ce064f734`，
共同content signature为
`244b81957cf4eb39889fd88b61bdccb296707a901f8240580c46061aeb2a1e5b`，
Run B reference match=true。Control 474/474精确复现P12R，396个eligible对象的
Treatment命中`388`个，overall recall=`0.979798`，最差fold=`0.916667`；
相对Control净增11、损失0。候选数P95/max=`4/12`，6/6 Case的CRS一致且为米制
投影，正式工件hash全部自校验通过，完整P05回归257项通过。

正式decision为
**`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`**。该结论关闭P12R的候选可达性
阻断，但只允许讨论后续R1候选scorer；不授权训练、自动替换SWSD、生产接入或将
候选阈值固化为业务规则。

## 9.33 P13-P0 提右候选集合模型训练已完成

P13-P0在R1冻结候选上训练480,739参数的permutation-invariant candidate-set
scorer。每个外层held-out Case fold只用其它fold建立归一化、checkpoint和inner
阈值；三个seed共15个模型。模型逐Road输出RCSD集合，并由独立safety head、置信
拒识和确定性fallback约束发布。40个T01 access无效对象直接硬回退；其余38个Review
和8个R1 Oracle不可达对象仅作label-only安全评价，未被写成推理mask。

特征在label读取前冻结。50维输入只含R1 candidate source/orientation、bundle、
incident carrier、相邻owner、相对距离、Road形态与集合rank；5m Local Control作为
固定先验。ID只用于Case内join，绝对坐标、Case/fold、路径、Movement、T05提右标签
和T06终态均未进入张量。

正式双跑`p05_scheme_a_p2_p3_p13_p0_oof_20260724_05/_06`共同feature signature为
`949d15ff4d0a87cce8c1be0f742aa921110e08baf6a288af7b38730f6c9c4e53`，
共同content signature为
`c219be6609e0bc0a9dfccb9077a2a19de20f23fc10059839313dd28679fa3925`，
Run F reference match=true，15个checkpoint逐字节一致，27项artifact各自hash
自校验通过。

模型raw exact-set=`0.646907`，低于Local Control `0.680412`，最差fold
`0.363636`；candidate/object macro-F1=`0.750984/0.791407`。自动发布发生14次
unsafe、2次Review RCSD和1次R1不可达RCSD；accepted coverage=`0.017677`，最差
fold为0。三seed pooled中，模型相对Control新增23次exact但破坏62次Control exact；
116个对象三seed稳定错误，只有3个对象三seed稳定净增。

正式decision为
**`P05_SCHEME_A_P2_P3_P13_P0_SELECTION_NO_GO`**。该结论否定当前50维R1
candidate-only模型，不否定R1候选GO或神经网络整体。未经另行授权不得继续同构
训练；后续技术方向应先审计相邻普通Segment OOF soft carrier状态能否作为合法
推理期joint-conditioning证据。

## 10. M0 验收标准

- 七个登记 Case 家族均被扫描，缺失/冲突不静默丢弃。
- 全部可用标签均有 source Case、run summary、artifact path 与 SHA-256 lineage。
- group 在 train/validation/test 间零交集，重复运行切分一致。
- Road/Node evaluator 覆盖 CRS、属性、端点、几何、拓扑与性能。
- 通过 truth integrity gate 的可用样本 Oracle 满分；异常 truth 隔离率与原因明确，至少五类定向破坏均能被识别。
- M0 summary 明确样本量、有效任务量、异常量、fold 分布和资源消耗。
