# 05 质量要求

## CRS

所有 Road/Node layer 必须声明 CRS。candidate 与 truth CRS 不同即 hard fail；M0 不隐式重投影。

## 拓扑

Road 起终点必须引用存在的 Node；Road ID、Node ID 必须唯一；有向边差异必须单独报告。任何修复都不得静默发生。

## 几何语义

几何评价至少覆盖端点误差、Hausdorff 和双向采样 Chamfer 近似。几何 fallback 必须受距离阈值约束，并与 ID 精确匹配分层报告。

## 审计

输入、参数、输出、运行环境和 hash 必须可定位。缺失/冲突样本必须进入异常清单。

## 性能

M0 全量运行记录 wall time、Case 数、Road/Node feature 数和峰值 RSS（平台可用时）。评估器应按 Case 流式读取，不把全部七个根一次性加载到内存。

## 测试

单元测试覆盖 inventory、scope、lineage、group split、Oracle 和破坏检测；真实数据验收覆盖七个 Case 根及显式 canonical baseline。

M1 还必须验证输入/label 隔离、实体级零泄漏、KEEP/DROP/SPLIT_1~3、加权 loss、checkpoint 重放和物化 no-silent-fix。最终候选 Road/Node 继续使用 M0 evaluator；完整 truth 不因候选无法表达而缩小分母。

## M1 性能

图模型使用稀疏边，不允许对万级候选构建全连接 attention。dataset、训练和推理分别记录 wall time、峰值 RAM、峰值 VRAM、候选/边数和吞吐；默认模型参数量必须落在 `8M~15M`。

M1 实测资源证据：dataset `19.24s`；固定开发训练 `8.02s`、峰值进程 RSS `2.13GB`、峰值 VRAM `4.70GB`；固定 test 模型与基线联合评价 `10.60s`、峰值进程 RSS `1.36GB`。这些数值只描述本机 RTX 5090 POC，不构成生产容量承诺。

## M2R 质量门禁

- 使用标签的 lineage/hash/CRS/weight/task mask 完整率 `100%`，`Unknown` 误作负样本数 `0`。
- 必选 Head small-batch 拟合指标至少 `0.95`；T03/T04 可评价 surface Dice 至少 `0.80`；T05 relation 完全正确率至少 `0.90` 且基数错误为 `0`。
- grouped OOF Road F1 至少 `0.85`、高于最强基线至少 `5` 个百分点、最差 Case 至少 `0.70`、direction/source 至少 `0.95`。
- constrained decoder 合法图比例 `100%`，事后内容修复、缺失引用、重复 ID、CRS 和有向拓扑 hard failure 为 `0`。
- 参数量 `8M~20M`，单 GPU 峰值 VRAM 不超过 `16GB`；训练、推理、逐 Case evaluator 性能可定位。

## R2 质量门禁

- Gate 1：Road edit coverage 至少 `99.9%`；Node、SPLIT、T05 pointer 可表达率 `100%`；51/51 Case 归一化 Road/Node 和有向拓扑完全一致。
- Gate 2：必选任务和 graph edit small-batch 指标至少 `0.95`，物化 Road/Node F1 至少 `0.98` 且拓扑完全一致。
- Gate 3：Road F1 至少 `0.85`、基线增益至少 `5pp`、最差 Case至少 `0.70`、Node F1 至少 `0.90`；edit macro-F1 至少 `0.75`，每类 SPLIT recall 至少 `0.70`；全部引用/ID/CRS/拓扑/物化 hard failure 为零。
- 模型目标 `20M~50M`，未经重新评估不超过 `60M`；峰值 VRAM 不超过 `16GB`，五折训练和单 Case P95 推理耗时可审计并满足 R2 SpecKit 限额。

R2 实测：Gate 1 和 Gate 2 通过；Gate 3 的资源与确定性通过，但语义、pointer、edit、最终 Road/Node 和拓扑门槛均失败。因此当前 40.19M ordinal slot-query 模型只能作为失败基线保留，不得进入扩量或生产候选。

## PTO-P0 质量门禁

- 51/51 Case，排除项零出现，truth-derived candidate/feature/ID 泄漏为零。
- Road `23,224`、最终 Node `27,553`、T05 Node `24,739`、pointer `4,760`、SPLIT child `1,730` 候选可达率 `100%`。
- 51/51 `OPTIMAL`、gap=0；Road/Node F1、属性准确率和有向拓扑均为 `1.0`，所有结构 hard failure 为零。
- 重复运行候选、选择、归一化图与指标 signature 一致；候选生成+求解 P95≤`60s`、最大≤`300s`、RAM≤`16GB`、GPU 不需要、总 CPU≤`2h`，策略 replay 耗时不得隐藏。

PTO-P0 实测候选可达性、精确求解、GIS、结构与确定性门禁全部通过；candidate build+solve P95=`1.489s`、max=`4.278s`、峰值 RSS约 `2.91 GiB`。含策略 replay 的端到端 P95=`284.809s`、max=`684.902s`，且 replay CPU time 不完整，性能门禁失败。PTO-P1 只允许先消费冻结/缓存候选；在线接入前必须以新 proposal generator 重过同一资源门。

## JSG-PTO-P0 质量门禁

- 固定 51 Case，排除项零出现，全部 lineage/hash/CRS 可定位。
- 实际出现的 Junction/Segment/Relation/Movement/Connector/Terminal/loop 可表达率 `100%`；零实例类型显式报告。
- canonical JSG 往返 51/51，两个独立 run semantic signature 完全一致。
- 多 THROUGH 自动选择数为零；所有 schema、ID、引用、方向、loop、roundabout hard failure 为零。
- JSG compiler 51/51 成功；Road/Node CRS、ID、引用、几何、有向拓扑 hard failure 为零，并与冻结 T06 truth 完全一致。
- `label_only=true`、`content_repair=false`、`silent_fix=false`；P95/max `<=30s/120s`，RSS `<=16GB`，GPU 不需要，总 CPU `<=1h`。

P0 实测通过全部门禁：51/51 JSG 往返和 compiler 精确、hard failure=0；Run A/B P95=`6.278s/6.320s`、max=`18.314s/21.840s`、峰值 RSS=`1,131,950,080/1,131,982,848 bytes`，无需 GPU。loop 为真实零实例，只完成 schema/合成边界验证。

## JSG-PTO-P1 质量门禁

- candidate run 51 Case、排除项零出现、truth 输入/派生/label-only candidate 均为零。
- 可确认 PTO-A 语义和 PTO-B RoadGraph edit reachability `100%`；Review/Unknown 单列。
- PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0；multi-THROUGH 自动选择、relaxation、content repair、silent fix 均为零。
- compiler 51/51 成功，Road/Node CRS、ID、引用、几何、有向拓扑 hard failure 为零。
- candidate/selection 双跑 signature 一致；增量 P95/max `<=60s/300s`、RSS `<=16GB`、总 CPU `<=2h`、GPU 不需要，历史 replay 成本另列。

P1 实测通过：两轮均 51 Case，417,493 candidates、72,318 groups，PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0，RoadGraph 51/51 精确，GIS/拓扑 hard failure=0；P95 `7.397s/8.892s`、max `26.294s/24.906s`、峰值 RSS 约 `3.677GB`、无需 GPU。历史 replay 5,751.192s 继续作为在线 proposal 性能 NO-GO。

## JSG-PTO-P2 质量门禁

- 51 Case M0 business-ID grouped 5-fold；每个 Case 一次 held-out，fold/ID/truth/oracle feature leakage 为零。
- 100% candidate 有 V0/V1 cost、confidence、uncertainty 和可重建 explanation。
- PTO-A Top-1 总体/各类型 `>=0.90/0.80`；JSG micro/macro F1 `>=0.90/0.85`；Review/Unknown recall `>=0.90`。
- Road/Node F1 `>=0.85/0.90`，最差 Case Road F1 `>=0.70`，direction/source `>=0.95`，每类 SPLIT recall `>=0.70`。
- 51/51 PTO-A/PTO-B `OPTIMAL`、gap=0，图 hard failure、relaxation、content repair、silent fix 为零。
- score P95/max `<=5s/20s`；完整链 P95/max `<=60s/300s`、RSS `<=16GB`、训练 CPU `<=2h`；双跑 signature 一致。

P2 实测：V1 JSG Top-1/macro F1/Review recall 为 `0.7243/0.6173/0.0130`，ranking gate 失败；RoadGraph safety gate 通过。P3 后续已完成并将总体排序显著提升，但 Connector 与 Review/Unknown 仍失败。

## JSG-PTO-P3 质量门禁

- 51 Case、191,331 groups、712,799 candidates；context、outer fold、inner validation、ID/truth/Oracle/absolute-coordinate leakage 为零。
- 参数目标 `0.5M~3M`、上限 `5M`；100% score/context/model contract，ECE `<=0.10`。
- 正式 3 seeds × 5 folds；每个 seed 的 JSG Top-1/micro `>=0.90`、macro `>=0.85`、五种对象类型均 `>=0.80`、Review recall/precision `>=0.90/0.80`。
- PTO-A/PTO-B 51/51 `OPTIMAL`；Road/Node、最差 Case Road、direction/source、SPLIT 均保持 `1.0`；hard failure/repair 为零。
- 单 seed 5-fold `<=2h`、总计 `<=6h`、RAM `<=16GB`、VRAM `<=8GB`；score P95/max `<=5s/20s`，完整链 `<=60s/300s`。

P3 实测：三个 seed 的 JSG Top-1/macro 为 `0.9390~0.9395 / 0.8471~0.8817`，Connector 为 `0.4283~0.5992`，Review recall/precision 为 `0.4389~0.4952 / 0.6886~0.7828`。Gate 0/1/3/4 通过，Gate 2 失败，正式判定 `P3_MODEL_NO_GO`。三个 seed 的 PTO-A/PTO-B 均 51/51 `OPTIMAL`，Road/Node/direction/source/SPLIT 均为 `1.0`，hard failure/repair/silent fix 为零；确定性、GIS、资源和完整回归通过。

## 方案 A Carrier 基线质量门禁

- 51/51 Case，排除项零出现；全部输入 manifest/hash/CRS 可定位。
- T01 Segment、ID、`pair_nodes/junc_nodes` 覆盖 100%，骨架 mutation 为零。
- 全部 `advance_right` 为 `ADVANCE_RIGHT Segment`，当前 `SegmentConnector` 为零。
- 每个 Segment 的独立 SWSD Road 证据可定位；Road/Node 不合法时 clue 与 FAIL 100% 输出，不修复。
- 策略三态映射、carrier label weight/mask/lineage、RealityChangeClue 和 fallback 闭包覆盖 100%。
- 两轮 skeleton/baseline/label/clue/fallback signature 一致；`content_repair=false`、`silent_fix=false`。
- P95/max `<=30s/120s`、RSS `<=16GB`、GPU 不需要、总 CPU `<=1h`。

上述 JSG-PTO-P0/P1/P2/P3 指标为历史实验门禁，不是当前方案 A 业务门禁。

方案 A baseline 已通过本节门禁：修正 fallback 边界后的正式 Run A/B 为 `p05_scheme_a_baseline_20260722_12/_13`，五类业务 signature 一致，完整 P05 回归通过。PASS 允许后续在冻结骨架与 mask 上研究 scorer，不把 40 个不可发布 Segment 或 913 条 clue 自动改写为真值。

Scheme-A-P1 Gate 4 要求每 seed 的51 Case均有确定终态：49 Case为 `LEGAL`，`T10:74155468` 与 `T10:609214532` 为 `EXPECTED_FAIL`。两个预期失败必须保持在模型与异常指标分母中，输出 clue 且禁止发布；任何额外失败、错误合法化、expected-failure 漂移、repair或 silent fix 均为 Gate 4失败。

Scheme-A-P1 已完成：Gate 0/4/5 PASS，Gate 1/2/3 FAIL，正式结论 `P05_SCHEME_A_P1_MODEL_NO_GO`。三 seed Segment macro-F1=`1.0000/1.0000/0.9869`、Movement exact=`1.0`，但 accepted coverage=`0.3637/0.3589/0.3533`；seed 29/43 anomaly precision=`0.7684/0.7472`。truth-exact 执行 coverage=`0.36933`，不得用错误 carrier 替换提升覆盖率。

## Scheme-A-Dataset-P0 质量门禁

- 范围固定为 741 sample、51 RoadGraph Case、8,863 Segment，批准排除不得进入启用任务；T07=`DRIVEZONE_ONLY`，Movement candidate/decision/evaluation=0。
- sample/artifact/task 的模块角色、lineage、hash、权重和 mask 完整；T01 RCSD label、Unknown enabled label、truth input/derived candidate、split conflict 均为0。
- 非 T01 `USE_RCSD` Road reachability 至少 `0.95`；可用 Segment Road、T06 final Road/Node 为 `1.0`，联合 exact 至少 `0.90`。
- 保持 49 `LEGAL` + 2 `EXPECTED_FAIL`，新增失败、relaxation、repair、silent fix 为0；CRS/ID/source 可解释，双跑内容 signature 一致，RSS不超过16GB、单次不超过2h、无需GPU。

正式 Run A/B 全部通过：`USE_RCSD=2190/2190`、可用 Segment=`8823/8823`、Road=`23224/23224`、Node=`27553/27553`、联合 exact=`1.0`，两轮 wall约5.2秒、RSS低于0.30GB，结论 `P05_SCHEME_A_DATASET_P0_GO`。该结果不包含 scorer OOF 和在线 proposal 性能。

## Scheme-A-P2-P1质量门禁

- candidate/label隔离、forbidden feature、fold leakage为0，Segment/Node truth和JunctionUnit compatibility Oracle均100%。
- 3 seeds × 5-fold中每seedSegment macro-F1>=0.98、USE_RCSD recall>=0.85、JunctionUnit Node exact>=0.90、ECE<=0.10。
- 每seed错误自动替换=0，总体和USE_RCSD safe accepted coverage均>=0.50，hard conflict recall=1.0、anomaly precision>=0.80。
- 每seed49 LEGAL + 2 EXPECTED_FAIL，新增失败、骨架mutation、relaxation、repair、silent fix均为0。
- 参数1M~5M，RAM<=16GB、VRAM<=8GB，3 seeds训练<=6h，单Case scoring P95/max<=5s/20s。

正式结果为`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`：数据、Node exact、ECE、49+2、确定性和资源通过；错误接受为`17/9/17`，总体coverage为`0.3102/0.3502/0.5150`，`USE_RCSD` coverage为`0.0999/0.0027/0.2658`，anomaly precision为`0.3460/0.2851/0.3936`，seed43 macro-F1为`0.8190`。训练wall=`471.231s`，scoring P95/max=`0.300s/0.968s`，峰值working set约`1.063GB`。

P2-P2-P0正式结果为`P05_SCHEME_A_P2_P2_P0_CALIBRATION_NO_GO_SAFETY_HEAD_GO`：P2-P1对象级错误接受仍完整保留，但真正accepted Segment根错误为`2/0/3`；40 Review自动发布均为0，正式可发布Case的effective Segment→Node requirement conflict/mismatch均为0。单一score/anomaly信号最佳零错误USE覆盖`0.200275 < 0.50`，完整feature跨truth精确碰撞为0。本阶段只放行后续safety-head技术讨论，不放行训练或生产。

P2-P2-P1正式结果为`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`：三seed accepted wrong=`5/0/4`、总体coverage=`0.374817/0.069841/0.296288`、USE coverage=`0.431714/0.066911/0.380843`，没有seed同时达到零错误和两个0.50覆盖门；40 Review自动发布均为0。每seedRoadGraph均为49 `LEGAL`+2 `EXPECTED_FAIL`，conditioned Node mismatch、payload conflict和unexpected failure均为0，说明失败门是safety model而不是整图执行。

P2-P2-P2-P0要求每个probe的每个held-out fold同时达到accepted wrong/9 error auto/Review auto=`0/0/0`、unsafe fallback recall=`1.0`和总体/USE coverage均`>=0.50`。线性probe全局为`2/2/0/0.969169/0.525217/0.741980`，1/5 fold通过；浅层MLP全局为`0/0/0/0.994191/0.548686/0.755729`，0/5 fold通过。两种probe的RoadGraph均49+2且conditioned Node conflict/mismatch为0，故正式结果为`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`。

P2-P2-P2-P1要求9 error、13 residual unsafe accepted和40 Review的62对象无重复、无漏归因且终态互斥；直接与辅助证据均须有source role、生成时点、推理可用性、成本和lineage。正式结果62/62完成，`INFERENCE/SOURCE_BLOCKED/UNOBSERVABLE=40/22/0`，新增获准直接推理证据为0，双跑signature一致，判定`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`。

P2-P2-P2-P2要求carrier accepted wrong/Review auto=`0/0`、carrier safety recall=`1.0`、每fold总体与USE coverage均`>=0.50`；clue recall独立报告。浅层MLP全局carrier门通过且clue miss为13，但仅2/5 fold通过coverage。22/22候选可达、26/57 Junction闭包、49+2 RoadGraph、双跑与资源通过，最终为`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`。

P2-P3-P0要求上述carrier门逐seed逐fold通过，并增加clue recall=`1.0`、precision`>=0.80`、macro-F1`>=0.85`和13/13 clue-only捕获。正式carrier wrong=`1/1/0`，fold 2总体/USE coverage约`0.29/0.32`；clue recall=`0.9844/0.9852/0.9987`且13对象捕获=`9/8/12`。49+2 RoadGraph、双跑、source-role、参数、资源与性能通过，但业务模型门失败。

P2-P3-P1要求输入/分母、逐对象归因、字段角色互斥和双跑资源门通过；`MODEL_RESTART_GO`还要求新增合法直接证据与独立冻结验证集同时存在。正式Gate 0/1/2/5通过，字段违规为0，但新增直接证据与独立验证均为0，因此为`EVIDENCE_NO_GO`。fold 2 eligible-only coverage只作诊断，未获授权替代原50%门。

Dataset-P1要求45/45 Segment包可由direct ID或无歧义Road partition定位；
8,863个当前Segment只能唯一归入label/context，context label leakage=0；
两个expected-failure Case保持49+2但Case级 scorer cascade mask=0。正式
41 direct（5 drift）+4 partition、6,275 label+2,588 context全部通过，
双跑signature一致，判定`P05_SCHEME_A_DATASET_P1_GO`。该门禁不含模型训练。

P2-P3-P2在6,275个eligible对象上继续要求逐seed/逐fold accepted wrong与Review
auto=`0/0`、carrier safety recall=`1.0`、总体和USE coverage均`>=0.50`；clue
recall=`1.0`、precision`>=0.80`、macro-F1`>=0.85`且5/5 eligible clue-only捕获。
正式accepted wrong=`1/13/0`、Review auto=`0/12/0`；seed317虽零错误但总体/USE
coverage=`0.1506/0.2757`。49+2、scope、确定性、资源和无泄漏通过，模型业务门失败，
故结论为`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`。

P2-P3-P3要求eligible与冻结清单全量1:1、40个invalid access只对应40 Review、
非Review误触发为0；重放后Review auto=`0/0/0`、accepted wrong=`1/1/0`、
context auto=0且每seed49+2。正式双跑全部通过；残余对象三个seed均大margin错误
排序、60/60近邻均为USE，故结论为
`P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED`。

P2-P3-P4要求scope分母`8,863=6,275+2,588`，context标签贡献为0且2,588个
全部安全KEEP；初始Node冲突10、Junction fallback Segment 21（eligible 10）、
最终Node truth 28,240且冲突/missing为0；delta必须为`436=435 context+1
eligible`。唯一eligible delta必须精确恢复残余对象为USE candidate
`sap1:918ffd80e766808f8a6b516c`。正式三seedaccepted wrong/Review auto均为0，
但seed/fold coverage/clue门未全部通过，故truth rebaseline GO与model NO-GO必须
同时成立。

P2-P3-P5沿用逐seed、逐fold门：wrong/Review auto=`0/0`、carrier safety
recall=`1.0`、总体与USE coverage均`>=0.50`；clue recall=`1.0`、precision
`>=0.80`、macro-F1`>=0.85`且本fold登记clue-only全部捕获。正式三seed的
safe coverage=`0.4290/0.5498/0.1374`、USE coverage=
`0.6918/0.7044/0.2310`；clue recall/precision/macro-F1=
`0.9805/0.6614/0.8512`、`0.8831/0.9985/0.9596`、
`0.9960/0.3605/0.5751`。RoadGraph、资源、确定性、无泄漏和范围门通过，
carrier/clue门失败，故为`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。

P2-P3-P6把P5质量结果校正为双层：每seed6,275条唯一join，safe coverage以6,235个
非Review为分母；scorer wrong=`1/1/1`、coverage=
`0.652446/0.795188/0.346913`，final wrong=`0/0/0`、coverage=
`0.429030/0.549800/0.137450`。每seedexpected-failure原子阻断1,954个eligible，
局部failure group仍为2。稳定FP/FN、collision、邻域、防泄漏和双跑门全部通过，
故归因GO；P5模型门不重判。

P2-P3-P7的来源、hash、CRS、6,275对象覆盖、602维有限值、15个inner calibration
pool隔离和双跑门全部通过。稳定wrong的top-20仍为
`20/20 USE_RCSD + 20/20 clue=false`，表征门失败；三个seed的recall=1单调阈值
precision/macro-F1均未过`0.80/0.85`，校准路线失败。因此审计可信但当前来源
NO-GO，不允许启动训练。

P2-P3-P8的来源、hash、CRS、字段角色、Case-local join、双跑和资源门全部通过。
稳定carrier wrong存在2个train-only `KEEP_SWSD + clue=true`同类来源且无
`USE_RCSD`同类对象，carrier门通过；稳定Clue错误适用来源仅`1/6`，Clue门失败。
因此正式结果为carrier-only partial GO，T03/T04角色仍不改变。

P9 promotion门要求无来源零差异、Clue零source消费、每seed carrier wrong=0、
safety recall=1.0且稳定wrong自动选择正确KEEP；完整carrier门继续要求逐seed/fold
总体与USE coverage均`>=0.50`。

正式P9的无来源、Clue、RoadGraph、确定性和资源门通过，但三seed scorer wrong均为1，
safety recall=`0.97778/0.97778/0.97619`，稳定对象仍选`USE_RCSD`；适用子集
Control/Treatment pooled macro-F1/KEEP recall均为
`0.9986769935/0.99609375`。正式判定
`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`。Run A/B wall=
`375.97s/355.44s`、RSS=`2.72/2.66GiB`、P95=`0.114/0.100s`。

P10要求五条裁决在两arm、三seed唯一命中，未裁决对象candidate-exact，裁决对象按
allowed/preferred/clue分层；wrong accepted、Review auto publish和Junction fallback
violation均为0，carrier safety recall为1.0。正式复算满足安全门，适用对象合法
准确率为1.0，但两臂优选命中率同为`0.9980158730`、strict gain=false；Clue pooled
precision/recall/macro-F1=`0.583278/0.987197/0.804359`、FP/FN=`3140/57`，稳定
Clue漏报为0、稳定误报为50。结论为
`P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`。

P12R硬门要求474/474 lineage、6个登记Case、40个invalid access全部Review、自动
真值两侧source一致、T05提右label=0、挂接/独立Road/unsafe publish=0、CRS为米制、
双跑一致且无训练/写geometry。上述门全部通过。候选门要求总体recall`>=0.95`且
最差5-fold recall`>=0.90`；正式结果为`0.952020/0.875`，故只判
`P05_SCHEME_A_P2_P3_P12R_CANDIDATE_REMEDIATION_REQUIRED`，不得用总体过线掩盖
最差Case fold失败。

P12R-R1要求Control 474/474复现P12R、P12R硬门全过、候选冻结前label read=0、
T05/T06推理泄漏=0、歧义或证据不完整候选自动加入=0、overall recall`>=0.95`、
最差fold recall`>=0.90`、无fold下降、候选数P95/max`<=10/32`、unsafe publish=0，
并要求6/6 Case CRS一致且为米制投影、正式双跑确定。正式结果为Control/Treatment
`0.952020/0.979798`、最差Treatment fold=`0.916667`、gain/loss=`11/0`、
P95/max=`4/12`，全部质量门通过，判定
`P05_SCHEME_A_P2_P3_P12R_R1_CANDIDATE_GO`。

P13-P0 selection门要求pooled/worst-fold raw exact`>=0.95/0.90`、candidate/object
macro-F1均`>=0.90`且不低于Local Control；安全门要求每seed/fold unsafe、
Review和R1不可达RCSD发布均为0，零错误accepted coverage总体/最差fold
`>=0.50/0.30`。正式结果为raw exact`0.646907`、最差fold`0.363636`、
macro-F1=`0.750984/0.791407`、相对Control=`-0.033505`；unsafe/Review/
unreachable=`14/2/1`，coverage=`0.017677/0`。故selection与safety门均失败。
