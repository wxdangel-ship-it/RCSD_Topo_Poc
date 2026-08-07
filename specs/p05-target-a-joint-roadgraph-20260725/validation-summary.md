# P05 Target A 第一轮训练验证摘要

## 结论

当前已经进入训练状态，但第一轮结论为 **NO_GO**，不能进入生产，也不能
把现有锚定或普通 Segment 输出作为安全自动替换结果。

本轮证明了两个事实：

1. Target A 联合模型方向可训练。补入合法的 T01 道路臂、原始 RCSD 道路臂
   匹配和 DriveZone 相对证据后，锚定状态与对象选择均明显改善。
2. 当前仍未满足业务安全目标。折外锚定门禁仍有错误自动接受，普通 Segment
   串联后也仍有错误 Road 方案；AdvanceRight 与完整 RoadGraph 尚未进入训练。

## 数据与监督

- 数据根：`E:\TestData\POC_Data`；
- Case：`51`；
- Segment：`8863`；
- 业务训练目标 Segment：`6275`；
- 上下文 Segment：`2588`；
- Movement：`0`；
- 人工裁决：`5`；
- T05 锚定样本：`4490`；
- T03/T04 单点状态样本：`689`；
- 联合锚定样本：`5179`；
- 对象级可监督锚定：`3251`；
- T05 relation 缺记录但属于正式语义路口的未决 ABSTAIN：`835`。

`NO_EVIDENCE`、原因未决的 `ABSTAIN`、正向 `KEEP_SWSD` 与后续 fallback
均保持不同语义；没有把缺记录补造成无 RCSD 证据、Clue 或 KEEP。

## 主要工件

- 标签：
  `outputs/_work/p05_neural_road_generation/target_a_label_store_20260726_07`
- v4 锚定 feature/label store：
  `outputs/_work/p05_neural_road_generation/target_a_anchor_joint_store_20260726_04`
- v4 锚定五折 OOF：
  `outputs/_work/p05_neural_road_generation/target_a_anchor_joint_oof_cpu_20260726_04`
- v4 锚定折外安全门禁：
  `outputs/_work/p05_neural_road_generation/target_a_anchor_safety_oof_cpu_20260726_04`
- 普通 Segment truth-free 候选：
  `outputs/_work/p05_neural_road_generation/target_a_plan_candidates_20260726_03`
- 普通 Segment 标签预检：
  `outputs/_work/p05_neural_road_generation/target_a_plan_preflight_20260726_07`
- 普通 Segment teacher-forcing OOF：
  `outputs/_work/p05_neural_road_generation/target_a_ordinary_teacher_oof_cpu_20260726_02`

上述目录均为 ignored 研究工件，不进入 Git。

## 锚定结果

模型参数量为 `17,452,173`。v4 单 seed、5 Case folds 诊断性 cross-fold：

| 指标 | v3 | v4 |
|---|---:|---:|
| OOF 覆盖 | 5179/5179 | 5179/5179 |
| status accuracy | 0.774474 | 0.898629 |
| supported macro F1 | 0.603274 | 0.791797 |
| SUCCESS precision | 0.960390 | 0.972103 |
| SUCCESS recall | 0.892665 | 0.898046 |
| NO_EVIDENCE F1 | 0.293144 | 0.543544 |
| ABSTAIN F1 | 0.591388 | 0.898241 |
| 对象 acceptable exact | 0.828668 | 0.841587 |

v4 诊断性折外安全校准：

- raw SUCCESS：`3262`；
- raw unsafe SUCCESS（状态错误、对象错误或对象不可证明）：`662`；
- 安全门禁接受：`240`；
- 正确接受：`236`；
- 错误自动接受：`4`；
- accepted coverage：`0.046341`；
- 结论：`safety_gate_pass=false`。

`SINGLE_POINT` 只有状态监督、没有对象级真值，因此永不自动接受；它仍参与
状态预训练，但不计作可发布锚定。

## 普通 Segment 串联结果

普通 Segment teacher-forcing OOF 在候选可达范围内为：

- 完整 Road 方案 acceptable exact：`0.904200`；
- always KEEP baseline：`0.792591`；
- USE_RCSD 完整方案 exact：`0.717045`。

把 v4 锚定门禁作为硬前置后：

- 候选可达普通 Segment：`4238`；
- 全部 required anchors 通过：`88`；
- 锚定门禁覆盖：`0.020765`；
- 依赖错误锚定：`4`；
- Road 方案 exact：`83/88 = 0.943182`；
- 错误 Road 自动方案：`5`；
- 自动正确覆盖：`83/4238 = 0.019585`；
- fold 4 可进入 Segment：`0`。

因此当前不能执行可信的 T032 五折锚定条件化普通 Segment 重训。下游分数
不得反向选择或修正锚定对象。

## 三种子诊断与 OOF 合同修正

补充两个 seed 后，旧 runner 的三个诊断性 cross-fold 结果为：

| seed | status accuracy | supported macro F1 | 对象 acceptable exact |
|---:|---:|---:|---:|
| 20260726 | 0.898629 | 0.791797 | 0.841587 |
| 20260826 | 0.868314 | 0.730674 | 0.836973 |
| 20260926 | 0.893802 | 0.780188 | 0.839742 |

三种子一致性门接受 `284` 个锚定，其中正确 `280`、错误 `4`；四个错误为：

- `T10:609214532 / 509457318`：原因未决的 relation 缺记录应为
  `ABSTAIN`，却自动选择 `NODE:5384379656965693`；
- `T10:609214532 / 60262124`：原因未决的 relation 缺记录应为
  `ABSTAIN`，却自动选择 `NODE:5384392105855232`；
- `T10:609214532 / 600668613`：应选择
  `NODE:5395562812284807`，模型选择
  `NODE:5395562812284899`；
- `T10:1885118 / 503668754`：应选择三 Road bundle，模型选择缺少
  `5384374355559979` 的两 Road bundle。

该共识串联 teacher-forcing 普通方案后，`4238` 个候选可达普通 Segment 中
`157` 个通过锚定门，`146` 个整链正确、`11` 个错误；其中 `1` 个由错误锚定
传播，`10` 个是普通 Road 方案自身错误。仍不得启动 T032。

随后代码审计发现旧 runner 把 outer held-out fold 同时用于 early stopping
与最终指标，因而上述全部 cross-fold 数值只能用于故障诊断，不能作为正式无泄漏
OOF 性能。当前已改为严格 outer/inner 合同：inner validation 只决定 epoch 和
安全阈值；随后以固定 epoch 在全部 outer-train 上重训；outer 标签只作最终评价。
v8 模型的 anchor status head 同时观察语义路口、候选集合和当前选中候选；
其严格 nested `3 seeds × 5 folds` 已完成，正式性能见后文。

## 泄漏、I/O 与治理

- T03–T06 终态 feature：`0`；
- 绝对坐标 feature：`0`；
- raw ID embedding：`0`；
- outer held-out early-stopping access：旧诊断 runner 为 `1`，严格 nested
  runner 合同为 `0`；
- truth-derived candidate：`0`；
- Movement 标签/输出：`0`；
- skeleton mutation：`0`；
- silent fix：`0`；
- 正式新入口：`0`；
- T01–T12 实现或接口修改：`0`。

城市级数据按 Case 一次读取并建立内存空间索引；训练读取 immutable
feature/label store，不反复物化 RoadGraph。

## 尚未完成

- T012–T014 的完整业务候选/ownership/access/topology hard masks；
- T032 锚定条件化普通 Segment；
- T033–T034 conditional AdvanceRight；
- T035 joint fine-tuning；
- T036 3 seeds × 5 folds；
- 完整 RoadGraph decoder 串联、49 LEGAL + 2 EXPECTED_FAIL；
- 与现有完整策略 paired comparison；
- 自动决策整图 exact、fallback 后整图 exact 与城市级 runtime profile。

严格 nested 锚定 OOF 与 inner-only 三种子安全门禁已于 2026-07-27 完成；
结果见下节。只有正式 outer OOF 锚定零错误且各 fold 有足够 Segment 通过，
才进入普通 Segment 条件化重训和 AdvanceRight。

## 严格 nested 锚定与 T01 依赖图验证（2026-07-27）

### v8：单锚定 forward 正式结果

旧诊断 runner 的外层标签泄漏已排除。v8 使用每个 outer fold 内部的
inner-validation 选择 epoch 和安全阈值，再以固定 epoch 在完整
outer-train 上重训；outer 标签仅用于最终评价。三种子共识结果：

- OOF examples：`5179`；
- 自动接受：`281`；
- 安全自动锚定：`275`；
- 危险自动锚定：`6`（NODE `3`、ROAD `3`）；
- accepted coverage：`0.054258`；
- Fold 2 安全自动锚定：`0`；
- `safety_gate_pass=false`。

### v9：冻结 T01 直接依赖 ego graph

v9 不引入 T03–T06 终态，也不把标签、绝对坐标或 raw ID embedding 放入
feature。每个 SWSD 语义路口是唯一 focal 锚定对象；其上下文由冻结 T01
目标 Segment 的 `pair_nodes/junc_nodes` 直接依赖构成。依赖邻居只进入
shared encoder，只有 focal 对象进入候选 head 和 loss。

数据与模型：

- examples/forward groups：`5179`；
- T01 直接依赖引用：`26189`；
- 平均有效对象：`5.0568`，最大 `43`；
- 多对象 group：`4473`，单对象 group：`706`；
- 参数量：`17,825,294`；
- feature store：约 `126.64 MB`；
- 训练期间只读 immutable store，不重复物化 Case RoadGraph。

严格 `3 seeds × 5 folds` OOF：

| seed | status accuracy | supported macro F1 | 对象 acceptable exact |
|---:|---:|---:|---:|
| 20260727 | 0.813864 | 0.625808 | 0.811234 |
| 20260827 | 0.835296 | 0.655002 | 0.815224 |
| 20260927 | 0.782197 | 0.585386 | 0.819521 |

三种子 inner-only 共识：

- 自动接受：`1312/5179`；
- 安全自动锚定：`1281`；
- 危险自动锚定：`31`；
- accepted coverage：`0.253331`；
- NODE 危险自动锚定：`17`；
- ROAD 危险自动锚定：`14`；
- 按标签：`ABSTAIN` 被错误自动锚定 `17`，`SUCCESS` 对象错误 `14`；
- Fold 2 自动接受与安全自动锚定均为 `0`；
- `safety_gate_pass=false`。

危险项分布于 `T10:609214532`（11）、`T10:706247`（10）、
`T10:1885118`（8）、`T10-Error:1511625_1514722`（1）和
`T10:991176`（1），不是单一 Case 偶发误差。

### 结论

T01 业务依赖进入 shared encoder 后，候选 acceptable exact 没有改善，
安全门反而从 v8 的 `6` 个危险自动锚定恶化为 `31` 个。当前联合
status/candidate head 会把依赖上下文转化为过度自信，不能区分：

1. 是否存在足以锚定的证据；
2. 锚定对象应为 Node 还是 Road/打断关系；
3. 唯一 Node 或最小完整 Road 组合究竟是哪一个。

因此本轮只判定当前锚定实现 **NO_GO**，不判定目标 A 或神经网络整体
NO_GO。普通 Segment 条件化训练、AdvanceRight 和完整 RoadGraph decoder
均未启动，避免错误锚定向后传播。下一轮锚定结构必须先拆分上述三个业务问题，
并保持锚定为下游不可绕过的硬门禁。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_anchor_joint_store_20260726_09_graph`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_graph_oof_cpu_20260727_v9_seed_20260727`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_graph_oof_cpu_20260727_v9_seed_20260827`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_graph_oof_cpu_20260727_v9_seed_20260927`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_graph_consensus_cpu_20260727_v9_01`

## v10：evidence/type/object 分层锚定（2026-07-27）

### 监督可辨识性

现有 store 不需要补 Case 即可监督分层结构：

- SUCCESS=`3542`；
- NO_EVIDENCE=`190`；
- ABSTAIN=`1447`；
- 有对象级监督=`3258`；
- 只接受 Node=`2280`；
- 只接受 Road=`898`；
- Node/Road 均为可接受多解=`80`。

类型层对最后一类使用 acceptable-set loss，不把可接受多解强制改写成唯一类型。
证据状态头不读取已选候选；推理先锁定 Node/Road 类型，再只在该类型内部选择
具体对象。模型参数量为 `18,818,992`。

### 单 seed 严格 nested OOF

run：
`target_a_anchor_strict_nested_hier_graph_oof_cpu_20260727_v10_seed_20260728`

| 指标 | 结果 |
|---|---:|
| examples / OOF coverage | 5179 / 5179 |
| status accuracy | 0.798031 |
| supported macro F1 | 0.598006 |
| SUCCESS precision | 0.946598 |
| SUCCESS recall | 0.930830 |
| 类型 acceptable exact | 0.934009 |
| 对象 acceptable exact | 0.812462 |
| 类型正确、对象错误 | 396 |

逐折对象 acceptable exact 为 `0.825726 / 0.815730 / 0.774920 /
0.792176 / 0.814898`。Fold 2 仍是稳定最差折，分层结构没有修复其跨 Case
泛化问题。

按每个 outer fold 的 inner-validation 独立生成单 seed 诊断安全阈值：

- 自动接受=`1387/5179`；
- 安全自动锚定=`1351`；
- 危险自动锚定=`36`；
- accepted coverage=`0.267812`；
- Fold 0/1/2/3/4 安全自动锚定=`607/492/0/89/163`；
- 危险标签：ABSTAIN `14`、NO_EVIDENCE `3`、SUCCESS 对象错误 `19`；
- 危险类型：NODE `28`、ROAD `8`。

### 结论

分层业务顺序已经落实，但统计和安全结果没有形成稳定改善。类型层达到
`93.40%` acceptable exact 后，仍有 `396` 个类型正确但具体对象错误；
说明剩余瓶颈主要是唯一 Node 组合、Road bundle 完整性及最小/完整组合之间的
结构化选择，而不是 Node/Road 类型判断。

v10 单 seed 已出现 `36` 个危险自动锚定且 Fold 2 仍为零覆盖，因此没有继续
训练另外两个 seed。当前实现 **NO_GO**，普通 Segment、AdvanceRight 与完整
RoadGraph 训练仍未启动。该结论不否定目标 A，只否定当前分层候选 softmax
足以解决锚定对象选择的假设。

## v11：候选成员关系与独立有效性监督（2026-07-27）

v11 针对 v10 的类型内对象错误，加入无标签候选成员关系：

- 同类型、成员相等、严格子集、严格超集；
- Jaccard、左右成员数、对称差；
- relation-aware 类型内候选上下文；
- balanced candidate-validity BCE。

这些关系只由推理期候选清单的成员相等/包含关系派生；具体 ID 不进入
embedding，T03–T06 终态与人工答案均不进入 feature。参数量
`19,318,833`，Target A 专项测试 `53 passed`。

pairwise 关系使 CPU 训练成本约为 v10 的 2–3 倍。按训练前确定的停止条件，
先比较前两个 outer folds：

| fold | selected epoch | status accuracy | supported macro F1 | 对象 acceptable exact |
|---:|---:|---:|---:|---:|
| 0 | 9 | 0.932318 | 0.850114 | 0.826556 |
| 1 | 1 | 0.752024 | 0.493170 | 0.791011 |

Fold 0 的状态指标改善明显，但对象 exact 相对 v10 同折只提高 `0.000830`；
Fold 1 则全面恶化。该收益不具备跨 Case fold 稳定性，无法证明高成本
pairwise decoder 有效。因此训练在 Fold 2–4 前主动终止，没有生成完整 OOF
summary，也不进行安全门或三种子扩展。

部分诊断工件：
`outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_structured_graph_oof_cpu_20260727_v11_seed_20260729`

v11 结论为 **DIAGNOSTIC_NO_GO**。它进一步说明，仅增加候选之间的包含关系
和通用有效性 BCE 仍不能学习 T05/T11 所需的业务完整性；下一步需要区分
Node 集合与 Road bundle 的组成语义，不能继续使用同一通用 pairwise decoder。

## v12–v15：组合式对象与 cardinality decoder

v12 将候选选择改为 Node/Road 成员组合式 decoder，保持 raw ID 不进入
embedding。完整严格 `5-fold nested OOF`：

- 参数量=`17,330,033`；
- status accuracy=`0.859818`；
- supported macro F1=`0.704314`；
- 对象 acceptable exact=`0.820135`。

v13r1 在组合分数上增加候选残差，只完成 Fold 0/1 诊断；对象 exact 分别为
`0.818257/0.835955`，没有形成稳定优于 v12 的收益，因此停止。

v14 将 Node/Road cardinality 作为硬锁定，只完成 Fold 0/1 诊断；对象 exact
分别为 `0.775104/0.835955`，Fold 0 明显退化，因此停止。该结果说明
cardinality 是有用条件，但不能在泛化尚不稳定时作为不可回退的硬选择。

v15 改为 soft cardinality 条件化并完成严格五折：

- 参数量=`17,918,129`；
- status accuracy=`0.916586`；
- supported macro F1=`0.829974`；
- 对象 acceptable exact=`0.829343`；
- strict inner-only 安全门接受=`1238`，安全=`1187`，危险=`51`；
- accepted coverage=`0.239042`。

v15 的状态指标较高，但随后正式重放证明其监督仍把 T03/T04 上游成功等同于
最终锚定成功，不能作为正式业务结果。soft cardinality 结构可保留，v15
标签口径必须废弃。

## 正式 T03/T04 → T05 重放与 v16

正式重放覆盖 `120` 个 T03/T04 单点成功 Case，并以 T05 最终关系重新定义
锚定监督：

- T05 最终成功对象=`103`；
- 明确 `no_related_rcsd` 的正向 `NO_EVIDENCE`=`5`；
- 最终原因未知、不得补造业务原因的 status/gate mask=`12`；
- `103` 个成功对象中，当前 truth-free 候选精确可达=`91`，另 `12` 个
  Road-only 完整集合不可达；
- v16 store examples=`5179`、status supervised=`5167`、
  candidate supervised=`3349`；
- inference feature SHA256=
  `b9ae220d7fb535a6e615a11d1bfc79cddce87119a63831dd9063c61bb1d51da6`。

v16 使用统一的 T05-style truth-free feature adapter 与修正标签，结构保持
v15：

- status accuracy=`0.786336`；
- supported macro F1=`0.605643`；
- 对象 acceptable exact=`0.812481`；
- strict inner-only 安全门接受=`1210`，安全=`1168`，危险=`42`；
- accepted coverage=`0.233636`。

指标下降不是新模型退化的充分证据，而是旧监督乐观偏差被纠正后的正式基线。
v16 同时证明单一 status head 不能承担“是否已解析、能否继续”的独立硬门禁。

## v17–v19：learned gate 与二阶段训练

v17 增加 learned gate，第一版只监督已有明确 gate 事实的 `4301` 个对象：

- 总参数量=`18,415,507`；
- status accuracy=`0.905361`；
- supported macro F1=`0.795889`；
- 对象 acceptable exact=`0.819648`；
- gate accuracy=`0.968147`，failure recall=`0.978910`；
- strict inner-only 安全门接受=`774`，安全=`758`，危险=`16`；
- accepted coverage=`0.149450`。

16 个危险项中，9 个是未被 gate 监督的 ABSTAIN 被放行，7 个是 SUCCESS
状态正确但完整候选对象集合错误。

v18 将所有有正式最终状态的对象监督为 resolved/unresolved：`5167` 个 gate
标签，其中 unresolved=`1447`、resolved=`3720`；12 个最终状态未知对象继续
mask，不补造原因。将该 loss 与 shared encoder 联合训练后：

- status accuracy=`0.875556`；
- supported macro F1=`0.689393`；
- 对象 acceptable exact=`0.818453`；
- gate failure recall=`0.817554`；
- strict inner-only 安全门接受=`969`，安全=`924`，危险=`45`；
- Fold 2 自动接受=`0`。

v18 明确暴露跨任务负迁移，结论为 **JOINT_GATE_NO_GO**。

v19 冻结 v17 shared encoder、status head 与 candidate decoder，仅二阶段训练
既有 gate head；inner validation 选择 epoch，outer 只按固定 epoch 拟合，
并只保存约 `1.99MB` gate delta：

- shared/candidate 参数更新数=`0`；
- 五折总 wall time=`635.50s`；
- 对象 acceptable exact 与 v17 逐样本保持一致=`0.819648`；
- ABSTAIN recall=`0.920525`；
- strict inner-only 安全门接受=`920`，安全=`901`，危险=`19`；
- Fold 2 接受=`22`，均安全；单点危险=`0`。

v19 证明“门禁独立训练”是正确边界，但冻结的 base embedding 仍不足以辨识
全部 resolved/unresolved，结论为 **POSTHOC_GATE_NO_GO**。

## v20：独立 evidence encoder

v20 不使用 base embedding，直接从推理期可用事实构建 `583D` truth-free
证据向量：

- focal object `64D`；
- candidate set 的 mean/std/min/max；
- T01 直接依赖对象的 mean/std/min/max；
- 候选数、依赖数、Node/Road 候选数与候选成员数统计。

模型为 `124,994` 参数 MLP；不使用终态字段、raw ID embedding、绝对 ID
或 T03–T06 推理结果。严格 outer/inner 五折结果：

- gate accuracy=`0.947552`；
- gate failure recall=`0.930200`；
- status accuracy=`0.915231`；
- supported macro F1=`0.795827`；
- ABSTAIN recall=`0.946095`；
- 对象 acceptable exact 保持=`0.819648`；
- strict inner-only 安全门接受=`740`，安全=`727`，危险=`13`；
- accepted coverage=`0.142885`；
- Fold 2 接受=`20`，均安全；
- 单点接受=`2`，均安全。

同 seed 通过正式 callable 复跑后，OOF、inner calibration 和 gated OOF
三份 JSONL 的 SHA256 均与诊断运行逐字节相同。v20 是当前最好单 gate，
但 13 个危险自动锚定仍非零，因此结论为 **BEST_SINGLE_GATE_NO_GO**。

v17/v19/v20 三 gate 交集仍有 `10` 个稳定危险项：只分布于
`T10:706247`、`T10:609214532`、`T10:1885118`；其中 6 个为完整对象集合
错误，4 个为 unresolved 被判 SUCCESS。禁止按 Case ID 硬编码排除。

曾按 T01 依赖传递闭包执行整组原子接受，得到 `9` 个接受、`9` 个安全、
`0` 个危险、coverage=`0.001738`；三个主要 T10 Case 的连通分量分别达到
上千对象。2026-07-27 业务复核确认 Segment/Junction 是硬阻断边界：Segment
fallback 止于自身，Junction fallback 止于直接关联 Segment，不得沿
`Junction—Segment—Junction` 传播。因此该 `9/5179` 结果现仅作为错误扩大
fallback 的反例，不是安全下界、正式覆盖率或 decoder 输入。

## v21–v25：member 完整性与安全门边界诊断

v21 在 v20 之后增加 candidate safety verifier，但仍只使用推理期证据和
候选输出，不读取标签终态。严格 nested OOF 得到：

- 自动接受=`727`，安全=`716`，危险=`11`；
- 危险项中 4 个为 ABSTAIN 被放行，7 个为 SUCCESS 的完整候选集合错误；
- 7 个候选错误包括 Node/Road 类型错误、Road 超集、Road 子集和错误 Node；
- verifier 对部分错误候选仍给出 `0.98–0.999` 高分。

因此继续在相同表征上叠加 verifier 不能形成可靠安全边界，结论为
**CANDIDATE_VERIFIER_NO_GO**。

v22 从组合式 decoder 的 member logits 派生集合概率、包含/排除 margin、
成员数残差和 entropy。即使使用 outer 标签作纯 oracle 阈值诊断，零危险时
最多也只能保留 `90/716` 个安全自动决定，且若干危险项具有极高 member
置信度。member 绝对置信度不能作为事后安全校准器。

v23 将既有 member loss 权重从 `0` 提升到 `0.5`，对象 acceptable exact
由 v17 的 `0.819648` 小幅升至 `0.823231`，但：

- supported macro F1 降至 `0.759273`；
- ABSTAIN recall 降至 `0.818936`；
- shared encoder 上出现明确的状态/候选负迁移。

v24 在 v23 表征上重新独立训练 `583D` gate，得到自动接受=`569`、安全=`548`、
危险=`21`，比 v20 更差。该 member-loss 路线终止，不继续叠加 verifier。

v25 尝试复用旧监督下 candidate exact 较高的 v15 checkpoint，但旧、新 replay
store 在 `689` 个对象的候选/特征、`91` 个 acceptable/preferred 集合、
`17` 个 status 标签和 `12` 个 status supervision 上不同；旧 store 也没有
当前正式 gate supervision。跨 replay 拼接 checkpoint、OOF 和 gate 标签不具备
同一监督语义，已在训练前拒绝，不产生正式模型结果。

v26 从当前正式 replay 重新训练 base，并完全移除 shared learned-gate head/loss。
预先按两折稳定性止损：Fold 0 相比 v17 同折，status accuracy
`0.931073 → 0.898870`、supported macro F1 `0.843360 → 0.805390`、
candidate exact `0.829648 → 0.809992`；Fold 1 的 candidate exact 仅
`0.831126 → 0.833333`，但 status accuracy `0.893225 → 0.868189`、
macro F1 `0.745078 → 0.730129`。两折未形成稳定收益，主动停止 Fold 2–4，
不启动基于该 base 的 v27 gate，结论为 **DECOUPLED_BASE_NO_GO**。

v28 冻结 v17 的 encoder、status、gate、type 与 cardinality，只训练
`373,122` 参数 candidate bundle residual，使 decoder 重新读取完整候选已有的
连通分量、叶节点、方向和 arm 聚合特征。两折诊断中 status accuracy、macro F1
逐项与 v17 相同，最大 status/gate 概率复算差分别不超过
`1.14e-6/3.58e-7`；但 candidate exact：

- Fold 0：`0.829648 → 0.837838`，提升 `0.008190`；
- Fold 1：`0.831126 → 0.826711`，下降 `0.004415`。

现有 64D 聚合候选特征只形成 Case 特异收益，未通过跨折稳定性门，停止
Fold 2–4，结论为 **POSTHOC_CANDIDATE_RESIDUAL_NO_GO**。下一步需要恢复当前
聚合特征丢失的 SWSD arm ↔ RCSD arm 集合对应关系和 Road 成员端点/方向关系，
而不是继续增加同类 residual、member loss 或置信度校准。

联合标签复用审计另发现 `114` 组重复 `anchor_id`，其中 `13` 组同时出现在
T03/T04 单点 Case 与 T10 完整 Case。13 组的 status 监督无冲突，但
`707267` 在两种上下文中的 acceptable 对象集合不同：完整 T10 上出现了单点
Case 不具备的额外 RCSD Node/Road 方案。由此确认 `anchor_id` 只可用于审计
同一业务对象，不能成为 embedding、标签复制键或跨 Case teacher 终态输入；
T03/T04 强标签必须通过可泛化的关系/几何模式进入训练。

2026-07-27 已按方案 A 修正 decoder：Road 所有权仍可联合求解，但 fallback
只接受显式 Segment/Junction 指令。Segment 指令只回退自身；Junction 指令
只影响显式列出的直接关联 Segment，并校验其与冻结 T01
`Junction—Segment` 关系一致；禁止沿 `Junction—Segment—Junction` 继续传播。

### 当前阶段结论

- 正式 replay、统一 feature adapter、独立 gate 训练边界与独立 evidence
  encoder 均保留；
- 当前最优单 gate 仍有 `13` 个危险，锚定发布门保持 **NO_GO**；
- T032–T036 继续禁止启动，普通 Segment、AdvanceRight 与完整 RoadGraph
  训练仍未开始；
- 下一轮必须分别解决：
  1. resolved/unresolved 的跨 Case 证据表征；
  2. Node 集合和 Road bundle 的完整性/唯一性与候选不可达；
  3. 将 SWSD 与 RCSD 的逐 arm 几何/方向/FC 证据、Road 成员端点关系作为
     truth-free set/graph 输入，替换只看聚合统计的候选表示。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_formal_replay_20260727`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_joint_store_20260727_13_resolved_gate`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_learned_gate_inner_safety_cpu_20260727_v17_01`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_resolved_gate_inner_safety_cpu_20260727_v18_01`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_posthoc_resolved_gate_strict_nested_cpu_20260727_v19_seed_20260731`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_independent_resolved_gate_strict_nested_cpu_20260727_v20r1_seed_20260732`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_candidate_safety_verifier_strict_nested_cpu_20260727_v21_seed_20260733`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_member_confidence_audit_cpu_20260727_v22_seed_20260730`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_member_supervised_learned_gate_soft_cardinality_graph_oof_cpu_20260727_v23_seed_20260734`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_member_supervised_independent_resolved_gate_strict_nested_cpu_20260727_v24_seed_20260735`

## 2026-07-28：T032 锚定条件化普通 Segment

### 数据与门禁口径

T032 已按方案 A 完成单 seed、严格 outer/inner Case OOF 诊断：

- 普通 Segment 样本=`4238`；
- OOF 锚定条件下标签仍可达=`4194`；
- 因 required anchor 未全部成功而必须 fallback=`44`；
- 缺失锚定条件=`0`；
- 正向 `KEEP_SWSD` 样本=`3358`，不要求 RCSD 锚定成功；
- `USE_RCSD` 样本=`880`，其中 `44` 个因锚定硬门禁不进入自动替换；
- 所有运行的 `unsafe_anchor_bypass_count=0`。

推理输入只使用 OOF 预测的锚定状态、gate 概率、已选 RCSD Node/Road
候选的 truth-free feature，以及候选 Road plan 与该锚定对象之间的
集合/端点关系。原始 ID 只用于关系 join 和审计，不进入 embedding；
T03–T06 终态、acceptable/preferred 标签和人工答案只进入 loss/评价。

### v35–v39：条件化平铺 plan 与关系 residual

| run | 参数量 | 完整 plan exact | KEEP exact | USE exact | 最差 fold |
|---|---:|---:|---:|---:|---:|
| v35 OOF anchor condition | 17,727,086 | 0.912017 | 0.961882 | 0.711722 | 0.730897 |
| v38 anchor-plan relation | 17,727,086 | 0.918455 | 0.958309 | 0.758373 | 0.800664 |
| v39 frozen-base relation residual | 17,740,848 | 0.920124 | 0.959797 | 0.760766 | 0.740864 |

v38 让候选直接观察“已选锚定 Node/Road 是否被当前完整 Road plan 覆盖”，
相对 v35 为 `141` 个修复、`114` 个回归，证明该关系是有效输入。v39 只在
冻结 v35 OOF logits 上训练 `13,762` 参数的有界 residual；总体略升，但最差
fold 显著退化，因此 residual 不作为正式基线。

### v40–v42：显式业务状态后再选完整 Road plan

错误分解显示，v38 的 `342` 个错误中，`281` 个是
`KEEP_SWSD ↔ USE_RCSD` 状态选反，只有 `61` 个是在已选 `USE_RCSD`
后 Road bundle 不完整。由此把 ordinary decoder 改为两层：

1. 显式输出 `KEEP_SWSD / USE_RCSD / ABSTAIN`；
2. 在已选状态内归一化并选择完整 Road 清单。

该结构不会把 carrier 输出降级为单个状态标签；最终输出仍是完整 Road plan。
状态内归一化还避免某个状态因候选 bundle 数量更多而天然获得更大概率质量。

| run | 训练差异 | 完整 plan exact | KEEP exact | USE exact | 最差 fold |
|---|---|---:|---:|---:|---:|
| v40 | joint plan loss + 额外 decision loss 1.0 | 0.916547 | 0.974092 | 0.685407 | 0.780731 |
| v41 | 仅 joint plan loss | **0.923939** | 0.955926 | **0.795455** | 0.787375 |
| v42 | v41 + partition-local Case balance | 0.922031 | 0.967838 | 0.738038 | **0.827243** |

v40 的重复 decision 监督把模型推向多数类 KEEP，产生 `209` 个
`USE_RCSD -> KEEP_SWSD` 错误，因此作废额外 decision loss。v41 相对 v38
为 `111` 个修复、`88` 个回归，是当前总体和 `USE_RCSD` 最好的普通 Segment
研究基线；其剩余 `319` 个错误包括：

- `KEEP_SWSD -> USE_RCSD`：`148`；
- `USE_RCSD -> KEEP_SWSD`：`104`；
- `USE_RCSD` 状态正确但 Road bundle 错：`67`。

v42 在每个训练/inner-validation 分区内给予各 Case 相同总 loss 质量，同时
保留原始 `1.0/0.7/0.3` 标签置信权重。它改善了最差 fold 和部分中小 Case，
但 `USE_RCSD` 退化，且部分分区的 Case 权重范围扩大到约
`0.09–175.38`，存在单样本 Case 支配训练的风险。因此 v42 只保留为诊断，
不继续权重搜索。

v41 各 fold 完整 plan exact 为
`0.937703/0.927318/0.920792/0.956284/0.787375`。主要 Case 中，
`T10:1885118` 相对 v38 的错误由 `129` 降至 `96`，但
`T10:605415675` 由 `32` 增至 `48`、`T10:74155468` 由 `27`
增至 `32`；两个单 Segment Error Case 也从正确退化为错误。它尚未满足
“各类 Case 最差表现不退化”的门禁。

### v43–v46：逐 Road 成员集合、状态内 bundle 与对称 arm 匹配

旧 64D plan 特征只提供长度、距离、方向和连通性的聚合统计，模型看不到
完整候选中的每一条 Road。新 truth-free candidate store 因此为 KEEP/USE
候选增加逐 Road 成员集合：

- 来源角色、方向、FC、Road/Segment 长度比和相对距离；
- Road 两端到 Segment 两端的距离、正反向顺序代价和方向夹角；
- 候选 Road 子图中的端点度数、叶节点和局部连接角色；
- 该 Road/端点是否与 OOF 锚定模型选中的 RCSD Road/Node 相关。

城市 Case 只读取一次 GPKG 并写入缓存；训练只读取缓存后的动态业务子图。
新 store 覆盖 51 Case、8,863 Segment 组、63,841 个候选和 241,052 条
Road 成员，其中 KEEP=`14,241`、USE=`226,811`。与 v41 使用的 store
逐候选比较，plan ID、decision、Road 清单、业务角色和原 64D 特征
`63,841/63,841` 完全不变；非空 Road 清单的成员覆盖缺失为 `0`。
manifest 记录 `EPSG:3857`、truth input=`0`、terminal feature=`0`、
raw-ID embedding=`0`、absolute-coordinate feature=`0`、
skeleton mutation=`0`、silent fix=`false`。

| run | 成员证据进入范围 | 完整 plan exact | KEEP exact | USE exact | 最差 fold | 最差 USE fold |
|---|---|---:|---:|---:|---:|---:|
| v41 | 无逐 Road 成员集合 | 0.923939 | 0.955926 | 0.795455 | 0.787375 | 0.678832 |
| v43 | 同时进入状态与 bundle | 0.928946 | **0.971412** | 0.758373 | 0.847176 | 0.663580 |
| v44 | 只进入已选状态内 bundle | 0.929423 | 0.967838 | 0.775120 | 0.843854 | 0.709877 |
| v45 | v44 + 对称两端 arm 跨状态残差 | **0.936338** | 0.970816 | **0.797847** | **0.850498** | **0.756881** |
| v46 | v45 arm + local/foreign 锚定关系 | **0.936576** | 0.967242 | **0.813397** | **0.857143** | **0.756881** |

v43 相对 v41 为 `133` 个修复、`112` 个回归，净增 `21`；其
`within-USE_RCSD` 错误由 `67` 降至 `46`，但
`USE_RCSD -> KEEP_SWSD` 由 `104` 增至 `156`，说明简单 mean/max
成员池化把集合形态学成了 KEEP 捷径。v44 保留成员证据用于同一业务状态内
的完整 bundle 排序，但业务状态 head 继续使用 Segment、OOF 锚定和原 plan
证据。v44 相对 v41 为 `120` 个修复、`97` 个回归，净增 `23`；
`within-USE_RCSD` 进一步降至 `37`，但跨状态错误仍为
`USE->KEEP=151`、`KEEP->USE=108`。

v44 主要 Case 错误为：`T10:1885118=125`、`T10:609214532=68`、
`T10:605415675=33`、`T10:74155468=27`、`T10:706247=23`、
`T10:991176=14`。相对 v41，后五个主要 Case 合计净改善 `51`，但
`T10:1885118` 净退化 `29`；一个单 Segment Error Case 也由正确退化为
错误。因此在加入 arm 证据前，v44 是总体和 bundle 完整性最好的中间基线，
v41 是 USE 总体对照；二者均不满足跨 Case 最差表现和发布门。

v45 在不改变任何候选、标签、原 64D plan 特征或 24D Road 成员特征的
前提下，为每个非空 KEEP/USE 候选增加两个 Segment arm：最近候选
Road/Node、叶端点距离、`5/15/30m` 局部端点密度、Segment/Road 向内方向
对齐和 OOF 锚定关系。两端通过 mask-aware mean/max 编码，交换 pair_node
存储顺序不改变 logits；arm 关系只是可学习证据，不构成锚定成功硬规则。
新 store 含 `109,956` 条 arm 记录，正好是每个非 ABSTAIN 候选两条；
缺失/非有限特征均为 `0`。模型新增 `25,120` 参数，总参数
`19,915,759`，仍低于 20M 门。

v45 相对 v41 为 `117` 个修复、`65` 个回归，净改善 `52`；相对 v44
净改善 `29`。错误分解为：

- `KEEP_SWSD -> USE_RCSD`：`98`；
- `USE_RCSD -> KEEP_SWSD`：`135`；
- `USE_RCSD` 状态正确但 Road bundle 错：`34`。

六个主要 Case 错误为：`T10:1885118=92`、`T10:609214532=75`、
`T10:605415675=36`、`T10:74155468=28`、`T10:706247=19`、
`T10:991176=10`；它们相对 v41 全部净改善或持平，未发现 Case 级净
exact 回归。v45 因而同时超过 v41/v44 的总体、KEEP、USE 与最差 fold，
成为当前 ordinary 结构基线。但单 seed 仍有 `267` 个自动完整 plan 错误，
且 T030d 锚定门仍未达到零危险发布要求，正式结论继续为 `NO_GO`。

v45 的 `135` 个 `USE_RCSD -> KEEP_SWSD` 错误全部来自权重 `0.7` 的
T10 Case 标签；在这批对象中，正确 USE plan 的 Road/Node 关系与当前
Segment 端点对应锚定和另一端锚定混在同一组布尔特征里。v46 因此只新增
端点条件化的 local/foreign OOF 锚定关系，不改变候选、标签、64D plan
特征、24D Road 成员特征或候选 Road 清单。模型参数为 `19,916,527`，
仍低于 20M 门；候选 manifest 仍为 truth input=`0`、terminal
feature=`0`、raw-ID embedding=`0`、skeleton mutation=`0`、
silent fix=`false`。

v46 的 paired 结果为 `41` 个修复、`40` 个回归，相对 v45 只净改善
`1`。错误分解为：

- `KEEP_SWSD -> USE_RCSD`：`110`，比 v45 增加 `12`；
- `USE_RCSD -> KEEP_SWSD`：`118`，比 v45 减少 `17`；
- `USE_RCSD` 状态正确但 Road bundle 错：`38`，比 v45 增加 `4`。

主要 Case 的自动错误为：`T10:1885118=85`、`T10:609214532=77`、
`T10:605415675=34`、`T10:74155468=28`、`T10:706247=27`、
`T10:991176=10`。虽然总体、USE 和最差 fold 略升，但
`T10:706247` 增加 `8` 个错误，且危险 `KEEP->USE` 总数明确上升。
按“准确性和安全性优先、零危险自动替换”的既定优先级，v46 不替代
v45；它只证明端点条件化锚定关系是可辨识信号，后续必须通过安全 head/
拒识门隔离危险方向，不能用降低 `USE->KEEP` 的代价换取更多自动替换。

### 当前结论

- T032 的实现与严格单 seed OOF 诊断已完成，任务状态从“未启动”更新为
  **已完成但 NO_GO**；
- v45 作为下一轮普通 Segment 结构基线，v44/v41 作为 paired 对照，
  v46 作为端点条件化关系诊断，v38 作为较低参数量对照；
- 不能把 `0.936338` 解释为完整 RoadGraph、完整 T03–T06 替代或可发布结果；
- T030d 锚定零危险发布门仍未完成；
- T033/T034 conditional AdvanceRight、T035 joint fine-tuning 与
  T036 `3 seeds × 5 folds` 暂不启动；
- 下一轮若继续 ordinary，不再搜索 class/Case 权重或后置 residual，
  先审计 v45 的 `KEEP_SWSD -> USE_RCSD` 危险错误及可独立拒识证据，
  再处理 `USE_RCSD -> KEEP_SWSD` 的关系缺口；保持 v45 的对称 arm
  与状态内完整 bundle 合同。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_conditioned_strict_nested_cpu_20260728_v35r1_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_relation_strict_nested_cpu_20260728_v38_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_relation_residual_strict_nested_cpu_20260728_v39_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_relation_hierarchical_strict_nested_cpu_20260728_v40_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_relation_hierarchical_joint_only_strict_nested_cpu_20260728_v41_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_relation_hierarchical_case_balanced_strict_nested_cpu_20260728_v42_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_plan_candidates_20260728_05_road_members`
- `outputs/_work/p05_neural_road_generation/target_a_plan_preflight_20260728_08_road_members`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_member_hierarchical_joint_only_strict_nested_cpu_20260728_v43_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_member_decision_local_hierarchical_joint_only_strict_nested_cpu_20260728_v44_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_plan_candidates_20260728_06_arm_relations`
- `outputs/_work/p05_neural_road_generation/target_a_plan_preflight_20260728_09_arm_relations`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_member_arm_hierarchical_joint_only_strict_nested_cpu_20260728_v45_seed_20260747`
- `outputs/_work/p05_neural_road_generation/target_a_plan_candidates_20260728_07_arm_local_relations`
- `outputs/_work/p05_neural_road_generation/target_a_plan_preflight_20260728_10_arm_local_relations`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_anchor_plan_member_arm_local_hierarchical_joint_only_strict_nested_cpu_20260728_v46_seed_20260747`

### v47–v48：USE safety head 与 Junction 邻接上下文

v47 固定 v45 carrier，不重新训练或修改锚定、KEEP/USE 状态和 Road bundle
排序；每个 outer fold 使用 v45 inner checkpoint 的预测训练 14,913 参数
safety MLP，在 inner validation 上把阈值校准到高于所有已知危险项，再评价
outer fold。历史 v45 的 16D arm checkpoint 通过零权重扩展到当前 22D
网络：旧 mean/max 两个 16D 半区逐列原位映射，新增 local/foreign 列为零。
五个 outer fold 的 4,238 个 plan ID 和概率全部与 v45 历史 OOF 工件一致，
证明不是重新训练造成指标漂移。

v47 的 462D safety 输入只含推理期证据：carrier 概率、Segment 与 OOF
锚定条件、选中 plan、逐 Road 成员、两端 arm 和候选集合相对关系；truth
只用于 inner fitting/calibration 和 outer evaluation。结果：

- raw automatic USE=`798`，其中正确 `666`、危险 `132`；
- accepted USE=`189`，正确 `180`、危险 `9`；
- accepted USE coverage=`0.236842`；
- safety 后全部自动业务决定=`3,585/4,238=0.845918`；
- 自动 plan exact=`0.959833`；
- use safety gate=`NO_GO`，完整 release gate=`NO_GO`。

9 个危险中 8 个是 `KEEP_SWSD -> USE_RCSD`，集中在
`T10:609214532`、`T10:605415675` 和 `T10:706247`；另 1 个是 USE
状态正确但 bundle 错。它们不是低概率尾部：carrier 概率最高
`0.954345`，safety score 也能高于 inner unsafe 阈值，说明一般概率校准
无法跨 Case 保证安全。

v48 进一步从 truth-free candidate store 的全部 8,863 个 Segment 构建
共享 required-anchor 邻接上下文。只纳入普通 Segment 的 object、候选
USE plan 聚合和候选数；ADVANCE_RIGHT 被排除，Segment ID/anchor ID
只作 join，标签作用域不参与邻居集合，避免“哪些对象有标签”泄漏。
安全输入增至 578D，head 为 18,625 参数，总参数 `19,934,384`。结果：

- accepted USE=`217`，正确 `203`、危险 `14`；
- accepted USE coverage=`0.271930`；
- safety 后自动覆盖=`0.852525`，自动 plan exact=`0.958760`；
- use safety gate=`NO_GO`，比 v47 的危险数进一步退化。

现有 `training_plan_labels.jsonl` 共 8,863 条，Clue 与 fallback-scope
task mask 各只有 `5` 条；4,238 个 ordinary 训练样本中只有 `4` 条：
3 个 `clue=false/NONE`、1 个 `clue=true/JUNCTION`，均来自用户人工
裁决。v47 的 8 个危险跨状态对象全部是权重 `0.7` 的
`confirmed_t10_strategy_replay`，其 `clue_task_mask=false`、
`fallback_scope_task_mask=false`。这具体证明缺失的监督不是更多
USE/KEEP 终态，而是：

1. 正向 KEEP 的原因：无 RCSD 证据、锚定歧义、普通业务保留或其他原因；
2. `RealityChangeClue` 是否成立；
3. 冲突属于 Segment 还是 Junction，以及 Junction 直接影响哪些 Segment。

上述信号不能由 KEEP 终态唯一推出。下一步不得继续把局部/邻接统计堆到
post-hoc safety head；应先形成可审计 Clue/scope 标签，随后让共享
Junction 状态、普通 Segment carrier 和 fallback directive 联合训练。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_use_safety_v45_strict_nested_cpu_20260728_v47_seed_20260748`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_use_safety_junction_context_v45_strict_nested_cpu_20260728_v48_seed_20260749`

### 现有 Case 的 Clue/scope 裁决准备包

在不增加 Case、不修改 T01–T12、也不从旧策略自动推导业务原因的前提下，
已生成 P05 内部 label-only 工件
`target_a_clue_scope_adjudication_20260728_02`。选取规则固定且可审计：

- P0：v47/v48 任一 safety head 实际接受的危险 USE，`20` 个；
- P1 carrier：v45 自动完整 plan 错误中除 P0 外的对象，`247` 个；
- P1 anchor：v45 因锚定 hard gate 回退的对象，`44` 个；
- P2 control：按 Case × preferred decision 稳定 hash 抽取最多 3 个正确
  对照，`52` 个。

最终队列为 `363` 个普通 Segment、覆盖 `22` 个既有 Case；另有 `5`
条 `user_manual_adjudication` 被写入只读 locked reference，不重复进入
队列。每条待裁决记录提供：

- 现有标签来源、权重、preferred/acceptable 完整 Road 方案；
- v45 选中方案、概率、锚定 fallback 状态；
- v47/v48 safety score、阈值、接受与危险状态；
- required SWSD semantic anchor，以及 candidate store 中共享该 anchor
  的全部普通 Segment ID。

所有 ID 只用于人工证据定位和直接关系 sidecar，不进入网络 embedding。
裁决输出字段为 `carrier_verdict / acceptable_road_plans /
preferred_road_plan / keep_reason / reality_change_clue /
fallback_scope / affected_segment_ids`。当前 363 条全部为
`UNKNOWN/PENDING`，`automatic_adjudication_count=0`、
`t06_t11_automatic_mapping_count=0`；草案值域未获用户确认前不得写回
label store 或启动联合 Clue/scope 训练。

为避免让每个对象填写无关字段，`_02` 将队列拆为互不混淆的 review
task：

- `CARRIER_PLAN`：363 条，复核完整 Road 清单、角色、access、Node、
  方向和拓扑；
- `KEEP_REASON_CLUE_SCOPE`：128 条，仅对现有 preferred KEEP 补充
  KEEP 原因、Clue、scope 与直接影响对象；
- `ANCHOR_RESULT`：44 条，复核 v45 因 anchor hard gate 回退的对象。

第一批固定为 P0 safety 危险 + P2 匹配正确对照，共 `72` 条
carrier plan，其中 `47` 条需要 KEEP/Clue/scope；剩余 `291` 条另存。
Phase 1 与 remaining 的 sample ID 互斥且并集精确等于完整 363 条队列。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_clue_scope_adjudication_20260728_02`

## 2026-07-28 T032-R1 精确作用域、Phase 1 回填与锚定硬门修正

本节覆盖并纠正 T032 中“正向 KEEP 不要求 required anchor 成功”的旧实现
解释。正式业务口径是：普通 Segment 的 required SWSD 语义路口锚定属于
进入 carrier 判断的网络硬门；任一 required anchor 未成功时，无论终态真值
是 KEEP 还是 USE，都必须输出 `ABSTAIN` 并按 Segment 原子 fallback。
正向 `KEEP_SWSD` 只在 required anchor 已成功且模型主动选择完整 SWSD Road
方案时计为自动业务决定。

### 标签作用域与人工回填

- `T10-Error/T10-Error-2` 只允许目录名对应的精确 Segment 作为标签；
  4 个目录目标不在冻结 T01 中，保持零标签，禁止以 Road 共享关系重映射；
- 精确 label store 为 51 Case、8,863 Segment，其中 target=`6,248`、
  context=`2,615`；普通 Segment strict OOF 范围=`4,226`；
- Phase 1 共 72 条人工裁决，KEEP=`47`、USE=`25`；人工权重统一提升到
  `1.0`，裁决只进入 label-only overlay，terminal feature=`0`；
- KEEP 原因为正向业务 KEEP=`23`、锚定未确定=`15`、无 RCSD 证据=`9`；
  Clue 均为 false；fallback 为 NONE=`32`、SEGMENT=`15`；
- 用户指定的 6 条已按确认值精确回填：3 条 KEEP、3 条 USE。
  其中 `T10:1885118/1901641_606670594` 为正向 KEEP，不再误标为
  `ABSTAIN -> Segment fallback`；其余未给出 Clue/scope 认知的 USE
  只监督 carrier，不补造 Clue 或 fallback 标签。

### 精确锚定与 ordinary OOF

锚定 truth-free 特征不因标签作用域变化而重复读取城市 GPKG；从既有冻结
feature store 按精确目标 Segment 的 required anchor 重算直接依赖，锚定
样本由 5,179 缩到 4,564，feature rows recomputed=`0`。

| run | 作用 | 关键结果 |
|---|---|---|
| v50 | 18.42M 锚定 shared/object OOF，精确作用域 | status accuracy=`0.873023`；gate accuracy=`0.911687`；failure recall=`0.913315`；candidate exact=`0.801659` |
| v51 | 124,994 参数独立 anchor gate | gate accuracy=`0.927065`；failure recall=`0.934119`；strict safety 仍有危险 anchor 自动接受=`14`，`NO_GO` |
| v52 | 旧 `fallback_required` 实现的 ordinary 对照 | 自动覆盖=`0.743966`；自动 plan exact=`0.904823`；危险 fallback 自动=`14`；因 KEEP 可绕过锚定而作废 |
| v55 | 修正 required-anchor 硬门后重训 | anchor fallback=`2,374/4,226`；自动覆盖=`0.438239`；自动 plan exact=`0.848780`；危险 fallback 自动=`8`，`NO_GO` |
| v56 | 固定 v55 carrier 的 USE safety | safety 后自动覆盖=`0.308093`；自动 plan exact=`0.907066`；accepted USE 仍有危险=`13`，`NO_GO` |
| v57 | 固定 v55 的 Segment fallback safety | 自动覆盖=`0.215334`；自动 plan exact=`0.875413`；危险 fallback 自动=`3`，`NO_GO` |

硬门修正同时覆盖训练与推理：锚定失败的样本不进入 carrier loss，teacher
forcing 选择 `ABSTAIN`，Road/carrier 分数不能反向改变锚定。修正前把
`conditioned_label_reachable` 当成 fallback 条件，导致 KEEP 方案总是可达
并绕过锚定；这是实现错误，不是可接受的覆盖率优化。

### 当前安全基线与下一步

将 v51 的 inner-calibrated anchor safety 接受结果真正作为 Segment 硬门，
再与 v56 USE safety 取交集，得到当前零危险诊断基线：

- 自动决定=`173/4,226`，覆盖=`0.040937`；
- 自动完整 Road 方案 exact=`0.976879`；
- 自动 KEEP=`128`、自动 USE=`45`；
- 已标注 fallback 范围内危险自动数=`0`。

仅使用 anchor safety、不叠加 USE safety 时为 `227/4,226=0.053715`，
完整 plan exact=`0.929515`、危险 fallback 自动=`0`。这证明 Segment
级阻断能把旧“整组只接受 9/5,179”的错误闭包改为局部安全 fallback，
但锚定 safety 的接受率仍远低于目标，不能发布。

当前缺失监督已具体收敛为两点：

1. 16 条 `fallback != NONE` 中只有 1 条 Junction fallback，无法可靠辨识
   Segment/Junction 升级边界；不能用默认 Junction 扩大回退范围；
2. 剩余危险对象本质是 anchor false positive：T05 标签已明确一端
   `ABSTAIN`，但独立 gate 在 held-out Case 预测 SUCCESS。继续调 ordinary
   carrier 或后置概率阈值不能修复。

下一轮应进入共享 anchor/ordinary gate 的联合训练：保留独立 anchor 对象
真值，同时让 Segment 级“任一 required anchor 未成功”的 fallback loss
反向约束共享 encoder；decoder 仍不能修改锚定、扩充候选或改变冻结骨架。
T032-R1 状态为“人工回填、硬门修正和单 seed strict OOF 已完成，发布门
NO_GO”；T033/T034 AdvanceRight、完整 decoder joint fine-tuning 和
`3 seeds x 5 folds` 尚未启动。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_label_store_20260728_08_exact_error_scope`
- `outputs/_work/p05_neural_road_generation/target_a_plan_preflight_20260728_13_phase1_manual_overlay_exact_six`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_joint_store_20260728_19_exact_error_scope_replay`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_exact_error_scope_resolved_gate_soft_cardinality_graph_oof_cuda_20260728_v50_seed_20260751`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_independent_exact_error_scope_resolved_gate_strict_nested_cpu_20260728_v51_seed_20260752`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_phase1_manual_exact_scope_exact_anchor_hard_gate_plan_member_arm_hierarchical_joint_only_strict_nested_cuda_20260728_v55_seed_20260753`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_use_safety_v55_hard_gate_exact_scope_strict_nested_cuda_20260728_v56_seed_20260756`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_fallback_safety_v55_hard_gate_exact_scope_strict_nested_cuda_20260728_v57_seed_20260757`

## 2026-07-29 T033–T035 AdvanceRight 联合依赖与结构化 decoder 诊断

本轮按正式业务依赖补齐了相邻普通 Segment 最终 access Road 到
AdvanceRight 的条件化链路。AdvanceRight 不能自行猜测或反向修改两侧普通
Segment；模型先分别输出两侧 `SWSD / RCSD / UNRESOLVED` 及 RCSD 侧唯一
access Road，再锁定这些结果，条件化选择完整提右 Road 组合、几何/挂接方案
与安全状态。SWSD 侧继续使用冻结 T01 的连接 Road，不补造 RCSD access。
训练期允许 teacher forcing，严格 OOF 推理只使用折外普通 Segment 结果；
label mask、真实 access、终态几何和 T06 正式结果均不进入推理特征。

### access、完整 Road 与几何监督覆盖

v95 对全部 `474` 个 AdvanceRight 建立 60D 条件化特征：

- OOF 两侧 source 可判定 `434` 个，两侧 exact access Road 可判定 `236`
  个；
- teacher 两侧 source 可判定 `392` 个，两侧 exact access Road 可判定
  `52` 个；
- `feature_uses_truth=false`、terminal input=`0`、raw ID embedding=`0`，
  feature 在读取标签前冻结并记录 hash。

v100 从现有 T06 终态重建几何弱标签：`COMPLETE=247`、
`UNREACHABLE=74`、`FALLBACK_NOT_APPLICABLE=153`，共有 `331` 个候选
variant、`249` 个 complete variant；但与现有正式 T06 action 逐字段
匹配数为 `0`。因此这些标签只允许作为“可达几何选择”弱监督，不能宣称已
继承正式打断/衔接动作真值。v101 teacher 条件下有 `25,398` 个几何候选；
v102r1 严格 OOF 条件下有 `6,436` 个候选，仅 `46` 个对象的 teacher
variant 可达。不可达 teacher variant 保持 `UNREACHABLE`，没有被最近
Road 或几何近似静默改写。两次候选构建均为 metric CRS、
`crs_consistent=true`、`silent_fix=false`、terminal input=`0`。

### 三组严格单 seed × 5 Case folds 训练

| run | 范围 | 参数量 | 主要折外结果 | 自动发布结果 |
|---|---|---:|---|---|
| v97 | 锁定 ordinary access 后的完整提右 Road 组合 | 865,393 | raw plan exact=`0.675105`；candidate acceptable exact=`0.732984` | 自动 `33/474`，危险 `30`，覆盖 `0.069620`，`NO_GO` |
| v103 | v97 + 几何/挂接联合头 | 1,220,339（其中几何头 354,946） | complete plan+geometry exact=`0.556962`；端到端 complete exact=`0.056962` | 自动 `33/474`，危险 `30`，`NO_GO` |
| v104r1 | 两侧普通 source/access 与提右 Road 端到端联合训练，阶段间 stop-gradient | 1,180,885 | side source exact=`0.814346`；RCSD side access exact=`0.779070`（86 个有标签）；两侧完整 ordinary exact=`0.052743`；提右 raw plan exact=`0.481013`；端到端 exact=`0.027426` | 自动 `0/474`、危险 `0`、正向 KEEP=`0`，`NO_GO` |

v104r1 的安全阈值多数高于 1，零危险来自全量回退，不是业务能力达标。
训练后修正了 teacher 评分应使用真实两侧 source 的评价合同；只读重算的
teacher raw plan upper bound 为 `0.647679`。既有 ignored v104r1
`summary.json` 中 teacher=`0.481013` 仍是修正前字段，不作为正式指标；
OOF=`0.481013`、端到端与发布结论均不受该评分修正影响。

这些结果表明，P13 的 candidate-local 缺陷已经被明确修正：网络确实能观察
相邻普通 Segment 的最终 source/access。然而瓶颈转移为完整 ordinary
access 的跨 Case 泛化和提右完整 Road/几何标签可辨识性。v100 中正式 T06
action 精确匹配为零，是当前明确缺失的监督信号；这不能靠继续调阈值或增加
局部几何特征补造。

### v105r1 结构化 decoder 与有限 fallback 审计

v105r1 读取冻结骨架全部 `8,863` 个 Segment（ordinary=`8,389`、
AdvanceRight=`474`），只在模型提供的完整候选方案中组合选择：

- ordinary 模型判为 release-ready `858` 个，完整候选适配成功 `855`
  个，另 `3` 个因候选适配不一致回退；
- 形成 `855` 个 Case 内所有权冲突连通组，最大组大小为 `1`；当前自动
  候选之间没有需要全局择优消解的共享 Road 冲突；
- ordinary 自动 `855`、AdvanceRight 自动 `0`、Segment fallback
  `8,008`；正向 `KEEP_SWSD=826`；
- 强标签可评价的自动对象 `577` 个，其中 exact=`493`、危险=`84`；
  另有 `278` 个自动对象没有足够强标签评价；
- Case 内重复 Road 所有权=`0`、skeleton mutation=`0`、
  `silent_fix=false`。

因此 decoder 的有限作用域、唯一所有权和不改骨架合同通过，但正式发布仍是
`NO_GO`：它不能修正模型已经给错的完整 Road 方案。v105r1 未执行最终几何、
Node/方向写出和完整 RoadGraph materialization，所以
`fallback 后最终 RoadGraph exact` 仍为空，不能据此关闭 T043–T046，也
不能声称 Target A 已生成完整业务正确 RoadGraph。

### 621989990 人工锚定裁决

对 `T10-Error:501386978_504378551` 的 SWSD 语义路口 `621989990`，用户
目视确认其业务真值为“可以正确锚定”。该裁决按人工真值权重 `1.0` 进入：

- anchor status 监督为 `SUCCESS`；
- 由于尚未指定唯一 RCSD Node/Road 对象，不补造具体 candidate 选择标签；
- 当前旧 T03 策略失败时，推理/发布允许
  `ABSTAIN -> 该 Segment fallback SWSD`，`RealityChangeClue=false`；
- 该 fallback 不得反向把人工“可锚定”改写为失败，也不得统计为正向
  `KEEP_SWSD`。

### 当前结论

T033、T034 和相邻 ordinary-access→AdvanceRight 范围内的 T035 已完成
实现及严格单 seed 诊断，但三组均为 **NO_GO**。单 seed 已分别暴露
`30` 个危险自动项或零自动覆盖，因此不扩另外两个 seed；T036 保持未完成。
T012 internal connector tree、T014 完整 hard mask/materializer、
T032-R2 全量共享 anchor/ordinary gate、最终 RoadGraph 写出和完整策略
paired comparison仍未完成。本轮结论只否定当前联合实现，不否定 Target A
的业务目标。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_advance_right_access_set_conditioning_20260729_v95`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_teacher_student_rcsd_access_strict_nested_oof_cuda_20260729_v97_seed_20260797`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_teacher_access_geometry_labels_20260729_v100`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_teacher_geometry_candidates_20260729_v101`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_oof_geometry_candidates_20260729_v102r1`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_geometry_teacher_student_strict_nested_oof_cuda_20260729_v103_seed_20260803`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_access_strict_nested_oof_cuda_20260729_v104r1_seed_20260804`
- `outputs/_work/p05_neural_road_generation/target_a_structured_decoder_audit_20260729_v105r1`

## 2026-07-29 621989990 物化、required-anchor scope 修正与 v108/v109

用户确认 `T10-Error:501386978_504378551` 的 SWSD 语义路口
`621989990` 在业务上可以正确锚定后，专项测试虽已覆盖裁决代码，但旧 v19
精确锚定 store 中没有该样本。进一步只读审计确认：

- 该 Segment 确实存在于冻结 T01，`pair_nodes=501386978,504378551`，
  `junc_nodes=506386224,602671263,621989990`；
- 缺失原因不是业务作用域排除，而是 v19 从更早的冻结 feature store 做
  subset，当时没有生成当前精确目标 Segment 的全部 required anchors；
- 因此不能只向 label JSONL 人工插入 `621989990`，必须按当前 51 Case
  inventory 和精确 Segment 作用域重建 truth-free anchor store。

v106 从现有 Case 完整重建，v107 再执行 T03/T04 正式 replay。两者的
manifest、feature/label SHA256 和 leakage audit 均通过。v107 与 v19
逐样本比较：

- 旧 `4,564`、新 `5,148`，共同样本 `4,564`；
- 新增 required-anchor `584`，删除 `0`；新增来自 T10=`473`、
  T10-Error=`82`、T10-Error-2=`29`，没有新增 Case；
- 排除直接依赖 ID 集合后，4,564 个共同样本的 truth-free 核心特征
  mismatch=`0`；
- `2,145` 个共同样本的直接依赖集合得到补全。这是由当前目标 Segment
  全部 required anchors 派生的 encoder 上下文变化，不是标签泄漏。

`621989990` 在 v107 中的最终监督为：

- `SUCCESS`、status supervised=true；
- resolved gate=`1`、gate supervised=true；
- sample weight=`1.0`；
- exact candidate 未指定，因此 candidate supervised=false、
  acceptable indices 为空、preferred index=`-1`；
- release 仍为 `ABSTAIN -> Segment fallback`、Clue=false，且不计为
  正向 `KEEP_SWSD`。

这次重建同时暴露：v50–v105 使用的 v19 锚定 store 漏掉 584 个既有
required-anchor 样本，且大量 Segment 内直接依赖不完整。因此这些 run
继续保留为当时实现的诊断事实，但不能再作为“当前完整监督作用域”的最终
性能结论。

### 相同配置/seed 的 paired strict-nested OOF

v108 完全复用 v50 的 18,415,507 参数配置、seed=`20260751`、
batch size=`128` 和 5 Case folds，仅把输入换为 v107：

| 指标 | v50 旧不完整 store | v108 完整 required scope |
|---|---:|---:|
| example / supervised | 4,564 / 4,552 | 5,148 / 4,313 |
| status accuracy | 0.873023 | 0.896824 |
| supported macro F1 | 0.751588 | 0.685779 |
| anchor gate accuracy | 0.911687 | 0.927892 |
| failure recall | 0.913315 | 0.813804 |
| pass recall | 0.910932 | 0.947154 |
| candidate acceptable exact | 0.801659 | 0.810729 |
| wall time | 481.34s | 708.76s |

v109 完全复用 v51 的 124,994 参数 independent gate 配置与
seed=`20260752`：

| 指标 | v51 旧不完整 store | v109 完整 required scope |
|---|---:|---:|
| status accuracy | 0.869288 | 0.924646 |
| supported macro F1 | 0.722582 | 0.787393 |
| anchor gate accuracy | 0.927065 | 0.959889 |
| failure recall | 0.934119 | 0.958266 |
| accepted | 469 | 849 |
| safe / unsafe-to-release auto | 455 / 14 | 817 / 32 |
| accepted coverage | 0.102761 | 0.164918 |
| proven-safe recall | 0.204678 | 0.303717 |

总体 accuracy、candidate exact 和覆盖上升，但零危险门显著失败：
Fold 0–4 的 unsafe-to-release auto 分别为 `5/3/3/20/1`；Fold 4 只接受
`2` 个，其中 `1` 个不可安全发布。32 个 unsafe-to-release 必须再拆分：

- `17` 个有监督错误：13 个权重 0.7 的 T10 具体对象错误、1 个权重
  1.0 的 T11 `no_valid_relation` 错误自动 SUCCESS、2 个权重 1.0 的
  T03 具体对象错误、1 个权重 1.0 的 T03_Error 错误自动 SUCCESS；
- `15` 个不可验证自动项。其中 14 个为 T10 `relation_record_absent`，其
  `status_supervised=false`、`gate_supervised=false`、
  `candidate_supervised=false`；另 1 个
  `T10:1885118/610667772` 的 status=`SUCCESS` 有监督，但 exact
  candidate 被 mask，模型输出的具体 Road 对象不能验证。15 个对象都不能
  补造为错误，也没有对象真值进入 loss；但自动输出具体 SUCCESS 方案不能
  验收，因此仍必须阻断发布。

这一区分严格继承“relation_record_absent 只表示锚定真值未知”的正式
口径：不得把 14 个未知对象补造为失败，也不得把 15 个不可验证对象统计成
模型已证实错误。
新增完整依赖扩大了可学习范围，同时扩大了错误或不可验证的自信接受，不能
解释为安全性改善。

`621989990` 位于 held-out Fold 4：raw status 预测为 `NO_EVIDENCE`，
SUCCESS probability=`0.276224`，independent gate pass
probability=`0.142206`，低于 inner-only safety threshold=`0.957704`，
最终 `ABSTAIN`、未自动接受、unsafe auto=false。即当前发布行为符合用户
允许的安全 fallback，但模型没有学会该人工 SUCCESS 真值。

v110 在不改变模型、threshold 或任何预测的前提下正式增加
`safety_supervised_error_auto / safety_unverifiable_auto` 字段；
v109/v110 的 OOF 与 inner-calibration JSONL SHA256 逐字节一致。正式
v110 计数为 safe=`817`、supervised error=`17`、unverifiable=`15`，
三者之和精确等于 accepted=`849`。

T030d 继续为 **NO_GO**。因为完整锚定 store 的单 seed strict OOF 已有
17 个有监督错误自动锚定和 15 个不可验证自动项，本轮不继续 ordinary、
AdvanceRight 或完整 decoder 下游重训；否则只会把未通过的锚定门传播到
Road 方案。下一步技术问题是 required-anchor 可判定性和具体对象监督，
不是继续校准后置阈值。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_anchor_joint_store_20260729_v106_user_anchor_621`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_joint_store_20260729_v107_user_anchor_621_replay`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_strict_nested_complete_required_scope_resolved_gate_soft_cardinality_graph_oof_cuda_20260729_v108_seed_20260751`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_independent_complete_required_scope_resolved_gate_strict_nested_cpu_20260729_v109_seed_20260752`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_independent_complete_required_scope_resolved_gate_strict_nested_safety_split_cpu_20260729_v110_seed_20260752`

## 2026-07-29 T032-R2 完整裁决继承与共享 anchor/ordinary gate

### v111：先修正完整 store 的裁决继承

T032-R2 预检发现：v107 虽补齐 required-anchor scope 并包含用户确认可锚定的
`621989990`，但它从较早的原始 store 重放，导致此前已确认的
`T10:609214532/609617028`“已证明无 RCSD 证据”又退回未知；与此同时
普通 Segment 标签仍保留该裁决，形成 anchor/Segment 层不一致。该问题
不是新的业务歧义，不重新请求人工裁决。

v111 在不改变 truth-free inference feature 的前提下，重新叠加全部既有
人工裁决和三态监督政策：

- anchor=`5,148`，feature store 与 v107 逐字节一致；
- `621989990` 为 `SUCCESS`、gate=`1`、weight=`1.0`，exact candidate
  继续 mask；
- `609617028` 为有监督 `NO_EVIDENCE` 正向终态；
- 24 条 T11 `no_valid_relation` 均为有监督失败；
- `relation_record_absent` 仍为未知并 mask，不补造成功或失败；
- ordinary plan 共 8,863 条，其中 gate resolved=`4,039`、
  failure=`123`、unknown=`4,227`、not applicable=`474`。

### v112/v113：共享 gate encoder 与独立对象选择

联合模型保持锚定对象唯一选择独立：共享的 200,963 参数 gate encoder
同时接受逐 anchor resolved/unresolved loss 与普通 Segment fallback loss；
Segment margin 是全部 required-anchor margin 的保守 soft-min 再减去非负
context risk，后层不能提高或绕过任一锚定门。5 Case folds 的 epoch 选择和
发布阈值均只使用对应 outer fold 的 inner validation，outer label 只评价。

v112 仅用联合 gate probability 做发布分数，暴露出它丢失独立对象模型
状态/对象置信度的问题。v113 不改变训练、预测或 fold，只把发布分数修正为
联合 gate 与独立对象模型状态/对象置信度的保守最小值。v112/v113 的
anchor/Segment raw OOF SHA256 分别逐字节一致。

raw gate 指标为：

| 层级 | accuracy | failure recall | pass recall | FP | FN |
|---|---:|---:|---:|---:|---:|
| anchor | 0.958739 | 0.932584 | 0.963154 | 42 | 136 |
| ordinary Segment | 0.864631 | 0.631148 | 0.872111 | 45 | 487 |

严格发布结果：

| 方案 | anchor accepted / safe / supervised error / unverifiable | Segment accepted / safe / supervised error / unverifiable |
|---|---:|---:|
| v110 independent baseline | 849 / 817 / 17 / 15 | 不适用 |
| v112 joint gate only | 947 / 721 / 123 / 103 | 803 / 694 / 5 / 104 |
| v113 joint+object confidence | 1,072 / 1,019 / 25 / 28 | 835 / 808 / 5 / 22 |
| v110∩v113 | 599 / 575 / 15 / 9 | 401 / 389 / 4 / 8 |

v113 相比 v112 明显恢复安全性和有效覆盖，但仍未达到零危险；与 v110
取交集后危险项仍非零，且覆盖显著低于 v110，不能证明共享训练为现有安全
基线增加了可发布价值。v113 的 25 个 anchor 监督错误中，T10=`23`、
T03=`1`、T03_Error=`1`；5 个 Segment 监督错误全部来自 T10。剩余问题
仍是跨 Case 可判定性与完整对象监督，不是 `621989990` 单条裁决造成。

`621989990` 在 v113 held-out Fold 4 中仍预测 `NO_EVIDENCE`，联合 gate
probability=`0.313208`、严格阈值=`0.982433`，最终安全拒绝为
`ABSTAIN -> Segment fallback SWSD`，clue=false；它不计正向
`KEEP_SWSD`。已确认无证据的 `609617028` 虽正确预测 `NO_EVIDENCE`，
但保守分数=`0.527441` 低于阈值=`0.925493`，同样 fallback，说明当前
安全门还牺牲了正向无证据召回。

T032-R2 状态更新为“共享训练、strict inner-only calibration、完整
required-anchor scope 单 seed OOF 已完成，发布门 **NO_GO**”。v112/v113
及交集均不向 ordinary carrier、AdvanceRight 或最终 RoadGraph 下游释放；
T030d 仍未完成，T036 不扩另外两个 seed。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_anchor_plan_supervision_20260729_v111_complete_required_scope_user_adjudications`
- `outputs/_work/p05_neural_road_generation/target_a_joint_anchor_segment_gate_complete_required_scope_strict_nested_safety_calibrated_cuda_20260729_v112_seed_20260764`
- `outputs/_work/p05_neural_road_generation/target_a_joint_anchor_segment_gate_complete_required_scope_combined_confidence_strict_nested_cuda_20260729_v113_seed_20260764`

## 2026-07-29 T012 RCSD 内部连接树与受影响模型重训

### 业务实现与真实数据候选

旧 `CORRIDOR_COMPONENT` 把主路径之外的整个连通分量统一标为
`INTERNAL_CONNECTOR`，51 Case 的 14,415 个候选中只有 309 个满足树形
条件，8,040 个含环或非单树，6,066 个存在不挂接 MAIN 的外部叶。该角色
划分不再进入新候选库。

v114 改为两个互不替代的候选来源：

- `COMPONENT_ALL_MAIN` 保留整个 RCSD 连通分量作为 MAIN 候选，避免因角色
  证明不足丢失完整 Road 清单；
- `INTERNAL_CONNECTOR_TREE` 只保留物理并行 Road 聚合后仍为单树、全部叶
  节点都位于当前 MAIN Road 节点集合、无外部叶的候选；原始并行 Road ID
  仍全部保留并进入 `owned_road_ids`。

v114 覆盖 51 Case、8,863 Segment group、69,085 个候选，其中
`INTERNAL_CONNECTOR_TREE=6,651`、`COMPONENT_ALL_MAIN=13,373`，
旧 `CORRIDOR_COMPONENT=0`。v118 逐候选审计确认 6,651/6,651 均满足：
plan/proof hard-valid、叶集合等于 MAIN 挂接集合、外部叶为零、角色 Road
集合一致、连接 Road 全部计入 owner、物理树边数有效。候选特征仍为 64D，
Road member 为 24D、arm 为 13D；输入 lineage 与旧 v07 相同，
CRS=`EPSG:3857`（51/51），`silent_fix=false`、骨架 mutation=0。
运行 wall=`119.455s`、Case p95=`7.787s`、max=`29.793s`。

完整 Road 清单预检由 `4,409/5,829=0.756390` 增至
`4,410/5,829=0.756562`，无旧可达样本丢失；旧候选中 9 个由
`CORRIDOR_COMPONENT` 命中的完整 Road 清单全部仍可达，但经正式角色条件
重算后均由全 MAIN 的 `ANCHOR_PATH / MULTIPATH_UNION /
COMPONENT_ALL_MAIN` 表达，不能继续把旧 generator 名称解释成内部连接
Road 真值。

当前 4,410 个可达训练 Segment 中，只有 1 个完整 Road 标签必须通过新的
内部连接树候选命中：
`T10-Error-2:986209_996008_1 / 986209_996008_1`。其完整 Road 清单是
4 条 RCSD Road；候选角色为 2 条 MAIN + 2 条 INTERNAL_CONNECTOR，
连接子图是 2-edge path，两端都挂接 MAIN。现有 T06 标签监督完整 Road
清单，MAIN/INTERNAL_CONNECTOR 的拆分由用户已确认的树形业务条件证明，
不是独立人工逐 Road 角色标签。除该对象外，现有 51 Case 没有第二条可达
正例能监督“何时必须把内部连接树加入完整 Road 清单”；这是具体监督稀疏
事实，不泛化为要求新增 Case。

### v119/v120 重训结论

候选特征语义变化后，使用同一 fold、seed 和 strict-inner 校准重训受影响
模型：

| 运行 | 参数 | 关键结果 | 结论 |
|---|---:|---|---|
| v119 shared anchor/ordinary gate | 200,963 | anchor accepted/safe/supervised-error/unverifiable=`1070/1017/25/28`；Segment=`827/801/5/21` | `NO_GO` |
| v120 ordinary complete-plan head | 19,916,527 | reachable plan exact=`0.898274`；自动覆盖=`0.225455`；自动可评价 exact=`0.850794`；unsafe scope bypass=`8` | `NO_GO` |

v119 相比 v113 没有消除危险项：anchor 监督错误仍为 25，Segment 监督错误
仍为 5。v120 对唯一内部连接正例在 held-out Fold 4 仍只选择两条 MAIN
Road，漏掉两条内部连接 Road；但 v119 对该 Segment 的 required anchors
未全部放行，最终 `release_accepted=false`，不会把错误 plan 传给
AdvanceRight 或 RoadGraph。

`621989990` 继续按用户目视审计作为“应成功锚定”的权重 1.0 正标签，
不能因当前 T03 策略或模型失败而改成 `NO_EVIDENCE`。其 exact RCSD 对象
仍未由人工指定，因此对象 head 保持 mask；v108/v119 仍以
`NO_EVIDENCE` 为基础预测，但严格发布门拒绝自动结果并执行 Segment
fallback。这是安全 fallback，不是正向 KEEP，也不算锚定能力成功。

T012 因此完成；候选表达、拓扑证明和所有权门已通过，但现有模型发布门仍
为 **NO_GO**。本轮不修改 T01–T12，不向 downstream 或生产释放。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_plan_candidates_20260729_v114_internal_connector_tree`
- `outputs/_work/p05_neural_road_generation/target_a_plan_preflight_20260729_v115_internal_connector_tree`
- `outputs/_work/p05_neural_road_generation/target_a_plan_preflight_20260729_v116_internal_connector_tree_phase1_manual`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_plan_supervision_20260729_v117_internal_connector_tree_user_adjudications`
- `outputs/_work/p05_neural_road_generation/target_a_internal_connector_audit_20260729_v118`
- `outputs/_work/p05_neural_road_generation/target_a_joint_anchor_segment_gate_internal_connector_tree_combined_confidence_strict_nested_cuda_20260729_v119_seed_20260764`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_oof_internal_connector_tree_complete_scope_hard_gate_plan_member_arm_hierarchical_joint_only_strict_nested_cuda_20260729_v120_seed_20260753`

## 2026-07-29 T014 确定性 materializer 与局部阻断审计

> 历史更正：本节 v122/v123 的执行器能力与 `MultiLineString` 局部阻断
> 事实保留，但“普通 Segment 必须选择唯一 access Road”及由此得到的
> 1,243+431 个 blocker 解释已被后续业务确认和 v132 推翻。正式当前口径
> 见本节末“v132 完整 access binding 修正”。

### 执行边界

新增的 materializer 只执行 `DecisionLedger` 已明确给出的 source Road、
Road 角色/所有权、方向、source slice、break position、reverse、join mode、
Node recipe、access reference 和 attachment position。它可以复制 source
Node、按指定 Road 位置生成 Node、执行非重叠 split/clip、reverse、
`COINCIDENT_ONLY` 或显式 `STRAIGHT_CONNECTOR` splice，并生成稳定 Road/Node
ID；不得自行选最近 Road、改变 Segment/Junction 骨架、扩大 fallback、
补造 access 或连接不连续几何。

hard validation 覆盖：

- 冻结 Segment 集合完全一致；
- CRS 一致且为米制投影；
- source Road/Node、方向和端点引用存在；
- 同一 source Road 的最终 owned piece 不重叠；
- 普通 Segment access 输出完整 Road/Node 集合，可包含自己的 owned Road
  和无 owner Junction connectivity Road，不要求唯一 Road；
- AdvanceRight 只引用相邻普通 Segment access，不取得其所有权，且自身必须
  有独立 `ADVANCE_RIGHT` Road；
- AdvanceRight 的 RCSD 侧 attachment 必须唯一指定 access 集合内父 Road、
  已执行的打断端点和共享最终 Node；SWSD fallback 侧必须复用冻结 access
  Node/JunctionUnit；
- shared no-owner `JUNCTION_CONNECTIVITY` 仅允许相同指令合并；
- 正向 `KEEP_SWSD` 与 `ABSTAIN -> fallback SWSD` 分开统计；
- `skeleton_mutation=0`、`silent_fix=false`、`content_repair=false`。

### 51 Case T01 fallback 审计

v122 首次跑完 51 Case 后发现，3 个大 Case 因读到
`MultiLineString` Road 被整 Case 拒绝。这与已确认的局部阻断边界不符。
检查确认这些 Road 都由两个不连续 part 组成，part 最小端点间隙为
`6.066m–212.605m`，不能由确定性层自动拼接。v123 只重跑这 3 个 Case，
把不支持的 Road 精确阻断到 owner Segment，其余 Segment 继续物化；未改写
几何或 access。

用 v123 替换 v122 的这 3 个 Case 后，合并结果为：

| 指标 | 结果 |
|---|---:|
| Case | 51 |
| 冻结 Segment | 8,863 |
| 严格物化 Segment | 7,144 |
| 局部阻断 Segment | 1,719 |
| 严格物化 Road | 8,546 |
| 完整冻结骨架物化 Case | 7/51 |
| 依赖完整子图可物化 Case | 51/51 |
| materialization hard failure | 0 |
| CRS metric/consistent | 51/51 |
| skeleton mutation / silent fix / content repair | 0 / 0 / 0 |

v122/v123 当时记录的 1,719 个局部阻断如下；前两行是已失效的执行器
解释，不是正式业务 blocker：

| 原因 | Segment 数 | 解释 |
|---|---:|---|
| `STANDARD_LEDGER_UNRESOLVED` | 1,243 | **已失效**：错误要求完整 access 集合只能有一条 Road |
| `ADVANCE_RIGHT_LEDGER_UNRESOLVED` | 431 | **已失效**：由上一错误假设连带产生，且未覆盖少量内部 attachment Node |
| `FROZEN_ACCESS_INVALID` | 38 | T01 已明确该 frozen access 关系 invalid |
| `FROZEN_INDEPENDENT_ROAD_INVALID` | 2 | T01 已明确没有合法独立 SWSD Road 方案 |
| `SOURCE_ROAD_GEOMETRY_UNSUPPORTED` | 5 | 5 条 owned T01 Road 是不连续 `MultiLineString`，确定性层拒绝补线；源图另有 1 条同类 Road 未进入冻结 Segment Road 清单 |

当时据此推导的“缺少唯一 access Road 监督”结论已经撤销。正式问题不是
在 2–3 条 Road 中选一条，而是输出完整 Road/Node access 集合；旧数字仅
保留为本体错误如何造成大范围假断联的回归证据。

v122 wall=`676.100s`；只重跑 3 个大 Case 的 v123 wall=`477.606s`。
materializer 单元计算不是主要耗时，瓶颈是审计器逐 Case 重复 hash 和打开
T01 GPKG。该性能不满足正式城市推理设计；正式实现必须城市一次加载、
按输入 hash 复用只读 Road/Node 索引，在内存传递依赖子图和紧凑 ledger，
最终只写一次 RoadGraph。

本段测试与性能数字为 v122/v123 历史快照，已由下文 v132 与 `490 passed`
正式替代。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_materializer_audit_20260729_v122`
- `outputs/_work/p05_neural_road_generation/target_a_materializer_audit_20260729_v123_source_localized`

### v132 完整 access binding 修正（正式替代 v122/v123 blocker 解释）

用户确认普通 Segment access 是完整 Road/Node 集合，只有 AdvanceRight
连接 RCSD carrier 时才从该集合选择唯一父 Road 片段和挂接位置；SWSD
fallback 侧允许保持冻结 Node/JunctionUnit 连接。真实 T01 同时表明：
AdvanceRight 的 `source_segment_access/target_segment_access` 少量指向
普通 Segment 内部 Node，而非 `pair_node/junc_node`。因此 materializer
正式采用：

- `ENDPOINT`：T01 `pair_node` access；
- `THROUGH`：T01 `junc_node` access；
- `ADVANCE_RIGHT_ATTACHMENT`：T01 明确登记的普通 Segment 内部挂接
  access；
- 每个 binding 输出全部 Road instruction 与 Node recipe，不读取冻结
  skeleton 中可能混入 T06 终态生成 ID 的 `access_node_ids`；
- access 集合缺 Road、漏掉同点 owned Road、方向角色不符或改变冻结
  Segment 关系时 hard fail；
- AdvanceRight 的 RCSD `ROAD_POSITION` 和 SWSD
  `FROZEN_ACCESS_NODE` 分开执行，后层不能代选父 Road。

v130 首轮全量已把旧 blocker 从 1,719 降为 47；检查最后两条
`ADVANCE_RIGHT_LEDGER_UNRESOLVED` 后确认，它们分别是
`T10:1885118 / 30956645_606058033@508058458` 与
`T10:605415675 / 857656_894718@89318168` 的合法内部挂接 Node。加入
`ADVANCE_RIGHT_ATTACHMENT` 后，v131 两 Case 烟测不再有 AdvanceRight
blocker，v132 正式全量为：

| 指标 | v132 |
|---|---:|
| Case | 51 |
| 冻结 Segment | 8,863 |
| 严格物化 Segment | 8,818 |
| 局部阻断 Segment | 45 |
| 严格物化 Road | 14,193 |
| 完整冻结骨架物化 Case | 45/51 |
| 依赖完整子图可物化 Case | 51/51 |
| `STANDARD_LEDGER_UNRESOLVED` | 0 |
| `ADVANCE_RIGHT_LEDGER_UNRESOLVED` | 0 |
| materialization hard failure | 0 |
| CRS metric/consistent | 51/51 |
| skeleton mutation / silent fix / content repair | 0 / 0 / 0 |
| wall | 185.371s |

45 个局部 blocker 只剩：

| 原因 | Segment 数 |
|---|---:|
| `FROZEN_ACCESS_INVALID` | 38 |
| `FROZEN_INDEPENDENT_ROAD_INVALID` | 2 |
| `SOURCE_ROAD_GEOMETRY_UNSUPPORTED` | 5 |

因此，旧 1,243 个普通 Segment 和 431 个 AdvanceRight 不是“缺少唯一
access 标签”，而是执行器错误地把完整集合压成单 Road。它们必须从后续
数据不足、断联和人工补标队列中删除。5 个不连续 `MultiLineString` 仍只
阻断 owner Segment，不自动补线；38+2 个 frozen invalid 继续按 T01
显式安全回退。

性能上，owner Road 预索引与 canonical CRS cache 不改变校验内容，使最大
Case `T10:1885118` 从 v123 约 `257.78s` 降为 v129 的 `47.26s`；51 Case
v132 为 `185.37s`。该工具仍是逐 Case 审计器，正式城市推理必须按已确认
合同一次加载只读 Road/Node 索引、按业务依赖子图 forward、冲突连通组
decode，并最终一次写出。

### v126/v127 完整 ordinary access 集合监督与首轮训练

重新解释现有 T06 终态标签时，以每条最终 formal incident Road 为必需业务
元素，以 source Road/位置对该 final Road 的映射为候选；只有多个 source
解释覆盖同一 final Road 时才是多解。exact-cover 适配结果：

| 指标 | v126 |
|---|---:|
| access 对象 | 2,904 |
| 可解析完整集合 | 2,000 |
| 原可训练对象 / 保留对象 | 1,665 / 1,665 |
| 多 Road 必需集合 | 1,972 |
| 真正多解集合 | 1 |
| 必需 final Road | 5,294 |

v126 只写出约 3.8MB label-only 集合文件，并复用原 267MB immutable
truth-free feature 的既有 hash，不复制大特征。旧 v93 将同一集合的多个
必需 Road 当作“多选一可接受候选”，所以其 `raw exact≈0.778` 仅是单 Road
命中率，不是完整 access 正确率。

v127 使用同一 204D teacher/OOF 条件化特征、253,121 参数 set encoder，
改为逐候选 sigmoid、exact-cover 多解 loss、正负成员 loss 与集合基数
辅助约束。严格单 seed × 5-fold Case-OOF：

| 指标 | v127 |
|---|---:|
| 可训练 example | 882 |
| OOF 完整集合 exact | 0.339002 |
| mean set F1 | 0.639804 |
| teacher 完整集合 exact | 0.586168 |
| upstream release eligible | 25 |
| 自动接受 | 23 |
| 危险自动接受 | 4 |
| 最差 Case exact | 0 |

错误按目标集合基数高度集中：基数 1 exact=`0.70`，基数 2
exact=`0.36`，基数 3/5/6/7/9/14 均为 0，基数 4 exact=`0.09`；
模型明显低估集合基数。v127 结论为 **NO_GO**。安全门同时修正为：inner
slice 没有 release-eligible 样本或没有观察到 unsafe 时，不得把阈值设为
0 自动放行，而应整 fold abstain；该修正用于后续运行，不回写 v127
历史预测。

### v134/v136/v137：最终 access 父 Road、显式集合大小与提右挂接

T06 `advance_right_attachment_audit` 的动作不能直接全部作为模型标签。
725 条 `normalize_swsd_singleton_mainnode` 只是确定性写出动作；真正涉及
Road/位置选择的 756 条动作，经最终 Road、最终 Node、相邻 Segment relation
和正式 connectivity 范围联合核对后得到：

| 监督类别 | 数量 | 用法 |
|---|---:|---|
| 唯一最终 access Road 片段强监督 | 619 | 继承 T10 Case 权重 0.7 |
| T06 动作明确但最终 access Road 不可唯一回溯 | 76 | 仅作 0.3 弱辅助 |
| 依赖未解析/相邻最终非 RCSD/carrier 缺失 | 61 | 完全屏蔽 |
| 确定性 Node 规范化 | 725 | 不进入模型 target |

强监督记录同时保留“打断前父 Road、打断位置、打断后真正被相邻普通
Segment 引用的最终 access Road 片段”。模型不预测生成 ID；T06 最终 Node
只作 label-only 几何反投，推理特征 `terminal_input_count=0`。619 条强监督
的最终 access 端点最大回投误差为 `1.862645149e-09m`，无 silent fix。

普通 access v135/v136 使用 204D 既有推理期证据、Set Transformer、显式
1..16 集合大小头和严格 top-k member decoder，参数量 446,737：

| 指标 | v127 | v135 teacher-only | v136 teacher+OOF 双视图 |
|---|---:|---:|---:|
| OOF 完整集合 exact | 0.339002 | 0.337868 | **0.433107** |
| mean set F1 | 0.639804 | 0.614726 | **0.742805** |
| teacher 完整集合 exact | 0.586168 | 0.714286 | 0.654195 |
| 集合大小 exact | 未显式输出 | 0.573696 | **0.713152** |
| release eligible | 25 | 25 | 25 |
| 自动接受 / 危险 | 23 / 4 | 1 / 1 | 1 / 1 |
| 最差 Case exact | 0 | 0.111111 | 0 |

v136 证明显式集合大小和 OOF 训练视图有效，但仍不满足零危险发布门；
唯一自动接受项 `T10:74155468 / 47267945_63009537@63009535` 预测 2 条，
真值要求 4 条。因此安全层不得放宽阈值，当前完整 access 自动发布为 0。

v134 的 619 条强监督中，563 条能在 v95 冻结的 truth-free 推理候选中
精确找到同一打断前父 Road、同一 `SPLIT_ROAD/REUSE_ENDPOINT` 操作和
同一位置；56 条不可达继续屏蔽，不以最近候选替代。v137 在这 563 条上
训练 144D、230,081 参数 side attachment scorer，teacher 与 strict OOF
双视图共同训练、OOF view 早停：

| 指标 | v137 |
|---|---:|
| strict Case-OOF exact | **0.943162** |
| teacher exact | 0.944938 |
| source exact | 0.942029 |
| target exact | 0.944251 |
| 最差 Case exact | 0.895349 |
| 上游完整 access release-ready | 0 |
| 自动接受 / 危险 | 0 / 0 |

v137 只证明“给定候选后选择提右单侧父 Road 与打断位置”的判别力，不是
完整提右正确率。完整提右仍需同时满足：普通 Segment 最终 access Road
集合、完整提右 Road 组合、source/target 两侧挂接、中间 splice、附属
Segment 挂接和最终拓扑。当前不得将 0.943162 解释为 T06 替代率。

全部改动后的完整 P05 回归为 `500 passed in 49.23s`，`compileall` 通过，
新增/修改源码与测试均低于 100KB。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_materializer_audit_20260729_v132_access_collection_internal_ar_full`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_access_collection_labels_20260729_v126`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_access_set_strict_nested_oof_20260729_v127_seed_20260729`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_attachment_supervision_20260729_v134_final_access_parent`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_access_cardinality_topk_strict_nested_oof_20260729_v135_seed_20260729`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_access_cardinality_dual_view_strict_nested_oof_20260729_v136_seed_20260730`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_side_attachment_strict_nested_oof_20260729_v137_seed_20260731`

## 2026-07-29 普通 Segment Road 所有权/正式角色多任务审计

### 输入版本与监督边界

v154/v156 证明更强的 Road 图注意力可以改善整体完整 Road 集合，但未解决
AdvanceRight 所依赖的普通 Segment：

| 运行 | 参数 | complete exact | Road F1 | 自动接受 / 危险 | 提右依赖 USE exact |
|---|---:|---:|---:|---:|---:|
| v154 mixed-attention | 624,964 | 0.633629 | 0.825496 | 945 / 23 | 17/314 |
| v156 anchor-Road cross-attention | 825,156 | **0.679861** | **0.852525** | 894 / 14 | 18/314 |

v156 的提右依赖子集 Road F1=`0.675089`、cardinality exact=`96/314`；
整体改进没有转化为关键依赖子集的完整集合能力。因此本轮没有继续做同类
阈值或 hidden-dim 扫描，而是加入显式 Road 所有权和正式角色监督。

正式训练输入统一为：

- truth-free candidate=`v114`，旧 `CORRIDOR_COMPONENT=0`，只继承
  `COMPONENT_ALL_MAIN / INTERNAL_CONNECTOR_TREE`；
- plan/anchor label=`v117`，继承用户裁决；
- anchor strict OOF=`v108`；
- member/ownership/role store=`v163`。

构建期间曾发现两个语义/版本错误并立即阻断：一次把 no-owner
Junction/connectivity 错写成 Road 角色；一次沿用了已废止的 v07
candidate store。对应 v158/v161 都只是未完成的无效部分运行，不进入任何
正式指标。最终标签严格拆分为：

- ownership：`OWNER_CURRENT_SEGMENT`、`NO_OWNER_JUNCTION_CONNECTIVITY`、
  `EXCLUDE_OR_OTHER_OWNER`；
- Road 正式角色：`MAIN / INTERNAL_CONNECTOR / ATTACHED_SWSD`；
- `NOT_SELECTED_FOR_CURRENT_SEGMENT` 只是 decoder null class，不是新增业务
  角色；no-owner connectivity 只由 ownership 输出，不伪装成 Road 角色。

v163 推理特征不读取 T06 终态，`feature_uses_truth=false`、
`terminal_input_count=0`。可训练普通 Segment=`3,156`，ownership label
=`108,114`，其中 owner=`8,799`、no-owner connectivity=`2,481`、
exclude/other owner=`96,834`；role label=`103,541`，但
`INTERNAL_CONNECTOR` 只有同一 Segment 内 2 条 Road，
`ATTACHED_SWSD=0`。这是真实监督稀疏，不得解释成参数不足。

切换到正式 v114 后，提右依赖 USE 可评价分母从 314 变为 312：
`T10:1885118 / 1898378_1898410` 与
`T10:605415675 / 1649480_1649532` 分别有 2 条、1 条目标 Road 不在当前
truth-free member pool，按不可达 mask，不用终态标签扩充候选。

### v164 直接融合与 v166 辅助多任务

两轮均为单 seed × 5-fold strict Case-OOF、teacher+OOF 双视图、OOF 早停，
参数量 942,604。v164 把 ownership/role logits 直接融合进 member logits；
v166 保留显式输出和共享 encoder loss，但不让业务头直接改写 member
logits。

| 指标 | v156 | v164 直接融合 | v166 辅助多任务 |
|---|---:|---:|---:|
| 可训练普通 Segment | 3,158 | 3,156 | 3,156 |
| complete exact | **0.679861** | 0.665082 | 0.663815 |
| Road macro F1 | **0.852525** | 0.849831 | 0.848516 |
| teacher complete exact | 0.690627 | 0.675539 | 0.675222 |
| 自动接受 | 894 | 1,115 | 943 |
| 自动覆盖 | 0.283091 | 0.353295 | 0.298796 |
| 自动 exact | 0.984340 | 0.975785 | 0.980912 |
| 危险自动项 | **14** | 27 | 18 |
| owner recall / precision | 未输出 | 0.922491 / 0.734105 | 0.915331 / 0.730257 |
| no-owner connectivity recall / precision | 未输出 | 0.340588 / 0.205047 | 0.351874 / 0.237680 |
| INTERNAL_CONNECTOR recall | 未输出 | 0/2 | 0/2 |

v164 证明 ownership/role 直接改写 member 会把 Junction/connectivity 或相邻
Road 误推成当前 owner，整体和安全性均下降。v166 证明将其改成辅助任务也
没有恢复整体 exact，不能靠 loss 权重或校准解释为已收敛。

提右依赖 USE 子集上，v166 为：

| 指标 | v156（314） | v166（312） |
|---|---:|---:|
| complete exact | 18/314=0.057325 | 22/312=0.070513 |
| Road F1 | 0.675089 | 0.689937 |
| cardinality exact | 96/314=0.305732 | 97/312=0.310897 |
| 自动接受 / 危险 | 0 / 0 | 0 / 0 |
| owner recall / precision | 未输出 | 0.904638 / 0.681051 |
| no-owner connectivity recall / precision | 未输出 | 0.471698 / 0.306577 |

关键子集有小幅改善，但不足以抵消整体退化，且 release coverage 仍为 0；
v164/v166 结论均为 **NO_GO**。下一轮不再做同类参数扫描，先吸收最小人工
裁决：

### v168 同正式输入单任务消融

为区分“v163 正式候选/锚定输入变化”与“所有权/角色多任务共享 encoder”
各自造成的影响，补充 v168 同输入消融。v168 与 v156 使用相同 seed
`20260742` 和相同 825,156 参数 anchor-Road decoder，但输入改为 v163，
并完全关闭 ownership/role decoder；仍执行 5-fold strict Case-OOF、
teacher+OOF 双视图及 OOF 早停。

| 指标 | v156 旧输入单任务 | v164 直接融合 | v166 辅助多任务 | v168 同输入单任务 |
|---|---:|---:|---:|---:|
| complete exact | **0.679861** | 0.665082 | 0.663815 | 0.663815 |
| Road macro F1 | **0.852525** | 0.849831 | 0.848516 | 0.850299 |
| teacher complete exact | **0.690627** | 0.675539 | 0.675222 | 0.674588 |
| 自动接受 | 894 | 1,115 | 943 | 998 |
| 自动覆盖 | 0.283091 | 0.353295 | 0.298796 | 0.316223 |
| 自动 exact | **0.984340** | 0.975785 | 0.980912 | 0.967936 |
| 危险自动项 | **14** | 27 | 18 | 32 |

v166 与 v168 的整体 complete exact 完全相同，说明相对 v156 的主要退化
来自正式候选/锚定输入切换，而不是辅助任务本身；v168 虽有略高 Road F1，
但危险自动项比 v166 多 14 条，不能视为更好的安全模型。

提右依赖 USE 子集上：

| 指标 | v166 辅助多任务（312） | v168 同输入单任务（312） |
|---|---:|---:|
| complete exact | **22/312=0.070513** | 15/312=0.048077 |
| Road F1 | 0.689937 | **0.708545** |
| cardinality exact | **97/312=0.310897** | 71/312=0.227564 |
| 自动接受 / 危险 | **0 / 0** | 1 / 1 |

v168 的局部 Road 重叠更高，但完整数量与完整组合更差；v166 的辅助输出
确实为关键链路提供了少量完整性与安全收益。因此当前选择是保留 v166
形态：ownership/role 必须显式输出并可参与共享 encoder 训练，但不得直接
融合改写 member logits。它仍是 **NO_GO**，现有 owner/role 标签不足以把
该收益提升为可接受覆盖，后续先回填人工裁决，不再做同族 loss/阈值扫描。

1. `T10:706247 / 708001_708003`：优先逐 Road 标
   `MAIN / INTERNAL_CONNECTOR / ATTACHED_SWSD`；
2. `T10:706247 / 706285_706290`：确认额外 Road
   `5395379941867683` 的所有权；
3. `T10:609214532 / 600991097_620990913`：确认
   `5384374759260185` 为非 owner；
4. `T10:609214532 / 949652_39464056`：确认正向 `KEEP_SWSD`；
5. `T10:609214532 / 60262104_60262137`：确认两条 owner Road；
6. `T10:74155468 / 89241765_520068509`：确认两条 owner Road。

已生成 v172 人工裁决证据包，包含 6 个相对路径 QGIS 项目、6 张静态预览、
一个 EPSG:3857 GeoPackage、10 行可填写裁决模板、215 条全候选 OOF
证据及哈希 manifest。证据包只复制冻结 T01 Segment 和 POC_Data 上下文
几何，不做 snapping/repair/reconnect/silent fix；其中包含 label-only
弱标签，明确 `inference_input_allowed=false`，不得作为推理输入。QGIS
回读验证为 6/6 项目、每个 8/8 图层有效，项目内无 WSL 绝对路径；单项目
headless 回读最大 0.296s。由于 QGIS 可能更新 GeoPackage 的 SQLite
容器元数据，不把整文件 SHA256 伪装成稳定内容证据；manifest 改为逐图层
记录排序后的属性与 geometry WKB 摘要，QGIS 全量回读后 8/8 图层摘要一致，
其余 16/16 输出文件 SHA256 一致。

v170 误用了不稳定的 GeoPackage 整文件哈希，v171 在 QGIS 退出后复用已
关闭的 GDAL driver manager 而未生成 manifest；两者均标记为
`DO_NOT_USE_PRELIMINARY`，不进入正式证据。

其中第 1 条是当前六条里唯一已有完整 Road 清单、但三条 owner Road 的正式
角色全部未知的对象；用户裁决后按权重 1.0 回填。当前不得把所有权辅助头
解释为 T06 替代能力，也不得放宽安全门。

本轮完整 P05 回归为 `523 passed in 50.12s`，P05 `compileall` 通过；
相关源码/测试均低于 100KB，训练文件达到 68,936 bytes，已同步登记
`code-size-audit.md` 的 60KiB 观察约束。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_formal_candidate_role_store_20260729_v163`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_formal_candidate_ownership_role_strict_nested_oof_20260729_v164_seed_20260745`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_formal_candidate_role_audit_20260729_v165`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_auxiliary_ownership_role_strict_nested_oof_20260729_v166_seed_20260746`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_auxiliary_role_audit_20260729_v167`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_formal_candidate_baseline_strict_nested_oof_20260729_v168_seed_20260742`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_formal_candidate_baseline_audit_20260729_v169`
- `outputs/_work/p05_neural_road_generation/target_a_phase1_manual_adjudication_evidence_20260729_v172`

## 2026-07-29：T06 混合场景监督恢复、v175 对照与首组 Road 角色人工裁决

### 标签适配缺口与修正

v163 中已有 30 条正式 `T06_MAIN_RCSD_ATTACHED_SWSD` Segment，但旧
Road-member adapter 只接受 `KEEP_SWSD / USE_RCSD`，因此这些样本全部未
进入训练，`ATTACHED_SWSD` 角色标签为 0。v174 修正后：

- 保留“RCSD 主干 + 附属 SWSD”的完整 Road 清单，不把它退化为通用
  HYBRID；
- 二分类 decision head 只把它映射为“主干执行 RCSD 替换”，原始业务状态
  继续单独输出；
- 4 条 anchor-ready 且完整候选可达的 Segment 进入训练；
- 产生 7 条确定的 `ATTACHED_SWSD` Road 角色真值；
- 最大完整 Road 清单为 66 条，cardinality 类别数改为 67；
- 新增容量硬门禁，禁止把 66 条真值静默裁成 64 条。

v173 曾把不可达 generated-final Road 从目标集合中移除，会把部分清单误当
完整标签，已标记 `DO_NOT_USE_PRELIMINARY`；v174 是正式替代工件。

### v175 strict Case-OOF

v175 沿用 v166 的辅助 ownership/role 多任务结构、同 seed `20260746`、
5-fold strict Case-OOF、teacher+OOF 双视图及 OOF 早停，仅替换为 v174
标签工件并把 cardinality 类别数从 65 提升到 67。参数量由 942,604 增至
942,862，训练覆盖 gate 通过，耗时 1,826.089s。

| 指标 | v166 | v175 | 变化 |
|---|---:|---:|---:|
| 可训练普通 Segment | 3,156 | 3,160 | +4 |
| complete exact | 0.663815 | **0.672785** | +0.008970 |
| Road macro F1 | 0.848516 | **0.854906** | +0.006389 |
| cardinality exact | 0.727503 | **0.737025** | +0.009522 |
| 自动接受 | 943 | **1,047** | +104 |
| 自动覆盖 | 0.298796 | **0.331329** | +0.032533 |
| 自动 exact | 0.980912 | **0.984718** | +0.003806 |
| 危险自动项 | 18 | **16** | -2 |
| 业务角色整例 exact | 0.728454 | **0.752532** | +0.024078 |

在 v166/v175 共同的 3,156 条对象上，v175 complete exact 为 0.673638，
Road F1 为 0.855220，自动覆盖为 0.331749，危险自动项仍为 16。危险项并
非稳定地解决原错误：旧 18 条中解决 10 条，但新增 8 条，只有 8 条重合。
因此危险数下降 2 不能解释为安全边界已经收敛。

### v176 关键子集审计

4 条 T06 混合 Segment 的 decision exact 为 4/4，但：

- 完整 Road 清单 exact 为 0/4；
- cardinality exact 为 0/4；
- Road macro F1 为 0.607016；
- 7 条 `ATTACHED_SWSD` 的预测数、正确数和 recall 均为 0；
- 四条真值 cardinality 分别为 10、12、15、66，预测分别为
  6、6、12、12。

提右依赖的普通 `USE_RCSD` 子集为 313 条，complete exact 仅
0.063898、Road F1 0.720935、cardinality exact 0.281150，自动接受仍为
0。当前平坦 cardinality + member top-k decoder 能改善一般集合重叠，但
不能可靠生成大 Road bundle，也没有学会附属 SWSD 与内部连接 Road 的正式
角色。v175/v176 结论仍为 **NO_GO**，下一步不得继续做同族阈值扫描。

### 用户首组 Road 角色裁决与 v177

用户对 `T10:706247 / 708001_708003` 确认：

- `5391352334583582 = MAIN`；
- `5391352334583612 = INTERNAL_CONNECTOR`；
- `5391352334583619 = MAIN`。

三条均确认为当前 Segment owner。v177 只把这三条 ownership/role 作为
权重 1.0 的人工真值；Segment decision/member 的 T10 Case 级权重仍保持
0.7，不因局部角色裁决擅自升级为完整集合人工真值。未裁决候选不补造
owner/no-owner 或 Road 角色。

v177 gate 通过，人工 Road 角色数为 3，角色计数更新为
`MAIN=4,226 / INTERNAL_CONNECTOR=3 / ATTACHED_SWSD=7`。v174 与 v177
推理特征文件 SHA256 均为
`0549E855F276B53F86B8310AF1156BA5871D49E8189B6DC4E2FB127FDF2522B5`，
证明人工裁决只进入 label/loss，没有进入推理输入。训练读取后该 Segment
base weight 为 0.7，ownership/role weight 为 1.0，对应 loss 比例
1.428571，且两个辅助任务都只打开三条人工确认 Road 的 mask。

本轮完整 P05 回归为 `527 passed in 50.93s`，P05 `compileall` 通过；
所有修改源码低于 100KB，当前训练文件 71,744 bytes，已同步登记
`code-size-audit.md`。

新增正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_t06_mixed_role_store_20260729_v174`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_auxiliary_t06_mixed_role_strict_nested_oof_20260729_v175_seed_20260746`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_auxiliary_t06_mixed_role_audit_20260729_v176`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_user_role_store_20260729_v177`

## 2026-07-29：多尺度 Road 关系消融、第二组人工成员裁决与安全重算

### 几何连通性只适合作为证据，不能作为硬业务规则

v178 对 3,160 条可训练 Segment 的完整目标 Road 清单做只读几何距离审计，
不执行 snapping、repair、reconnect 或 silent fix。多 Road Segment 在
0/1/3/6/12/25m 下连成单组件的比例分别为
0.179408/0.306412/0.432182/0.737361/0.879162/0.939581。4 条正式
`T06_MAIN_RCSD_ATTACHED_SWSD` 中有 3 条在 1m 内连通，最后一条到 12m
才连通。因此距离可进入模型证据，但不存在一个可固化为业务正确性的统一
硬阈值。

v179 在不保存绝对坐标的前提下，为 8,389 条 Segment / 210,147 条候选
Road 构建 726,556 条 25m 内稀疏 Road–Road 关系，每条关系为 13D 相对
几何/拓扑证据；gate 通过，构建耗时 93.142s。关系只写入 truth-free
feature 文件，标签文件保持独立。

### v182：关系仅作 attention bias 为 NO_GO

v180 因逐 edge 创建 CUDA 小张量导致 CPU 瓶颈，首折 22 分钟未完成，
未产生结果目录；批处理改为每 Segment 一次向量化传输后，最密 40 条
Segment、20,978 条关系、最大 199 Road 的关系张量重建为 0.800s。

v182 与 v175 使用同 seed/config，仅新增 13D learned attention bias。
前两折均相对 v175 退化，且危险自动项没有改善：

| fold | complete exact v175 → v182 | Road F1 v175 → v182 | unsafe |
|---:|---:|---:|---:|
| 0 | 0.675388 → 0.648406 | 0.867650 → 0.850648 | 5 → 5 |
| 1 | 0.672096 → 0.642780 | 0.858841 → 0.853517 | 6 → 6 |

v182 提前停止并标记 `DO_NOT_USE_PRELIMINARY`。结论仅淘汰“把关系作为
attention bias”这一实现，不否定关系证据或联合网络方向。

### 第二组人工裁决与 v189 标签仓

用户确认 `T10:706247 / 706285_706290 / 5395379941867683` 为
`OWNER_CURRENT_SEGMENT`。该裁决证明 v175 对此 Segment 的额外选择不是
危险模型错误，而是 T10 0.7 弱标签漏标。

v189 将目标 Road 清单从单条 `5395379941867708` 修正为两条，并严格拆分
监督权重：

- `5395379941867683` 的 member 与 ownership 权重为 1.0；
- Road 角色未人工裁决，仍按现有弱证据权重 0.7；
- Segment 其余候选、decision 与完整清单仍保持 T10 权重 0.7。

v189 gate 通过；人工计数为 membership 1、role 3。feature SHA256 为
`F3D62E0AC36E69141E160A2C5AF6D44BB554D15CC379F083084DC7FB161947E7`，
与 v179 完全一致，证明人工裁决没有进入推理输入；label SHA256 为
`CCCEFEED9F38B6808C9E34C1DD38C1953268B9A7C21B90F608ACFDEF9AC28928`。

### v190 显式 pair 共成员组件目标为 NO_GO

v190 恢复 v175 的 endpoint-only Graph Encoder 邻接，关闭关系 attention
bias，只让多尺度关系进入显式 pair 共成员 head，避免变量混杂。首折结果：

| 指标 | v175 fold 0 | v190 fold 0 |
|---|---:|---:|
| complete exact | **0.675388** | 0.652494 |
| Road macro F1 | **0.867650** | 0.855747 |
| 危险自动项 | **5** | 12 |
| component edge precision / recall / F1 | 无 | 0.231581 / 0.947859 / 0.372222 |

该目标把同源近邻 Road 过度聚合，且首折耗时接近 v175 两倍。v190 提前停止
并标记 `DO_NOT_USE_PRELIMINARY`；不得通过调低 loss 权重把它包装为成功。

### v192：不重训的弱标签修正重算

v192 直接使用 v175 strict OOF checkpoints 在 v189 修正标签上重新评分，
没有训练新模型。`706285_706290` 从 1→2 的“危险多选”修正为 2→2 完整
命中，仍为自动接受；总体危险自动项 16→15，没有新增危险项，自动 exact
0.984718→0.985673，complete exact 0.672785→0.673101。说明该人工裁决
消除了 1 条假危险，但不改变 v175 整体 **NO_GO**。

下一人工问题升级为双向所有权联合裁决：
`600991097_620990913` 与 `620990913_600991097` 当前弱标签分别把
`5384374759260189`、`5384374759260185` 设为 owner，而模型对两个方向都
选择两条；按唯一所有权约束，必须联合确认两条 Road 对两个正式 Segment
的归属，不能继续只问单 Road 是否为额外 owner。

本轮完整 P05 回归为 `535 passed in 51.55s`。所有源码低于 100KB；
训练文件为 85,201 bytes，已在 `code-size-audit.md` 登记为下一次新增职责
前必须拆分。

新增正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_target_geometry_connectivity_audit_20260729_v178`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_multiscale_relation_store_20260729_v179`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_multiscale_relation_user_membership_20260729_v189`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_road_v175_user_membership_reaudit_20260729_v192`

## 2026-07-29：剩余危险项方向/所有权/完整方案可达性审计

### v194：方向只能作软证据，不是当前主要缺口

v194 对 v192 剩余 15 个危险自动 Segment、36 条目标/额外 Road 做
EPSG:3857 只读方向审计；不执行 snapping、repair、reconnect 或
silent fix。15 条额外 Road 中 10 条的原始有向夹角为负；但同一危险集合
21 条目标 Road 中也有 8 条为负。对完整 3,160 条可训练普通 Segment
执行反事实硬剔除会把 exact 从 2,127 降为 1,499，危险自动项从 15 增至
340，因此方向不得成为 hard mask。

随后按正式方向枚举复核当前 40D candidate-local 特征：`direction=2`
沿 `snodeid→enodeid`，`direction=3` 沿反向，`direction=0/1` 为双向。
当前目标 Road 中 `direction=2` 为 7,669/8,903，其余 1,234 条为双向或
未知；危险集合没有 `direction=3` Road。重算有效通行方向后，15 个危险项
的正负方向分类全部不变。结论是现有特征已经包含方向信息，当前错误不是
方向枚举解释错误，而是完整 Road 组合与所有权竞争不足。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_unsafe_directional_evidence_audit_20260729_v194`

### 跨 Segment 唯一所有权只解决危险项的一部分

在 v189 的 3,160 条可训练普通 Segment 中，按 Case+raw RCSD Road 联合审计：

- 15,825 个 Case-Road 对中，13,688 个进入多个 Segment 的候选池；
- 7,132 条 Road 有唯一 owner 真值，owner 冲突为 0；
- 其中 6,673/7,132=0.935642 同时出现在其他 Segment 候选池；
- 605 条无 owner 的 Junction/connectivity Road 被多个 Segment 合法关联。

这证明冲突连通组 decoder 有充分训练信号，且唯一所有权不能退化为
“Road 只能出现在一个 Segment 候选池”。但 v192 的 15 条额外 Road 中，
只有 2 条已被另一正式 Segment 标为 owner；13 条只是跨 Segment 候选或
无已知 owner。因此全局唯一所有权能够直接阻断 2 条危险项，不能代替
Segment 内完整 Road 清单判断。

### 完整方案候选优于逐 Road top-k，但当前候选覆盖仍不是完整目标

把 v114 truth-free 完整 carrier 方案与 v189 修正后的完整 Road 真值按
decision+Road 集合严格比较：

| 范围 | 精确候选可达 | 总数 | 覆盖 |
|---|---:|---:|---:|
| 全部可训练普通 Segment | 2,363 | 3,160 | 0.747785 |
| 正向 KEEP_SWSD | 1,447 | 1,447 | 1.000000 |
| USE_RCSD | 916 | 1,709 | 0.535986 |
| T06 主干 RCSD+附属 SWSD | 0 | 4 | 0.000000 |
| v192 剩余危险项 | 11 | 15 | 0.733333 |

v175 的 OOF member 排序若使用真值 cardinality，完整 Road exact 为
2,685/3,160=0.849684；与 v114 完整方案取并集后的 Oracle 可达为
2,733/3,160=0.864873，覆盖剩余危险项 13/15。说明下一代 decoder 应直接
评分完整 carrier 方案，并允许网络从冻结 Road 候选池生成新的结构化方案；
不能继续用平坦 cardinality+top-k，也不能把 v114 候选集当作完整业务空间。

当前 15 个危险项中 12 个预测 cardinality 错误，最常见的是单 Road 真值
被高置信预测为两条；另外 3 个虽 cardinality 相同但 decision 或 Road
身份错误。现有 v120 完整 plan 模型与 v175 member 模型做原始一致性门后，
自动范围为 958 条、exact=953/958=0.994781，仍有 5 条危险；继续叠加
v120 旧 safety 门只保留 408 条且仍有 2 条危险。该结果仅作互补性诊断，
不作为新发布门或新正式基线。

## 2026-07-29：完整 Road 方案 reranker strict-nested OOF

### 实验边界

本轮冻结 v175 的 942,862 参数普通 Segment Road encoder，不再向其
85,201 bytes 训练文件增加职责。新增 302,305 参数的完整方案
Set/Transformer reranker，候选为：

- v114 truth-free、hard-valid 的完整 KEEP/USE Road 方案；
- 冻结 member 分数按 SWSD/RCSD 来源分别生成的 1..K 完整前缀方案；
- 显式 `ABSTAIN`。

方案特征为 153D，只包含 generator 类型、冻结 decision/member 证据、
方案 cardinality/边界 margin 和 v114 的 64D 静态方案证据均值/最大值；
raw ID 只用于 join/audit，不进入 embedding。标签在所有特征和候选生成后
才标记 exact acceptable proposal；不可达真值只把 `ABSTAIN` 标为安全
目标。

v175 原始 checkpoint 来自 v174，而 v189 在保持 3,160 个样本的
Road 顺序、锚定条件、object/candidate/OOF 特征和 release 状态完全一致的
基础上新增 13D Road-relation 审计字段，并只修改
`706285_706290` 一条 member 真值。为避免错误地把新增字段送入旧
checkpoint，本轮严格用 v174 原始推理输入复现冻结 encoder 分数，再用
v189 当前真值训练/验收方案层。逐字段对齐检查为 3,160/3,160 通过。

每个 outer fold 的 reranker 只在 outer/inner 之外的 Case 上训练，在
inner Case 上定阈值，outer Case 只用于最终验收。v196/v197 为训练前数据
契约/路径解析诊断，v198 因外部命令 60s 超时终止，均未产生 summary，
不得解释为模型结果。

### v199：完整方案选择能力提升，但安全门失败

v199 固定训练 30 epoch，5-fold CUDA 完成，耗时 613.726s。当前
proposal union 的 exact 可达上限保持 2,733/3,160=0.864873。正式结果：

| 指标 | v175 按 v189 真值重算 | v199 |
|---|---:|---:|
| raw complete exact | 2,127/3,160 = 0.673101 | **2,231/3,160 = 0.706013** |
| 相对修正/退化 | - | 修正 180，退化 76，净增 104 |
| 自动接受数/覆盖 | 1,047 / 0.331329 | 894 / 0.282911 |
| 危险自动项 | 15 | **12** |
| 自动接受 exact | 0.985673 | 0.986577 |
| 模型主动 ABSTAIN | 不适用 | 379 |

raw exact 提升 3.291 个百分点，证明“完整方案直接评分”优于平坦
cardinality+top-k；但 12 条危险项仍使 gate 失败，结论为 `NO_GO`。
12/12 的真值都在 proposal union 中，且错误选择也都是 v114 hard-valid
静态方案，不是正确候选缺失或前缀生成失败，而是跨 Case 方案判别失败。

按 Case+raw RCSD Road 对 v199 自动接受结果增加最保守的唯一所有权阻断，
可发现 2 个重复 Road 冲突，正好是
`600991097_620990913`/`620990913_600991097` 两条反向 Segment；两者均
fallback 后接受数为 892、危险项为 10。说明冲突连通组 decoder 是必要的，
但不能替代其余 4 条 Road 清单完整性错误和 6 条 KEEP/USE 决策错误。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_complete_plan_proposal_reranker_strict_oof_20260729_v199_e30_seed_20260765`

### v200：inner 早停不能解决高置信跨 Case 错误

v200 只改变训练纪律：最多 60 epoch、patience=8，在 inner fold 恢复最佳
validation loss checkpoint，候选、特征、标签和安全阈值不变。5-fold
CUDA 耗时 530.401s，最佳 epoch 为 12/16/15/16/12。结果：

- raw complete exact 2,222/3,160=0.703165，低于 v199；
- 自动接受 1,054/3,160=0.333544；
- 危险自动项 20，自动接受 exact=0.981025；
- gate 失败，结论 `NO_GO`。

早停反而把 inner 阈值降到 0.79–0.97 并扩大危险接受，证明剩余问题不是
固定 30 epoch 的一般过拟合，也不能继续靠局部阈值调优。下一轮应进入
已确认的冲突连通组全局组合与共享 encoder 的联合方案 loss；局部 reranker
仅保留为消融证据，不作为发布门。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_complete_plan_proposal_reranker_strict_oof_20260729_v200_early_stop_seed_20260765`

## 2026-07-29：共享 Road encoder 的完整方案联合训练

### 实现合同

v199/v200 冻结 encoder 后，完整方案选择已证明可提升 raw exact，但 inner
阈值不能保证 outer 安全。本轮不再向 85,201 bytes 的旧训练文件增加职责，
新增以下联合链路：

1. 用 v175 strict checkpoint 初始化 942,862 参数的 anchor/Road/
   ownership/role encoder；
2. 对每个 truth-free 完整方案池化 selected/excluded Road embedding，并
   同时读取 trainable decision/cardinality/member 证据；
3. 以 acceptable-set plan loss 与旧 decision/member/ownership/role
   auxiliary loss 联合 fine-tune，共享 encoder 可接收完整方案梯度；
4. inner 模型只在 outer/inner 之外训练并在 inner 选 epoch；outer 模型从
   对应 base checkpoint 初始化，在全部 non-outer Case 固定重训相同 epoch，
   outer 只验收；
5. top-K 方案逐 Road 输出模型预测的 ownership 和正式业务角色；
   ownership 与角色分离，`NO_OWNER_JUNCTION_CONNECTIVITY` 不创建新
   Road 角色。

专项测试已证明 plan loss 梯度实际到达 candidate encoder；v189 当前标签
可覆盖 v174 checkpoint 输入，而新增 13D Road relation 不会误送给旧模型。

### v201 fold 0：选择能力继续改善，发布安全退化

v201 只执行 outer fold 0（`T10:1885118`，1,223 条普通 Segment），最多
8 epoch、patience=3，最佳 epoch=4。模型参数 1,073,167，其中新 plan head
130,305；CUDA 耗时 423.173s。

| fold 0 指标 | v175 | v199 | v201 shared encoder |
|---|---:|---:|---:|
| raw complete exact | 0.675388 | 0.713001 | **0.719542** |
| 自动接受 | 407 | 310 | 529 |
| 危险自动项 | **5** | **3** | 19 |
| 自动覆盖 | 0.332789 | 0.253475 | 0.432543 |

v201 的 top-5 中正确完整方案可达 1,018/1,223=0.832379；top-1 错误中
另有 138 条可由 top-5 表达，证明共享 encoder 的候选排序仍有改进空间。
但 inner 零错误阈值在唯一 outer Case 上产生 19 条高置信错误，因此不得
扩完整 5-fold 或 3-seed，结论 `NO_GO`。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_shared_encoder_joint_plan_strict_nested_oof_20260729_v201_fold0_e8_seed_20260766`

### v202/v203：decoder 不得用 lower-rank 候选重做业务判断

v202 把 v201 top-5 的模型 ownership/role 输出接入既有
`StructuredRoadGraphDecoder`。初版在 top-1 因角色/ownership 不完整时
自动选了未单独取得 release 资格的 top-2，使危险项 19→20。该行为违反
“decoder 只组合已确认方案，不能替模型重新判断业务事实”，已立即修正。

v203 规定当前只有 top-1 可发布；top-2..5 仅作候选覆盖审计，未来只有模型
显式输出逐方案 release 资格后才能进入全局择优。修正后：

- 模型接受 529，2 条因 top-1 缺正式角色而 Segment fallback；
- decoder 自动 527，危险 19，没有新增危险；
- 527 个冲突连通组最大大小仍为 1，fold 0 没有共享 owned Road 冲突可供
  全局 decoder 消解；
- lower-rank 自动改选为 0，skeleton mutation=0。

这证明 decoder 合同正确，但不能修复局部模型已经选错的完整方案。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_shared_encoder_joint_plan_decoder_audit_20260729_v202_fold0`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_shared_encoder_joint_plan_decoder_audit_20260729_v203_fold0_top1_release`

### v204：独立逐方案 validity head 仍不能跨 Case 保证安全

v204 在共享 plan representation 上增加独立 sigmoid validity head：
selection head 负责选方案，validity head 预测选中方案是否可自动发布；
release confidence 为 validity × selection probability × selection margin。
方案池、标签和 outer/inner 划分不变。

最佳 epoch=3，参数量 1,073,296，CUDA 耗时 381.128s。fold 0 raw exact
继续提升到 **0.722813**，但自动接受 559 条、危险 22、自动 exact
0.960644。独立 absolute correctness loss 仍未跨 Case 泛化，结论
`NO_GO`；不得继续把同一输入上的 head/threshold 调参解释为安全方案。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_shared_encoder_joint_plan_validity_strict_nested_oof_20260729_v204_fold0_e8_seed_20260766`

## 2026-07-29：自动 RCSD ledger 到最终 RoadGraph 的真实数据 smoke

### 执行边界

为关闭 T014 中“模型决定已经存在，但尚未进入最终一次物化”的结构缺口，
新增两层内部适配：

1. 完整链 ledger 装配器只接受与 decoder 选中 `plan_id` 完全绑定的执行
   指令；自动方案的 Road 来源、正式角色与所有权必须与模型完整 Road 清单
   一致。正向 `KEEP_SWSD` 从已经验证的完整 T01 SWSD 指令转为正向结果，
   与 `ABSTAIN → fallback` 分开记录；
2. ordinary whole-Road 编译器只处理“required anchor 已由独立锚定模型锁定
   为 Node、所选 Road 无打断”的可执行路径。它从源 Road 复制方向和几何，
   将已锁定 Node 写成 access Node recipe，并把与该 Node 相交的已选 Road
   全部写入 access；不选择锚定对象、不补 Road、不执行未声明打断。

若执行指令缺失、`plan_id` 不一致、Road 角色/所有权改变、锚定 Node 不在
所选 Road 上，或模型计划要求 split 而没有显式 split 指令，装配器直接拒绝，
不会用后处理猜测修复。

### v206 选样泄漏纠正

v206 的模型 forward 和物化输入没有终态字段，但初次挑选 smoke 样本时读取了
`proven_safe_anchor` 评估字段。该字段没有送入模型或 materializer，却会把
“挑一个已知正确样本”误写成“纯推理期选样”。因此 v206 立即降级为仅证明
编译器可执行的诊断工件，不进入无泄漏、性能、安全或发布结论。

### v207 纯推理期选样与确定性双跑

v207 重新从现有工件中筛选，仅使用以下推理字段：

- ordinary OOF 为 automatic `USE_RCSD`；
- 两个 required anchor 均为 `gate_passed + predicted SUCCESS`，且各自只
  输出一个 `NODE:` 候选；
- Segment 无 junc access，选中 Road 在锁定 Node 上具有端点 incidence；
- 不读取 `label`、`candidate_acceptable_exact`、`proven_safe_anchor`
  或普通 Segment 终态 exact。

共有 348 个 Segment 满足该结构条件；按 store 顺序选择第一条：

- Case/Segment：
  `T10-Error-2:13394084_786858 / 13394084_786858`；
- 锚定：两个 required anchor 均由 v65 strict OOF 独立输出唯一 RCSD Node；
- ordinary：v69 strict OOF 输出 `USE_RCSD` 完整方案
  `tap:28bf5dd45b6d2896ec0ae5f2`；
- 选中 RCSD Road：
  `5384374825399367`、`5393143504374348`；
- 几何边界：两条均为完整源 Road，无打断、拼接或补造。

同一 ledger 连续两次物化结果：

| 指标 | v207 |
|---|---:|
| 自动 Segment | 1 |
| fallback Segment | 0 |
| 最终 Road | 2 |
| 最终 Node | 3 |
| directed edge | 2 |
| frozen access binding | 2 |
| skeleton mutation | 0 |
| silent fix | 0 |
| content repair | 0 |
| canonical hash 一致 | 是 |

两个冻结 access 分别绑定到模型锁定的 RCSD Node，且各自完整包含与该 Node
相交的已选 Road。输入 skeleton、anchor OOF、ordinary OOF、候选 store、
原始 RCSD Road/Node 均记录路径与 SHA256。

### v208 全部 348 条推理期候选的可执行性审计

v208 对全部 348 个结构候选逐 Segment 执行相同编译和 materializer hard
validation，不读取标签：

| 指标 | v208 |
|---|---:|
| eligible | 348 |
| 可直接执行 | 114 |
| preflight 阻断 | 234 |
| 可执行覆盖 | 0.327586 |
| skeleton mutation / silent fix / content repair | 0 / 0 / 0 |

234 条阻断的唯一原因均为
`access direction role differs from its complete Road/Node set`。对照 T06
正式逻辑后确认：T06 使用原始 RCSD `direction` 验证两端有向可达，不会
任意改写 Road 方向。因此这些结果不是“几何没连接”，而是模型选中 Road
集合在已锁定 Node 下不满足冻结 Segment 的方向语义；应作为通用拓扑
hard mask 只回退该 Segment，禁止通过 reverse 猜测或扩大 fallback。

完整链 ledger 已支持显式 `preflight_fallback_reasons`：它只接受自动模型
决定作为拒绝对象，禁止保留对应自动执行 recipe，并记录被拒 Segment 与
原因；其他 Segment 不受影响。

### v209 完整 26-Segment Case 一次物化

v209 使用 v207 的纯推理期选择结果，在
`T10-Error-2:13394084_786858` 完整冻结 Case 中保留 1 个自动 RCSD
普通 Segment，其余 25 个 Segment 显式局部 fallback：

| 指标 | v209 |
|---|---:|
| frozen Segment | 26 |
| 自动 RCSD / fallback | 1 / 25 |
| 最终 Road / Node | 38 / 41 |
| directed edge / access binding | 40 / 58 |
| skeleton mutation / silent fix / content repair | 0 / 0 / 0 |
| 完整 Case canonical hash 双跑一致 | 是 |

这首次证明目标 A 的“网络锚定 → 完整 Road 方案 → topology hard mask →
有限 fallback → 完整 Case Road/Node/access 一次写出”在真实数据上可执行。
它仍不是业务正确率或安全发布结论：v65/v69 本身为 `NO_GO`，v208 仅评估
可执行性，当前编译路径仍限于 locked-Node + whole-Road；尚未覆盖
Road/打断锚定、普通 junc access 完整集合、自动 AdvanceRight、完整策略
paired exact 和 51 Case 双跑。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_full_chain_real_automatic_rcsd_smoke_20260729_v206`
- `outputs/_work/p05_neural_road_generation/target_a_full_chain_inference_only_selection_double_run_20260729_v207`
- `outputs/_work/p05_neural_road_generation/target_a_full_chain_inference_only_executability_audit_20260729_v208`
- `outputs/_work/p05_neural_road_generation/target_a_full_chain_complete_case_one_auto_rcsd_20260729_v209`

## 2026-07-29：AdvanceRight 端点复用型执行链

### 发现并修正的 access 语义错位

decoder 的正式合同一直是：AdvanceRight
`source_access_road_id/target_access_road_id` 引用两侧相邻普通 Segment
最终采用的 access Road，提右只形成挂接关系，不取得这些 Road 的所有权。
但 v209 前的完整链 ledger 仍把这两个 id 当作提右自身 Road alias 校验，
会拒绝业务上正确的自动提右执行指令。

本轮将该校验限定到普通 Segment；AdvanceRight 自有 Road 仍严格比较模型
完整 Road 清单的 source/role/ownership，父 access Road 则由两侧 attachment
编译合同绑定。与此同时，AdvanceRight 的正向 `KEEP_SWSD` 不再像普通
Segment 一样无条件把 T01 fallback 改名为正向 KEEP：它也必须给出服从
两侧普通 Segment 最终 access 来源的条件化执行指令，避免绕过提右正式链路。

### 当前新增的可执行范围

新增 `target_a_advance_right_materialization.py`，输入全部是模型已确定结果：

- 完整提右 Road 清单；
- source/target 相邻普通 Segment；
- 两侧最终 access binding 与父 Road；
- 两侧提右 child Road 与 child endpoint；
- 两侧最终 Road 来源条件。

确定性层只复制整条 source Road、复用已锁定端点 Node，并分别写出：

- RCSD 相邻侧：明确父 Road instruction 与 `0/length` 端点位置的
  `ROAD_POSITION`；
- SWSD 相邻侧：复用冻结 Node/JunctionUnit id 的
  `FROZEN_ACCESS_NODE`。

编译器不会选择相邻 Segment、父 Road、提右 Road、端点或来源，也不会把
父 access Road 所有权转给提右。父/子端点不重合、父 Road 不在已选 access
binding、decoder source condition 不一致、Road 已要求打断/片段时都会
拒绝，由调用方仅回退当前 AdvanceRight Segment。

当前范围只覆盖 whole-Road + endpoint reuse。父 Road 中间打断、提右 Road
片段和两侧来源不一致时的中间 RCSD/SWSD splice 仍需下一版 split-capable
编译器；本轮不把端点单测解释为完整 T06 替代率或真实自动提右安全结果。

### 旧 OOF 输出的结构覆盖审计

对 v103 的 474 条 AdvanceRight strict OOF 只用推理输出字段
`adjacent_context_resolved`、`predicted_plan_type`、
`missing_geometry_proposal_types` 和
`selected_geometry_proposals.operation` 过滤：

| 指标 | 数量 |
|---|---:|
| OOF AdvanceRight | 474 |
| 预测 `RCSD_ONLY / SWSD_ONLY / MIXED_SPLICE / REVIEW_FALLBACK` | 50 / 245 / 139 / 40 |
| 两侧均显式 `REUSE_ENDPOINT` 且非 MIXED 的当前可编译结构 | 49 |
| 当前结构覆盖 | 0.103376 |
| 其中 raw plan exact（仅评价） | 38 |
| 其中完整 plan + geometry exact（仅评价） | 7 |
| base/effective automatic | 0 / 0 |

筛选没有读取 exact 或 safety truth；exact 字段只在结构集合确定后评价。
v103 依赖的是较早的普通 Segment/锚定 store，本表不能替代当前重训或发布
指标。它只说明：端点编译器关闭了必要执行缺口，但对现有输出结构覆盖有限，
且没有可发布自动结果；下一实现优先级应转向模型已经定义的父 Road
`SPLIT_ROAD`、child Road 片段与 `MIXED_SPLICE` 指令，而不是继续增加
端点特判。

## 2026-07-29：方案 A 独立 MIXED_SPLICE 执行链与 v212/v217

### 业务与执行边界

按用户裁决，`AdvanceRight MIXED_SPLICE` 是独立条件化几何方案，不属于
普通 Segment 的通用 HYBRID。普通 Segment 仍只允许完整 RCSD 主干，唯一
SWSD 保留仍是 T06 已定义的附属/侧向场景。MIXED_SPLICE 只有在两侧相邻
普通 Segment 最终 access 来源一侧 RCSD、一侧 SWSD 时成立。

新增执行链要求模型显式给出完整提右 RCSD/SWSD Road 组合、RCSD 侧父
access Road、打断/端点位置、child endpoint、中间两侧 splice 位置和最终
方向；T01 提供冻结的相邻 Segment、access identity、SWSD endpoint 与方向。
确定性层只执行：

- 把已选普通 RCSD parent Road 打断为两个不重叠最终片段；
- 按模型选择保留 RCSD/SWSD Road interval；
- 执行显式 `STRAIGHT_CONNECTOR`，生成 Node ID 并写出两侧 attachment；
- 保持提右 Road 的 `ADVANCE_RIGHT` 角色和唯一所有权；
- 任一 recipe 缺失或跨 head Road 不一致时只回退当前 AdvanceRight。

合成整图测试已覆盖 parent split、两源 retained interval、端点/中间衔接、
完整 access、attachment、所有权和拓扑；结果
`skeleton_mutation_count=0`、`silent_fix=false`、
`content_repair=false`。

### parent-piece 候选与 v212

中间父 Road 打断不再由执行器暗选片段。候选层对每个 interior
`SPLIT_ROAD` 同时生成 `SOURCE_PART` 与 `TARGET_PART`，作为多解标签进入
loss；端点复用不生成片段选择。proposal 特征由 111D 增至 113D。

| 候选工件 | 对象 | proposal | 可达 teacher variant | feature truth |
|---|---:|---:|---:|---:|
| v210 teacher | 474 | 28,343 | 249/249 | 0 |
| v211 strict OOF | 474 | 7,345 | 46/249 | 0 |

v210/v211 分别含 5,890/1,818 条 split 片段候选，但当前 weak geometry
teacher 没有一条可达完整 variant 以 interior split 为正标签；这不是候选
缺失，而是该 teacher 标签无法辨识 parent-piece。已有 v134/v137 单侧正式
挂接监督仍单独有效，不能把 weak replay 冒充正式动作真值。

v212 使用 v210/v211 重训 113D 几何头，参数量 1,221,363，其中几何头
355,970；RTX 5090 单 seed × 5 Case folds 用时 57.59 秒。

| 指标 | v103 | v212 |
|---|---:|---:|
| complete plan+geometry raw exact | 0.556962 | 0.556962 |
| raw end-to-end complete exact | 0.056962 | 0.056962 |
| 自动接受 / 危险 | 33 / 30 | 33 / 30 |
| MIXED 完整结构 recipe | 133/139 | 135/139 |
| MIXED 自动接受 | 0 | 0 |

v212 只补齐执行表达，没有改善判别或安全门，结论 `NO_GO`。

### v217：串联更强单侧挂接后的真实误差暴露

为避免继续使用较早 v95 条件，v213/v214 从 v146（普通联合状态 +
v145/v137 单侧挂接预测）重建 teacher/strict-OOF 条件视图；v215/v216
重新生成几何候选。strict OOF 可达 weak geometry task 从 46 个增至
137 个，但相邻普通结果也把更多侧锁为 RCSD。

v217 以 v147 carrier 预测为 base、v146 为 access 条件，重新训练同一
113D structured geometry decoder：

| 指标 | v212（旧保守条件） | v217（联合普通/挂接条件） |
|---|---:|---:|
| complete plan+geometry raw exact | 0.556962 | 0.162447 |
| raw end-to-end complete exact | 0.056962 | 0.006329 |
| geometry action exact | 0.705882 | 0.203704 |
| 自动接受 / 危险 | 33 / 30 | 0 / 0 |
| MIXED complete exact | 旧条件不可直接同比 | 0.045455 |

两轮标签分布和相邻 source 条件不同，不能把表格解释为同口径模型退化；
它证明的是：更真实地释放 RCSD 普通 access 后，现有分阶段
ordinary → attachment → AdvanceRight scorer 无法保持完整 Road 组合、
挂接与 splice 一致。v212 的较高 raw exact 不能代表目标 A 收敛。

正式结论仍为 **NO_GO**。下一模型迭代必须把普通最终 access、提右完整
Road bundle、attachment 和 splice 放入共享 encoder 的联合结构化 loss，
停止继续叠加独立局部 scorer；锚定独立硬门、T01 骨架和局部 fallback
边界保持不变。

### v218：carrier/geometry shared encoder 联合微调

v218 在 v217 完全相同的 v146 普通/挂接条件、v215/v216 geometry
candidate 和 v147 base checkpoint 上，开放原本冻结的 AdvanceRight
carrier encoder，并以
`L_geometry + 0.5 × L_carrier(plan+safety+cardinality+Road-set)`
联合微调全部 1,221,363 个参数。学习率降为 `1e-4`，单 seed × 5 Case
fold 用时 112.66 秒。代码保持默认 frozen-base 行为，只有显式同时设置
`fine_tune_base=true` 与正 `base_loss_weight` 才进入联合模式。

| 指标 | v217 frozen base | v218 joint fine-tune |
|---|---:|---:|
| complete plan+geometry raw exact | 0.162447 | 0.177215 |
| raw end-to-end complete exact | 0.006329 | 0.006329 |
| geometry action exact | 0.203704 | 0.268519 |
| MIXED complete exact | 0.045455 | 0.090909 |
| teacher raw complete | 0.497890 | 0.497890 |
| teacher raw end-to-end | 0.364979 | 0.373418 |
| 自动接受 / 危险 | 0 / 0 | 0 / 0 |

该结果证明 carrier 与 geometry 共同更新有正收益，但不构成完整目标 A
端到端联合训练：v146 给出的普通 Segment 完整 Road/access 仍是 forward
前已固定的 OOF 条件，v218 无法反向修正它。严格 OOF 的 474 个
AdvanceRight 中，只有 3 个同时满足两侧普通 Segment
`Road set + source + access` 全部正确，且三者均为
`T10:1885118` 的 SWSD_ONLY 对象；其余分解为：

- 217：两侧 source/access 正确，但至少一侧完整 Road 清单错误；
- 129：source 正确，但 Road 清单与 access 至少一项错误；
- 125：source、Road 清单和 access 均未同时正确。

因此 v218 的 0 自动接受不是 geometry 阈值单独造成，而是普通 Segment
完整 Road 清单先把 471/474 个提右对象挡在发布门外。下一训练结构必须让
每侧 ordinary 完整 Road-set head、access proposal head、AdvanceRight
Road bundle 与 geometry recipe 在同一个依赖 forward 中共享梯度；不能把
v218 继续解释为只需调大/调小 `base_loss_weight` 即可收敛。

### v219–v222：普通完整 Road 与 access 父 Road 的角色分离

对 v213 teacher 条件复核发现，502 个 RCSD 侧（313 个不同普通 Segment）
的 T06 access 父 Road不在该普通 Segment 的自有完整 Road 清单内。这不是
标签冲突。以 `T10:1885118 / 606115197_1904806` 为例，原始 RCSD
GPKG 中正式 Road `5384388884629636` 终止于 Node
`5384388884629547`，提右打断父 Road `5384386938798953` 从同一 Node
继续，两者都是独立真实 RCSD Road。模型此前把“挂接证据强”误当成
“Segment 自有”，属于业务角色混淆。

因此 shared side encoder 改为显式输出：

1. `SWSD / RCSD / UNRESOLVED` 数据源；
2. 该来源内的 ordinary 完整 Road 集合及集合大小；
3. 与自有集合分离的 AdvanceRight access/打断父 Road；
4. 锁定前三项后的完整 AdvanceRight plan。

Road 集合 decoder 对已锁定来源执行 hard mask，不能跨 SWSD/RCSD
混选。847/948 个相邻侧具备非空、候选完整可达的 Road-set 监督；
563 个 RCSD 侧具备 access 父 Road强监督；242/474 个 AdvanceRight
同时具备两侧完整 Road/access 监督。teacher/OOF 同为空的侧不再计作
Road-set exact。

| 轮次 | ordinary 初始化/更新 | Road-set exact（847） | source exact（948） | access exact（563） | AR plan exact | 两侧 ordinary exact | 端到端 exact |
|---|---|---:|---:|---:|---:|---:|---:|
| v219 | 仅 474 个 AR 对象从零联合训练 | 0.041322 | 0.857595 | 0.948490 | 0.523207 | 0.006329 | 0.006329 |
| v220 | v142 预训练，全参数同速微调 | 0.096812 | 0.910338 | 0.936057 | 0.544304 | 0.010549 | 0.008439 |
| v221 | v142 预训练 ordinary 冻结，旧未分源 decode | 0.060213 | 0.907173 | 0.948490 | 0.552743 | 0.006329 | 0.006329 |
| v222 | v142 冻结 + 数据源内 Road hard mask | 0.081464 | 0.907173 | 0.948490 | 0.552743 | 0.006329 | 0.006329 |

v219 证明 474 个提右对象不足以从零重学完整 ordinary Road 集合；v220
证明普通 Segment 预训练可迁移，但同一学习率会损伤已有表示；v222
恢复正式数据源门禁后，source/access 已不再是主要误差，完整 Road 清单
仍是决定性瓶颈。全部轮次自动接受为 0、危险自动为 0，正式结论
**NO_GO**。下一步不是继续调整 AdvanceRight/MIXED_SPLICE scorer，而是
用全部普通 Segment 监督预训练 role-aware Road encoder，再以更小的
ordinary 学习率与 access/AdvanceRight/geometry heads 联合微调。

正式工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_advance_right_teacher_geometry_candidates_20260729_v210_parent_piece`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_oof_geometry_candidates_20260729_v211_parent_piece`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_geometry_teacher_student_strict_nested_oof_cuda_20260729_v212_parent_piece_seed_20260812`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_attachment_teacher_view_20260729_v213`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_attachment_oof_view_20260729_v214`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_attachment_teacher_geometry_candidates_20260729_v215_parent_piece`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_attachment_oof_geometry_candidates_20260729_v216_parent_piece`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_geometry_joint_attachment_strict_nested_oof_cuda_20260729_v217_parent_piece_seed_20260817`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_geometry_joint_attachment_strict_nested_oof_cuda_20260729_v218_joint_finetune_seed_20260818`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_separated_strict_nested_oof_cuda_20260729_v219_seed_20260819`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_separated_pretrained_ordinary_strict_nested_oof_cuda_20260729_v220_seed_20260820`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_separated_frozen_pretrained_ordinary_strict_nested_oof_cuda_20260729_v221_seed_20260821`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_masked_frozen_pretrained_ordinary_strict_nested_oof_cuda_20260729_v222_seed_20260821`

### v223–v228：低学习率与同构角色预训练

v223 首先只修正 v220 的同速微调：v142 ordinary decoder 使用主链
`0.1×` 学习率，其余结构、数据源 hard mask 和 strict Case-OOF 不变。
相对冻结 ordinary 的 v222，Road-set exact 从 `0.081464` 提升到
`0.095632`，端到端 exact 从 `0.006329` 提升到 `0.008439`，说明同速
微调确有表示破坏，但降低学习率本身不足以解决完整 Road 清单。

v224 曾把 v175 角色图模型中所有与 set decoder 同名同形的 40 个参数整体
迁移。它虽然张量兼容，但 `graph_context/member/cardinality` heads 原本在
锚定图语境下训练，放入 unordered-set forward 后 Road-set exact 降为
`0.074380`、source exact 降为 `0.833333`。v225/v226 随后只覆盖
`object_encoder/candidate_encoder`；同 seed v226 相对 v223 的 Road-set
仍从 `0.095632` 降到 `0.075561`，5 个 fold 为 4 个退化、1 个持平。
因此 v175 跨结构直接迁移正式淘汰；形状兼容不能替代 forward 语义兼容。

v227r1 改为在与 joint ordinary decoder 完全相同的 unordered-set forward
上，以全部 3,160 个普通 Segment 训练 membership/cardinality，并把
ownership/role 仅作为辅助 loss，禁止反向改写 member logits。专用 set
collator 不再构造模型未消费的 Road×Road/anchor 张量，完整 5-fold nested
OOF 从首版预计超过一小时降至 `487.352s`；首版只完成 fold 0，已移至
`v227_aborted_slow_collator`，不得进入指标。

| ordinary 预训练 | complete exact | Road macro F1 | ownership accuracy | role accuracy | 自动/危险 |
|---|---:|---:|---:|---:|---:|
| v142 set baseline | 0.625712 | 0.821493 | — | — | 797 / 23 |
| v175 anchor-graph role | 0.672785 | 0.854906 | 0.933020 | 0.984289 | 1,047 / 16 |
| v227r1 same-forward role set | 0.610443 | 0.811531 | 0.917958 | 0.978111 | 786 / 20 |

v227r1 的角色头能学习标签，但 ordinary 完整 Road 集合整体相对 v142
退化，因此不能单独作为 ordinary 发布模型。为确认提右依赖子集是否仍有
局部收益，v228 使用与 v223 相同 seed、相同 `0.1×` ordinary 学习率，
只把预训练换成 v227r1：

| joint 指标 | v222 frozen v142 | v223 low-LR v142 | v228 low-LR v227r1 |
|---|---:|---:|---:|
| Road-set exact（847） | 0.081464 | 0.095632 | **0.102715** |
| source exact（948） | **0.907173** | 0.908228 | 0.897679 |
| access exact（563） | 0.948490 | **0.950266** | 0.946714 |
| AR plan exact | **0.552743** | 0.535865 | 0.510549 |
| 两侧 ordinary exact | 0.006329 | 0.010549 | **0.014768** |
| raw end-to-end exact | 0.006329 | 0.008439 | **0.014768** |
| 自动接受 / 危险 | 0 / 0 | 0 / 0 | 0 / 0 |

v228 的 7/474 端到端正确和 `0.102715` Road-set exact 是弱正向结果，但
source、access、AR plan 均有退化，自动覆盖仍为 0，正式结论继续
**NO_GO**。该结果只支持保留“same-forward role-aware pretraining”资产，
不支持继续扫描 role loss 或 AdvanceRight scorer。当前下一瓶颈是大
Road bundle 的数量与结构完整性：需要让普通 decoder 显式表达多 Road
连通组件、主干/内部连接/附属 Road 的集合结构，并在全部普通 Segment
上训练后再接 joint；不能把 v175 图 head 或 T06 终态作为推理输入。

新增正式诊断工件（ignored，不进入 Git）：

- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_masked_low_lr_v142_strict_nested_oof_cuda_20260729_v223_seed_20260822`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_masked_low_lr_role_pretrained_strict_nested_oof_cuda_20260729_v224_seed_20260823`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_masked_low_lr_role_encoder_overlay_same_seed_strict_nested_oof_cuda_20260729_v226_seed_20260822`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_role_aware_set_strict_nested_oof_cuda_20260729_v227r1_fast_set_collator_seed_20260825`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_joint_role_masked_low_lr_same_forward_role_pretrained_strict_nested_oof_cuda_20260729_v228_seed_20260822`

## 2026-07-29～2026-07-30：普通 Segment 结构化集合与提右最终状态条件化

### v229–v234：count head 不足以解决大 Road bundle，结构化扩展形成安全子集

v229 在 ordinary role-aware set 上增加显式 cardinality 预测，但没有改变
逐 Road 集合形成机制，不能解决 10+ Road 复杂 Segment 的完整性。v231/v233
改为 order-free set expansion：每一步在尚未选择的 Road 与 `STOP` 之间决策，
teacher forcing 允许任一剩余真值 Road 作为正确动作，推理期不读取真值基数。
两个独立 strict Case-OOF seed 的结果为：

| 指标 | v231 | v233 |
|---|---:|---:|
| complete/Road-set exact | 0.713291 | 0.707911 |
| 10+ Road support | 146 | 146 |
| 10+ Road exact | 0.184932 | 0.219178 |
| 10+ Road 真值平均基数 | 14.8630 | 14.8630 |
| 10+ Road 预测平均基数 | 9.7808 | 11.3288 |
| 10+ Road 低估基数 | 112 | 96 |

相对 v142/v175/v227r1，结构化扩展显著提高总体完整集合 exact；但大集合仍
主要因提前 `STOP` 和漏选而失败，继续增加普通 cardinality head 或训练 epoch
没有证据。`INTERNAL_CONNECTOR`、`ATTACHED_SWSD` 监督仍极少，不能用总体
role accuracy 宣称这些正式角色已具备跨 Case 泛化。

首次 v234 采用两个独立 seed 的 Road set 交集，但后续完整业务门审计发现，
它使用 `ordinary_decoder_automatic` 重新放行 USE，并把 USE 直接设为
`class_gate_passed=true`。结果中 26/26 个自动 USE 的
`required_anchor_gate_passed=false`，与“锚定是普通 Segment RCSD 替换
前置硬门禁”冲突；同时旧 unsafe 只检查 decision/Road set，没有把逐 Road
ownership 和角色纳入。旧 v234 的“139 自动、零危险”因此废止。

用户确认按方案 A 修正后，v234r1 的推理期发布条件为：

1. KEEP/USE 均须通过独立 required-anchor gate；
2. 只有显式 `inference_no_evidence_proof_passed` 的正向 KEEP 可使用
   无锚定例外；当前预测没有该字段，因此本轮例外数为 0；
3. 两个 seed 必须同时自动，并对业务状态、完整 Road set、逐 Road
   ownership 和业务角色完全一致；
4. 真值只统计 selected business output 的 unsafe/unverifiable，不参与
   自动选择。

v234r1 结果：

- 自动接受 `113/3160`，coverage=`0.035759`；
- 正向 `KEEP_SWSD=113`、`USE_RCSD=0`；
- selected ownership/角色 `113/113` 可评价且正确；
- automatic exact=`1.0`、unsafe/unverifiable automatic=`0`；
- complete exact=`0.713291`、Road macro F1=`0.856067`；
- 两 seed 完整 Road set 分歧 `530`。

因此 ordinary 当前只形成 113 个正向 KEEP 的零危险选择子集；没有普通
USE 通过完整业务门，不能再用 materializer preflight fallback 把错误放行
解释为安全模型决定。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_count_aware_role_set_strict_nested_oof_cuda_20260729_v229_seed_20260826`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_set_expansion_frozen_encoder_strict_nested_oof_20260729_v231_full_seed_20260827`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_set_expansion_frozen_encoder_strict_nested_oof_20260729_v233_full_seed_20260828`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_set_expansion_two_seed_release_gate_20260730_v234r1`

### v235–v240：以 ordinary 最终 access 状态条件化 AdvanceRight

v235r1 对 51MB AdvanceRight feature store 单次流式读取，并把 ordinary
OOF 预测建立一次索引；未改变的 feature/teacher/label 文件使用 hardlink，
避免按对象重复读取和复制。948 个相邻侧中，667 个能 join ordinary OOF
预测；281 个预测缺失，其中 80 个侧没有 owner/road candidate，只能保持
局部 fallback。最终状态统计：

- final-state ready 侧 `868/948`；
- final-state ready AdvanceRight `434/474`；
- `FALLBACK_SWSD=943` 个侧；
- `POSITIVE_KEEP_SWSD=5` 个侧；
- 当前没有自动 `USE_RCSD` 相邻侧。

该条件层显式区分正向 KEEP 与 fallback SWSD。fallback 恢复冻结 T01
Segment 的完整 SWSD Road 集合；SWSD access Road 必须是该集合中与冻结
T01 access Node 相接的 Road。模型自动 `USE_RCSD` 若尚未给出神经网络
attachment，则保持 access pending，不用后处理补造。

v236r1 暴露旧目标顺序错误：46 个两侧最终已是完整 SWSD 的对象仍沿用
fallback 前的 formal RCSD/Review 目标，造成 13 个 Review 自动项。v237
修正为先评价锁定后的两侧最终状态：两侧完整 SWSD、access 有效、可达且
materializer ready 时，条件方案就是 `SWSD_ONLY`。这不是把 fallback
伪装成正向真值，而是按已确认业务顺序重新执行 AdvanceRight 条件决策。

两个独立 strict OOF seed 的安全结果：

| 指标 | v237 | v239 |
|---|---:|---:|
| 自动接受 | 416 | 430 |
| automatic coverage | 0.877637 | 0.907173 |
| automatic/plan exact | 1.0 | 1.0 |
| unsafe automatic | 0 | 0 |
| REVIEW_FALLBACK 自动接受 | 0/40 | 0/40 |

两个 seed 的方案分歧为 0。v240 不平均分数，只接受两 seed 同时自动且完整
方案一致的交集，得到：

- 自动接受 `414/474`，coverage=`0.873418`；
- automatic exact、candidate acceptable exact、plan type exact 均为 `1.0`；
- unsafe automatic=`0`、fold mismatch=`0`、plan disagreement=`0`；
- 414 个自动结果全部为正向 `SWSD_ONLY`；
- 40 个 `REVIEW_FALLBACK` 对象全部拒绝自动发布。

v240 是“ordinary 最终状态已锁定后的 SWSD-only AdvanceRight 条件路径”
局部 PASS，不是完整 AdvanceRight PASS。由于当前相邻侧没有自动 RCSD，
该轮没有评价 `RCSD_ONLY` 或 `MIXED_SPLICE` 的推理期自动能力。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_advance_right_final_ordinary_state_conditioning_20260730_v235r1`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_final_state_teacher_student_strict_nested_oof_cuda_20260730_v237_seed_20260829`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_final_state_teacher_student_strict_nested_oof_cuda_20260730_v239_seed_20260830`
- `outputs/_work/p05_neural_road_generation/target_a_advance_right_final_state_two_seed_release_gate_20260730_v240`

### v241r1：最终状态 materializer 审计

v241r1 将 v234r1 ordinary 与 v240r1 AdvanceRight 的正式双种子输出送入现有
T01 fallback materializer。对已接受 `SWSD_ONLY`，只把同一个已验证 T01
fallback recipe 从 `ABSTAIN/fallback_applied=true` 重分类为
`KEEP_SWSD/fallback_applied=false`；Road、Node、attachment 和几何内容
完全不改变。结果：

- 51 Case、8,863 个冻结 Segment；
- 8,818 个 Segment 可物化，45 个保留既有 T01/source blocker；
- 414 个 AdvanceRight 自动请求全部物化，coverage=`1.0`；
- 正向 ordinary KEEP=`113`；
- ordinary USE=`0`、preflight fallback=`0`；
- 输出 Road=`14,193`、Node=`12,745`、attachment=`868`；
- hard failure、skeleton mutation、silent fix、content repair 均为 0；
- source unusable Road=`8`，只保留在直接对象阻断中，不扩张 T01 依赖闭包。

修正门禁后的完整 P05 回归见本轮最终审计。v241r1 证明当前被接受子图可以
安全执行，但不证明 51 Case 全部冻结骨架均有可发布自动结果，也不证明
Target A 已替代完整 T03–T06。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_final_state_two_seed_materializer_audit_20260730_v241r1`

### v243–v247：结构化扩展与完整方案选择

v243r2 在 fold2 使用 access seed、端点 frontier teacher forcing、16 个
prefix state 和 inner-only STOP bias。相对同 seed v233，overall exact 从
`0.681287` 提升到 `0.690058`，Road macro F1 从 `0.841178` 提升到
`0.846755`；但 10+ Road exact 仍为 `3/16`。STOP bias
`-0.25/0/0.25/0.5/0.75/1.0` 没有改变 outer 结果，证明剩余问题不是一个
全局停止阈值。

v244 首次实现显式 `CONTINUE_FRONTIER/START_COMPONENT/STOP`，但把 access
seed 错误实现为 START 的硬候选裁剪，导致训练 loss 为 `Infinity`；该工件无效，
后续指标不得引用。v244r1 将 access seed 恢复为网络证据、允许模型选择所有
START Road，并增加 non-finite loss 硬失败。有效 fold2 结果为：

| 指标 | v243r2 | v244r1 |
|---|---:|---:|
| complete/Road-set exact | 0.690058 | 0.701754 |
| Road macro F1 | 0.846755 | 0.847126 |
| 10+ Road exact | 3/16 | 2/16 |
| 10+ Road 低估/过估 | 3/6 | 5/8 |
| 零危险自动覆盖 | 92/342 | 92/342 |

因此三动作 decoder 改善普通样本，但没有改善长 Road bundle，不扩完整 OOF。

v245 不读取真值生成 KEEP/USE 完整 Road beam；真值只在全部方案生成后做
oracle reachability。结果：

| Beam 宽度 | overall oracle exact | 10+ Road oracle exact |
|---:|---:|---:|
| 1 | 0.707602 | 1/16 |
| 4 | 0.830409 | 3/16 |
| 8 | 0.865497 | 6/16 |
| 16 | 0.897661 | 7/16 |
| 32 | 0.923977 | 7/16 |

这证明当前模型已能为大多数普通 Segment 提出正确完整方案，但 oracle 不等于
推理选择能力。v246 在 folds 0/1/4 训练、fold3 early stopping/安全阈值、
fold2 测试，使用 32D 方案摘要：raw exact=`0.701754`、10+ Road=`2/16`；
零危险自动接受 `113/342=0.330409`，高于 v244r1 的 `92/342`，但没有利用
oracle 提升 raw exact。v247 加入 graph context、方案内/外 Road embedding
mean/max 后，fold2 raw exact 退化为 `0.611111`、10+ Road=`0/16`、零危险
覆盖=`0.195906`；高维表示对 inner Case 有效但跨 Case 过拟合，路线停止。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_frontier_expansion_strict_nested_oof_cuda_20260730_v243r2_stop_bias_fold2_seed_20260828`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_component_action_strict_nested_oof_cuda_20260730_v244r1_fold2_seed_20260828`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_component_action_beam_oracle_20260730_v245_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_beam_reranker_canary_20260730_v246_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_embedding_beam_reranker_canary_20260730_v247_fold2`

### v248–v255：关系方案比较、指标拆分与锚定上限

v248 使用 case-invariant 关系摘要，fold2 raw exact=`0.698830`、
10+ Road exact=`2/16`、零危险自动覆盖=`107/342=0.312865`；没有超过
v246。v249 将 ownership、角色、access、端点关系写成可解释结构化能量，
raw exact 提高到 `0.716374`，但 10+ Road 仍为 `2/16`，并出现
unsafe automatic=`1`，不能作为安全发布方案。

v250 将 v245、v248、v249 等 truth-free 方案视图做候选并集，只以真值执行
离线 oracle 审计：overall oracle exact=`311/342=0.909357`，
10+ Road=`7/16`。这说明多视图能覆盖更多正确方案，但长集合仍有 `9/16`
不可达，且 oracle 不能进入推理输入。

v251/v252 训练 same-plan affinity，outer pair F1 仅为
`0.1444/0.1527`，最终 raw exact=`0.684211/0.690058`。v253 删除候选
绝对 embedding，只保留 Road–Road 关系和对称信号后，outer pair F1 提高到
`0.654739`；但 inner 选择的完整方案权重为 0，最终仍回到 v249。
因此关系证据具备跨 Case 泛化能力，但“独立二分类 Road 是否同方案”不是完整
Road 清单的有效训练目标。

v254/v255 改为 listwise complete-plan loss，真值只用于 acceptable-set
损失，不进入特征，并通过 Road 顺序不变性测试。复核时发现旧的 raw exact
把“正确识别 beam 中没有有效方案并 ABSTAIN”与“选中正确 carrier 方案”
合并统计，现已拆分：

| 版本 | 参数量 | raw exact（含安全 ABSTAIN） | reachable-plan exact | 10+ Road reachable exact | 零危险自动覆盖 |
|---|---:|---:|---:|---:|---:|
| v254 scalar pairwise | 3,499 | 0.780702 | 241/306=0.787582 | 1/7 | 90/342=0.263158 |
| v255 residual relational | 9,704 | 0.757310 | 239/306=0.781046 | 2/7 | 97/342=0.283626 |

两者 unsafe automatic 均为 0，但高 raw exact 主要包含对 unreachable 样本的
安全 ABSTAIN；它们没有超过 v249 的 reachable 方案排序，也没有超过 v246
的零危险覆盖。因此不得把 v254/v255 解释为 ordinary carrier 已收敛。

进一步把 v250 多视图 oracle 与当前 v189 锚定硬门禁相交，得到当前链路的
fold2 理论上限：

| 范围 | 样本数 | anchor ready | 多视图可达 | 两者同时成立 |
|---|---:|---:|---:|---:|
| ALL | 342 | 231/342=0.675439 | 311/342=0.909357 | 214/342=0.625731 |
| KEEP_SWSD | 160 | 94/160=0.587500 | 160/160=1.000000 | 94/160=0.587500 |
| USE_RCSD | 182 | 137/182=0.752747 | 151/182=0.829670 | 120/182=0.659341 |

即使方案 decoder 完美，在当前锚定输出下也最多自动覆盖 `62.57%`，低于
Target A 的 `80%` 目标。当前 v108 锚定模型 fold2 的 gate accuracy 为
`0.936634`，但 concrete anchor object acceptable exact 只有 `0.747748`；
后续 v112/v113 的共享 gate 主要学习“是否 resolved/是否 fallback”，没有让
ordinary carrier loss 反向训练具体锚定候选表示。下一步不能继续单独优化
decoder，必须构建 Case 级 combined batch：同一 forward 编码 SWSD 语义路口
锚定候选和 ordinary 完整 Road 方案，允许两个任务共享 encoder；推理时锚定头
仍独立确定唯一锚定对象，carrier 不得替它选择或绕过硬门禁。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_relational_beam_reranker_canary_20260730_v248_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_structured_energy_canary_20260730_v249_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_multi_view_beam_oracle_20260730_v250_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_same_plan_affinity_canary_20260730_v251_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_gated_same_plan_affinity_canary_20260730_v252_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_relational_same_plan_affinity_canary_20260730_v253_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_pairwise_plan_decoder_canary_20260730_v254_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_residual_pairwise_plan_decoder_canary_20260730_v255_fold2`

## v256–v265：同一 forward 的锚定—ordinary 联合训练与监督缺口

### 业务子图和 I/O

v256 首先按实际城市/Case 数据审计 forward 边界。19 个共享 Case 中，
最大完整 Case 含 1,628 个锚定对象和 1,555 个 ordinary Segment；若把共享
Road/Node/Junction 关系做传递闭包，最大连通组达到 3,117 个对象，违背已确认
的“Segment/Junction 阻断连锁反应”业务边界。

正式实现因此改为一个普通 Segment 为 focal object，只带：

1. 该 Segment 的全部 required SWSD semantic anchors；
2. 每个 required anchor 的一跳直接锚定依赖；
3. 同一 Segment 的完整 Road plan 候选。

空间切片只用于查询，未截断上述业务依赖。4,196 个可构建子图的对象数
P95/max 为 `14/47`；31 个普通 Segment 缺少任何 required anchor，保持局部
fallback。anchor feature、plan candidate、plan label 三个 store 各读取一次，
后续在内存中 join、分组和 padding，未按 Segment 重复读取城市文件。

### v257r3：真实共享 encoder canary

首两次 v257 运行在 validation 出现 NaN。定位到通用
`acceptable_set_nll`：有候选但未监督的 context anchor 会得到 `inf`，
之后再乘零 mask 形成 NaN。修正后，无监督候选行 loss 为 0，监督行语义不变；
v257r3 完整训练成功。

结构约束：

- ordinary query 只能读取 anchor；ordinary 对象不能向 anchor 发送消息；
- 相同 anchor 在不同 focal Segment 中的 status/candidate prediction 必须一致；
- teacher forcing 只在训练 carrier 时锁定已标注的唯一 anchor；free run 物理
  移除全部 teacher choice；
- carrier loss 可经共享 encoder 更新 anchor candidate evidence，但不能改写
  anchor head 的离散选择和发布门。

v257r3 outer fold2：

| 指标 | 结果 |
|---|---:|
| 参数量 | 18,415,507 |
| 唯一 anchor / candidate-supervised | 500 / 277 |
| concrete anchor object exact | 210/277=`0.758123` |
| anchor prediction inconsistency | 0 |
| ordinary count / anchor truth ready | 603 / 212 |
| all-plan exact（重数 prediction JSONL） | 533/603=`0.883914` |
| free-plan exact（ready 分母） | 172/212=`0.811321` |
| 安全自动正确覆盖 | 23/603=`0.038143` |
| unsafe automatic | 0 |
| Review automatic | 1 |

唯一 Review 自动项为 `T10:605415675 / 860484_513632104`：plan 为正确
`KEEP_SWSD`，但 required anchor `860484` 的现有标签仅是
`relation_record_absent`，不能视为成功、失败或无证据。故 v257r3 为
`CASE_JOINT_FOLD_CANARY_NO_GO`。

### v258/v259：compatibility 路线停止

- v258r1 让 anchor-plan compatibility 直接修改方案 logits：
  anchor exact=`0.765343`，all-plan exact=`0.830846`，自动正确
  `7/603`；相对 v257r3 明显降低完整方案选择。
- v259 只保留 compatibility auxiliary loss：
  anchor exact=`0.761733`，all-plan exact=`0.815920`，自动正确
  `4/603`。

两者 unsafe/review 为 0，但没有改善主要目标；compatibility 不再继续调参。

### v260r1/v262：正向 NO_EVIDENCE KEEP 与安全校准

v257r3 的 ready 定义遗漏了已确认业务例外：只有正式证明
`NO_EVIDENCE` 时，普通 Segment 可以在没有具体 RCSD anchor 对象的情况下
正向输出 `KEEP_SWSD`。修正后：

- 训练时，acceptable plan 含 `KEEP_SWSD`，且每个 required anchor 均为
  唯一 `SUCCESS` 或有监督 `NO_EVIDENCE`，carrier task 才可进入 loss；
- 推理时，`USE_RCSD` 仍要求全部 required anchors 唯一 `SUCCESS`；
- `relation_record_absent` 仍是未知，不能进入正向 KEEP；
- 无证据证明只影响 KEEP，不为 USE 放宽 anchor。

v260r1 的 outer ready 从 `212/603` 增至 `235/603`，all-plan exact=
`522/603=0.865672`，free-plan exact=`184/235=0.782979`。但只按
NO_EVIDENCE status 概率做 inner-only 零假阳阈值时，outer anchor `1614138`
被误判为 NO_EVIDENCE；该对象实际有 candidate-supervised SUCCESS，且模型
选中的 `ROAD:5391284588189652` 候选本身正确。对应 Segment
`1614138_1636205` 被错误自动 KEEP，unsafe automatic=`1`。

v262 不重训，复用 v260r1 两个 checkpoint，把无证据置信度定义为：

`min(P(NO_EVIDENCE), 1 - P(unique-anchor gate success))`

两个阈值仍只由 inner validation 选择。结果：

| 指标 | v260r1 | v262 |
|---|---:|---:|
| outer all-plan exact | 0.865672 | 0.865672 |
| outer ready free-plan exact | 0.782979 | 0.782979 |
| concrete anchor exact | 0.747292 | 0.747292 |
| base releasable | 160 | 208 |
| 自动正确 | 5 | 5 |
| unsafe / Review | 1 / 0 | 0 / 0 |
| 自动正确覆盖 | 0.008292 | 0.008292 |

v262 消除了危险项，但覆盖仍只有 0.83%，判定
`CASE_JOINT_RECALIBRATION_NO_GO`。不能把安全校准成功解释为联合模型 GO。

### v263/v264：监督缺口转成人工裁决输入

fold2 的 500 个唯一 required anchors 中，有 198 个缺少 status 或具体
candidate 对象真值，影响 356/603 个普通 Segment。当前模型已有 56 个此类
anchor 进入未验证 release 候选；全局安全阈值必须阻断它们，这也是覆盖骤降
的直接原因之一。

v263 生成完整 198 条队列及 Phase 1 的 30 条优先队列。Phase 1 全部来自
`T10:605415675`，覆盖 91 个受影响 Segment。允许的人工结果严格限定为：

- `SUCCESS_UNIQUE`：从现有 candidate IDs 中选一个唯一 Node 或 Road bundle；
- `PROVEN_NO_EVIDENCE`：必须有正式证据证明没有 RCSD 锚定证据；
- `AMBIGUOUS`：多候选或证据不足，Segment fallback；
- `CANDIDATE_MISSING`：正确对象不在候选集合，不得发明 ID 或让 carrier
  代选。

v264 将 Phase 1 打包为只读 EPSG:3857 GeoPackage：

| 图层 | 数量 |
|---|---:|
| SWSD semantic anchors | 30 |
| impacted frozen T01 Segments | 91 |
| RCSD candidate Nodes | 187 |
| RCSD candidate Roads | 338 |

几何原样复制；topology changed=`false`、silent fix=`false`，所有请求对象均
找到。该包只供人工裁决，不回写 T01–T12。

### v265：已有锚定真值严格复用审计

为避免重复人工工作，v265 将 v263 的 198 个待裁决对象与 v117 已装载的
T03/T04 正式重放和 T11 人工标签逐对象核对。自动继承必须同时满足：

1. 同一 SWSD semantic anchor；
2. 推理输入哈希一致；
3. candidate IDs、局部结构对象和结构证据一致；
4. 来源真值已监督且不存在冲突。

空间近邻、模型预测和仅 anchor ID 重名均不得作为继承依据。审计结果：

| 项目 | 数量 |
|---|---:|
| v263 全量待裁决 | 198 |
| Phase 1 待裁决 | 30 |
| T03/T04/T11 跨样本严格复用 | 0 |
| Phase 1 跨样本严格复用 | 0 |
| 已有 T11 真值证明 candidate missing | 1 |
| 全量剩余待裁决 | 197 |
| Phase 1 剩余待裁决 | 30 |

唯一已有真值命中为 `T10:605415675 / 12833355`。T11 人工记录选择
`ROAD:5384391266669010`，而该对象不在冻结 candidate IDs；因此只能固化为
`CANDIDATE_MISSING -> Segment fallback`，不得转成 `NO_EVIDENCE`、
`KEEP_SWSD` 或成功锚定。该对象位于原队列第 198 位，不属于 Phase 1，
所以当前最优先的 30 条人工范围不变。

### Phase 1 label-only 回填管线

人工结果返回后的处理链路已提前实现，不需要再修改训练输入结构：

- CSV 必须与 v263 Phase 1 JSONL 一一对应，除
  `manual_decision/manual_selected_candidate_id/manual_evidence_note` 外，
  所有冻结列必须逐值一致；
- `SUCCESS_UNIQUE` 必须原样选择 `candidate_ids` 中的一个完整候选；Road
  bundle 内部的 `|` 是候选身份的一部分，不按单 Road 拆分；
- `PROVEN_NO_EVIDENCE`、`AMBIGUOUS`、`CANDIDATE_MISSING` 禁止填写候选，
  所有四类裁决均要求可审计的 evidence note；
- 输出只重写 training label store，inference feature store 必须 SHA256
  字节一致；
- `AMBIGUOUS/CANDIDATE_MISSING` 写为显式失败 gate 和 Segment fallback；
  `PROVEN_NO_EVIDENCE` 只允许正向 KEEP，不为 USE 放宽 required anchor；
- 任一 required anchor 已明确失败时，Segment 立即 fallback；即使同一
  Segment 的其他 required anchor 尚未裁决，也不得继续 carrier。

空白正式模板已用 `require_complete=false` 验证 30 条作用域和所有冻结列，
完成行数为 0；这只证明模板可读，未把空白行写入标签。定向合同测试
`14 passed`，完整 P05 回归 `643 passed, 1 warning`。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_case_joint_anchor_carrier_canary_20260730_v257r3_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_case_joint_anchor_carrier_canary_20260730_v258r1_compatibility_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_case_joint_anchor_carrier_canary_20260730_v259_aux_compatibility_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_case_joint_anchor_carrier_canary_20260730_v260r1_no_evidence_keep_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_case_joint_anchor_carrier_recalibration_20260730_v262_gate_consistent_no_evidence_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_anchor_adjudication_queue_20260730_v263_fold2`
- `outputs/_work/p05_neural_road_generation/target_a_existing_anchor_truth_reuse_audit_20260730_v265_fold2`

### 当前结论与下一收敛目标

当前总体结论仍是 **TARGET_A_OVERALL_NO_GO**：

1. 已收敛并通过双 seed/物化门的是 `SWSD_ONLY` AdvanceRight 条件路径；
2. ordinary 完整 Road set 有明显表达提升，但完整业务门安全覆盖仅 `3.58%`，
   且当前全部为正向 KEEP；
3. access/frontier 训练已显著减少 10+ Road 漏选，但过选同时出现；当前失败
   不是单一 STOP 阈值。beam oracle@16 已到 `7/16`，剩余瓶颈包含完整方案
   排序和 9/16 候选仍不可达两部分；
4. ordinary `USE_RCSD` 的完整 access/Node/几何 recipe 尚未进入正式发布；
5. `RCSD_ONLY`、`MIXED_SPLICE`、Clue/scope 和完整 RoadGraph exact 尚未通过。

下一轮冻结 v240r1/v241r1，不再扫描局部 AdvanceRight scorer，也停止把
ordinary decoder 当作独立瓶颈继续调参。训练资源转入 Case 级 combined batch：
SWSD 语义路口锚定候选与普通 Segment 的 access/主干/内部连接/附属 Road
完整方案共享 encoder，锚定头保持独立硬门禁；继续以 concrete anchor object、
完整 Road set、角色、所有权、access、Node、方向、拓扑和零危险自动替换联合
验收。

## 2026-07-30 v309–v325：联合模型独立 validity 头

v309 在不修改 T03–T06 推理接口的前提下重算修正后的锚定监督，完整 OOF
concrete candidate exact=`0.846594`、status accuracy=`0.926750`、
gate accuracy=`0.949467`。这证明锚定对象、状态和可发布门具有可学习信号，
但原始置信度仍不能直接满足零危险发布。

v313 将锚定、ordinary 完整 Road 方案、Road member/arm 与分层 business
decision 放入同一约 20.60M 参数 forward。fold2 all-plan exact=
`0.930348`、free-run exact=`0.880851`，说明联合 encoder/结构化 decoder
显著优于早期局部 scorer；但严格门仅自动接受 14 条，覆盖 `2.32%`，
且没有自动 `USE_RCSD`，仍为 NO_GO。

v315–v319 依次验证单一 risk MLP、anchor/plan 双通道线性 head、二维
零危险阈值、显式 decision logits 和 Case 内相对 percentile。所有路线在
inner 可找到少量零危险样本，但 outer fold 因概率尺度漂移或每个 Case
最高分仍含错误而接受 0 条。由此停止继续做纯 posthoc calibration；后续
安全信号必须进入联合网络并接受独立监督。

v320 新增独立 `ordinary_plan_validity_head`，排序 logits 与候选是否属于
acceptable set 的 BCE 不再共用同一输出。参数量为 22,592,341。单 fold
诊断中，按 inner 的 plan-only 零错误阈值，outer 可接受 `89/235` 条且
plan error=`0`；但全部为 KEEP，锚定错误仍有 30 条。v321 补齐四个 inner
fold 后，Case/decision percentile 的 outer plan-only 零错误接受为
`55/235`，仍没有 USE；某些 inner Case 的最高分 USE 本身错误，故严格
跨折阈值不可发布。

v322 将 plan validity loss 从 `0.5` 提高到 `2.0`。fold4 USE 零错误安全
前缀由 `1/113` 提升到 `52/144`，证明独立 validity 监督有效；稀有
`INTERNAL_CONNECTOR` Case 仍未选对，但已从 USE 排名第 1 降到第 53。
v323 增加显式 business-decision softmax loss，outer plan exact 提升至
`0.872340`，但一个错误 USE 仍被高置信接受。

v324 再新增独立 `ordinary_decision_validity_head`，把“选择 KEEP/USE”
与“所选状态是否可安全接受”物理分头。模型参数量 24,579,734，低于 25M
门限；outer complete-plan exact=`0.880851`，独立 decision-validity 的
USE 零错误前缀为 `36/81=44.44%`，plan+decision 联合前缀为
`33/81=40.74%`。这是当前最强 USE 安全排序信号，但尚未达到每 fold 50%
研究 GO。

v325 对 fold0/1/3 warm-start 微调并复用 v324 fold4/outer。四个 inner
fold 合计 truth-ready 2,040 条，complete-plan exact=`0.888235`；
outer 235 条 exact=`0.880851`。outer KEEP/USE 的零错误联合前缀分别为
`95/154=61.69%` 和 `33/81=40.74%`。但 inner USE 安全前缀分别为：

| fold | USE ready | 零错误安全前缀 | 覆盖 |
|---:|---:|---:|---:|
| 0 | 352 | 0 | 0.00% |
| 1 | 245 | 1 | 0.41% |
| 3 | 98 | 11 | 11.22% |
| 4 | 140 | 43 | 30.71% |

fold0/fold1 的最高分错误使跨折 USE 阈值仍高于 1，v325 判定
`DECISION_PLAN_VALIDITY_CANARY_NO_GO`。当前不能用 outer2 的 40.74%
替代逐 fold GO，也不能把 plan-only 正确解释为锚定与最终 RoadGraph 已安全。

当前最影响阈值、且现有标签均为权重 0.7 的人工核查项为：

1. `T10:1885118 / 1881754_1898462`：现真值只含
   `5388762134481242`；模型增加 `5388826593329198`。
2. `T10:605415675 / 500861744_600275542`：现真值为
   `KEEP_SWSD Road 524187094`；模型选择 RCSD
   `5395950500446909 + 5395950500446992`。
3. `T10-Error-2:986209_996008_1 / 986209_996008_1`：现真值为两条
   MAIN 加两条 `INTERNAL_CONNECTOR`，模型只选两条 MAIN。该条属于目录名
   对应 Segment 的可靠 Error 标签，除非人工发现真值本身错误，否则继续按
   connector 完整性错误处理。

本轮推理 feature 未读取 acceptable/preferred/plan correctness 等 label-only
字段；outer label access during fit=`0`。独立 plan/decision validity 结构、
warm-start 和风险特征合同的 Target A 全量专项回归为
`418 passed, 1 warning`。当前工件：

- `outputs/_work/p05_neural_road_generation/target_a_separate_plan_validity_canary_20260730_v320_fold2_seed_20260801`
- `outputs/_work/p05_neural_road_generation/target_a_cross_fitted_plan_validity_canary_20260730_v321_fold2_seed_20260811`
- `outputs/_work/p05_neural_road_generation/target_a_stronger_plan_validity_canary_20260730_v322_fold4_seed_20260821`
- `outputs/_work/p05_neural_road_generation/target_a_warm_decision_validity_canary_20260730_v323_fold4_seed_20260831`
- `outputs/_work/p05_neural_road_generation/target_a_warm_separate_decision_validity_canary_20260730_v324_fold4_seed_20260901`
- `outputs/_work/p05_neural_road_generation/target_a_cross_fitted_decision_validity_canary_20260730_v325_fold2_seed_20260911`

## 2026-07-30～2026-07-31 v326–v350：T05 监督修正、结构化锚定与只降级安全门

v326r2 修正 T05 锚定来源映射后，v327 以 24,579,734 参数完成 fold2
全量重训。v336 将 `NO_EVIDENCE`、唯一成功锚定和失败/歧义按正式三态门禁
重算：free-plan exact=`0.855932`、concrete anchor exact=`0.801444`，
自动候选 22 条，其中 21 条正确、1 条危险，自动正确覆盖
`21/605=0.034711`，truth-ready 覆盖 `21/236=0.088983`。唯一危险项为
`T10:605415675 / Segment 1633165_512279283`：ordinary plan 的
`KEEP_SWSD` 正确，但 required anchor 错选附近 RCSD Node
`5391330021350570`。

用户随后确认，对 SWSD semantic Junction `1633165`，唯一正确锚定是以下
六条 RCSD Road 的 road-only split；上述 Node 不可接受：

- `5391329551450177`
- `5391329551450189`
- `5391329551450260`
- `5391329551450265`
- `5391330021350944`
- `5391330021350949`

v339 将该真值以权重 `1.0` 写入 label-only store，推理 feature store
保持不变。v340 复算后危险项仍存在，证明这是模型泛化错误，不是多解标签
或旧真值错误。

v342–v346 将问题从候选级重新拆成“RCSD 证据角色 + Node/Road 类型 +
cardinality + 原子成员集合”：

- v342 的聚合统计 relation/type exact=`0.697842/0.894886`，不能表达
  object-level 结构；
- v343 的原子 set + raw topology decoder 为 814,348 参数，outer
  relation/type exact=`0.726619/0.900568`、member exact=`0.688761`、
  macro F1=`0.770239`；1633165 已正确判为 `B /
  rcsd_present_not_junction` 和 Road，但 cardinality 预测 1；
- v344 ordinal cardinality outer exact=`0.858790`、member exact=
  `0.703170`、macro F1=`0.773474`。1633165 在强制真值 cardinality=6
  时，member ranking 恰好选中六条完整真值 Road，说明成员排序正确，
  错误集中在长尾数量解码；
- v345/v346 的 singleton-vs-multi 与 relation/type 条件阈值仍未使
  1633165 跨过 inner-only 阈值，停止为单个 outer Case 下调阈值。

v347 首次只使用推理期输出比较 release cardinality 与 expected-floor
cardinality。规则只允许把已有自动候选降级为 `ABSTAIN`，不能修改锚定、
carrier、候选、T01 骨架或 fallback 作用域。对 v340 的 22 个自动候选，
接受 21 个且 21/21 正确，唯一拒绝项正是 1633165。

随后把实验结构固化为正式 P05 组件：

- `target_a_anchor_structural_decision.py`：共享 object embedding adapter、
  原子 Node/Road set、arm 摘要、raw topology message passing、正式
  relation/type/exact+ordinal cardinality/member heads、候选类型 hard
  mask 和只降级门禁；
- `target_a_anchor_structural_training.py`：训练 label 与推理 batch 物理
  分离，relation 与 member task mask 独立，多解类型、数量和完整成员集合
  使用 acceptable-set loss；
- v348r2 正式 decoder 为 794,892 参数，outer relation exact=
  `0.841727`、type exact=`0.900568`、member exact=`0.685879`、
  member macro F1=`0.777820`；
- 加入“不可选择候选集中不存在的对象类型” hard mask 后，v349r1 的
  ordinal cardinality outer exact=`0.832853`、member exact=`0.688761`、
  macro F1=`0.783146`。1633165 仍为正确 relation/type 和正确六 Road
  排序，但 release cardinality=`1`；
- v350r1 以正式组件重算：1633165 expected-floor cardinality=`4`，
  因 `1 != 4` 降级；22 个自动候选接受 21 个，21/21 正确、危险 0，
  保留率 `0.954545`，结果为 `GO_FORMAL_SAFETY_GATE`。

相关定向回归为 `73 passed`，完整 P05 回归为
`697 passed, 1 warning`。v350r1 只证明当前 22 个自动候选上的门禁集成
成立，不改变 Target A 整体 **NO_GO**：总体/USE 覆盖仍远低于研究 GO，
ordinary USE 完整执行、AdvanceRight RCSD_ONLY/MIXED_SPLICE 和最终
RoadGraph exact 尚未收敛。

## 2026-07-31 v351：Case-joint 共享 embedding 结构锚定集成

v351 将独立结构 decoder 接到 v327 的共享 object embedding，并在同一
Case-joint forward 中联合训练 relation、Node/Road 类型、exact/ordinal
cardinality、member set 和低权重 ordinary loss。推理 batch 不含
relation/member 真值；Case batching 的 padded anchor 只编码有效组，
inactive task 允许权重 0，训练与评估均保留同一套原子 member、arm 和
topology evidence。参数量为 `24,926,558`，低于 25M 门限。

v351r5 fold2 结果：

| 指标 | v351r5 |
|---|---:|
| ordinary free-plan exact | `0.868644` |
| ordinary all-plan exact | `0.902479` |
| concrete anchor object exact | `0.797834` |
| relation exact | `0.727901` |
| Node/Road type exact | `0.893274` |
| member exact | `0.779821` |
| member macro F1 | `0.810189` |
| 自动候选 | `20` |
| 自动正确 / 危险 | `19 / 1` |

member exact 相对 v348r2 提升，但 relation/type 退化。1633165 被判为
`rcsd_present_not_junction + NODE + cardinality 1`，错选
`NODE:5391330021350570`；threshold 与 expected-floor cardinality 同为 1，
所以仅靠 cardinality disagreement gate 无法阻断。与 v350r1 做交集时，
19 条共同接受全部正确，唯一危险项被 v350 拒绝；这只恢复安全，不增加
覆盖。

训练分布审计排除了“缺少同类标签”：outer fold2 训练范围有 426 条
`B + ROAD + 多 Road`，其中 27 条 cardinality=6。对照 v348r2 使用原始
64D anchor evidence 可正确判定 1633165 为 `B + ROAD`，v351 只通过共享
embedding 后退化为 Node。因此下一轮不再让 ordinary loss 直接改写锚定
语义表示；保留原始推理期锚定证据分支和 v350 只降级门禁，把其 immutable
proposal 作为下游 decoder 的条件输入。v351 判定
`CASE_JOINT_STRUCTURAL_ANCHOR_CANARY_NO_GO`，Target A 总体仍为 NO_GO。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_case_joint_structural_anchor_canary_20260731_v351r5_fold2_seed_20261081`

本轮修正后的完整 P05 回归为 `700 passed, 1 warning`。

## 2026-07-31 v352–v354：冻结原始锚定 teacher 的下游条件化

v352 把 raw-evidence 结构 teacher 从 794,892 参数压缩到 324,108 参数。
fold2 relation/type exact=`0.784173/0.872159`、member exact=`0.648415`，
总体指标低于 v348r2，不能单独晋升；但 1633165 首次同时得到
`B + ROAD + cardinality 6 + 六 Road exact`。该结果说明原始 64D anchor
evidence、原子 member、arm 和 topology edge 能保留 v351 共享 embedding
丢失的关键判别，同时参数足以与 v327 组合后维持 25M 门限。

v353r3 使用 324,108 参数 teacher 和 v327 checkpoint，冻结 teacher、
anchor/base encoder 与全部 ordinary heads，只训练新增的 25,696 参数
ordinary anchor-condition stem。条件输入由每个 required anchor 的原始
64D object evidence，加 relation 三态概率、Road 类型概率、期望
cardinality 和 relation confidence 六维摘要组成；训练期 carrier loss
不能进入锚定分支。固定训练 2 轮，不使用 outer 指标选 epoch。结果：

| 指标 | v327 | v353r3 |
|---|---:|---:|
| 参数量 | `24,579,734` | `24,929,538` |
| free-plan exact | `0.855932` | `0.881356` |
| all-plan exact | — | `0.917355` |
| concrete anchor exact | `0.801444` | `0.801444` |
| anchor inconsistency | `0` | `0` |

因此冻结条件化结构判定 `GO_FROZEN_CONDITION_INTEGRATION`：它提高 ordinary
完整方案选择，同时没有让 carrier 反向改变锚定输出。

v354 只读重放 v353r3，并叠加 v350r1 正式锚定门。迁移 v351 的 inner-only
release threshold 时，原始 v353 候选为 26 条，含 1 unsafe 和 1 Review；
锚定门最终接受 24 条且 24/24 正确，全部为 KEEP，比 v350 的 21 条安全
接受增加 3 条。outer 真值可见的零危险上限为 34 条，其中 KEEP 30、USE 4，
但该阈值 `0.997352` 使用 outer truth，只能证明可达，不能发布。下一步必须
为冻结条件化结构训练严格 inner checkpoint 并从 inner 单独选择 release
threshold；当前结论仍是 Target A 总体 NO_GO。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_small_raw_structural_teacher_canary_20260731_v352_fold4_seed_20261091`
- `outputs/_work/p05_neural_road_generation/target_a_frozen_anchor_condition_adapter_canary_20260731_v353r3_fold2_seed_20261101`
- `outputs/_work/p05_neural_road_generation/target_a_frozen_anchor_condition_safety_audit_20260731_v354_fold2`

冻结锚定条件桥已固化为
`target_a_anchor_structural_conditioning.py`；新增合同测试覆盖 raw evidence、
padding、required anchor 越界和 carrier 梯度隔离。完整 P05 回归为
`703 passed, 1 warning`。

## 2026-07-31：recall-first 端到端 Road 集合与几何输出

本轮按“先让端到端模型对每个对象出结果，再收敛错误，先保召回”重设研究
执行顺序。置信发布门不参与研究输出；正式安全 gate 仍保持零危险要求，
`KEEP_SWSD` 与 `ABSTAIN -> fallback` 分开。

### 输入与候选合同

- forward 单位为一个 AdvanceRight、两侧普通 Segment 及其 required
  anchors；T01 业务骨架冻结，T07 仍是前置证据；
- v383r4 对 474 个原始提右识别 434 个可组成完整依赖子图的对象，另 40 个
  因冻结 T01 access 不完整保持提右 Segment 局部 fallback；
- Road 集合候选只使用 50D 推理期局部证据，不读取旧
  `oof_conditioned_feature_values`；有监督对象正确集合
  `313/313` 可达；
- v387r2 的几何 union 使用普通完整方案成员与原始 side Road candidates，
  不读取普通终态或几何终态选择。共 269,875 个 103D proposal，最大单对象
  5,188；218/218 个需要新增动作的监督对象完整可达；
- GPKG、feature/label store 每次运行只读一次，候选与组合在内存复用，
  不按 epoch 重复物化 RoadGraph。

### v384、v386：完整提右 Road 集合

v384 首次把 anchor、ordinary 和完整提右 Road 集合放入同一 forward。
外层 fold0 对 177/177 对象强制输出，127 个监督对象 top-1/top-3/top-5
分别为 `102/127=0.803150`、`122/127=0.960630`、`127/127=1.0`。

v386r1 新增显式 Road cardinality 与两侧 ordinary source 概率，在未用于
v384 设计分析的外层 fold1 上得到：

| 指标 | v386r1 fold1 |
|---|---:|
| 强制研究输出 | `143/143=1.0` |
| Road 监督 | `106` |
| Road top-1 exact | `86/106=0.811321` |
| Road top-3 recall | `95/106=0.896226` |
| Road top-5 recall | `101/106=0.952830` |
| Road top-16 recall | `106/106=1.0` |

5 个 top-5 miss 均不是候选缺失，正确方案排名为 8、14、8、8、13。两条后续
训练折缺口的正确 Road 排名分别为 31/128 和 17/32，均是模型偏好较短
Road 集合导致的 cardinality/完整性排序错误。

### v388r1、v389：同一 forward 几何头

v388r1 保持 v386r1 完全冻结，只训练 365,953 参数几何头；训练和外层评价
都使用 free-run ordinary 状态，不使用 teacher 锁。v389 只把同一 checkpoint
的 Road/几何 beam 审计为 16，不修改权重或候选。

| 指标 | 结果 |
|---|---:|
| 参数量 / 可训练参数 | `25,016,551 / 365,953` |
| 外层研究输出 | `143/143=1.0` |
| Road top-1 / beam-16 | `0.811321 / 1.0` |
| 几何监督 | `67` |
| 几何 top-1 complete exact | `30/67=0.447761` |
| 几何 beam-16 complete recall | `67/67=1.0` |
| 联合监督 | `77` |
| 联合 top-1 complete exact | `33/77=0.428571` |
| 联合 beam-16 recall | `77/77=1.0` |

这证明第一版端到端系统已经能够对全部外层对象输出完整 Road 集合和分类型
几何 proposal，并在可控 beam 内保住正确完整方案；它不等于最终 Node/方向/
拓扑和 RoadGraph 已物化正确。

### v390：平面组合 decoder 否决

v390 只允许四种业务可解释 schema：

1. `SWSD_ONLY_NO_NEW_GEOMETRY`；
2. `RCSD_SOURCE_AND_TARGET_ATTACHMENTS`；
3. `SOURCE_RCSD_ATTACHMENT_AND_MIDDLE_SPLICE`；
4. `TARGET_RCSD_ATTACHMENT_AND_MIDDLE_SPLICE`。

它不能改锚定、扩候选、改变 T01、重新判断证据或创建通用 HYBRID。训练期
Road/几何 beam=32 使 239/239 联合监督可达，外层仍固定 16；但最多 81,920
个组合的平面 softmax 得到 top-1=`32/77=0.415584`、top-16=
`63/77=0.818182`，低于 v388r1/v389。该路线判定
`STRUCTURED_FLAT_COMBINATION_NO_GO`。

当前保留 v388r1/v389 作为 recall-first 基线。下一步不得继续扩大候选或
评估 beam；应分别收敛完整 Road cardinality/成员排序和分类型几何 top-1，
随后完成五折 OOF、Node/方向/拓扑写出、最终 RoadGraph exact、完整策略
paired comparison 与零危险发布门。完整 P05 回归为
`719 passed, 1 warning`；P05 范围源码/测试文件无 100 KB 超阈值。

## 2026-08-01：Target A 联合训练里程碑 M1/M2

为结束 v470–v475 冻结 encoder 后反复更换 scorer/loss 的局部路线，本轮不再
沿用版本号累加作为进度，而建立两个有明确假设的联合训练里程碑。两者均以
Fold1 为严格外层留出，只运行一个 seed、一个固定配置和 4 epoch，不使用
Fold1 选择参数或阈值。

M1 首次让同一 30,092,522 参数系统同时接收全范围锚定监督和依赖子图中的
ordinary 完整 Road/access、AdvanceRight 监督。前向仍先锁定 anchor，再解码
ordinary 和 AdvanceRight；训练期允许多任务 loss 更新共享 encoder。Fold1
锚定 status accuracy 从初始化的 `0.849255` 提升到 `0.901840`，gate failure
recall 从 `0.051095` 提升到 `0.744526`，候选 acceptable exact 从
`0.844371` 提升到 `0.848786`。但 ordinary 完整 Road 泛化下降：

| 指标 | 初始化 v442 | M1 |
|---|---:|---:|
| reachable Road-set exact | `0.097378` | `0.086142` |
| business side complete exact | `0.106996` | `0.094650` |
| both ordinary complete exact | `0.018868` | `0.009434` |
| effective decision exact | `0.800699` | `0.737762` |
| AdvanceRight conditional exact | `0.660377` | `0.820755` |

M2 在同一联合系统内增加业务阶段 stop-gradient：锚定监督更新共享 encoder；
ordinary loss 只更新 ordinary decoder/adapter；AdvanceRight loss 只更新条件化
head，不能回写普通 Segment。定向测试证明 base embedding 无下游梯度，而两个
后级 head 仍可训练。M2 的 Road-set、business side 和 both-side exact 与 M1
相同，effective decision 进一步降至 `0.695804`，AdvanceRight conditional
exact 保持 `0.820755`，business plan exact 为 `0.632075`，10+ Road exact
仍为 0。

因此 M1/M2 均为 **NO_GO**。结果否定的是“现有 ordinary member/cardinality
表示只需直接联合反传或增加阶段梯度隔离即可收敛”，不否定 Target A。当前
瓶颈已定位到普通 Segment 完整 Road 集合的结构表示和 decoder：候选空间存在
正确解，但现有独立 member + cardinality top-k 无法表达集合边界、连接结构和
大集合完整性。下一步不得继续调整同一 loss 权重；必须把普通 Segment 输出
改为对业务合法完整 Road 方案进行 listwise/结构化选择，并在该阶段通过后再接
AdvanceRight 与 RoadGraph 物化。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_joint_multitask_m1_20260801_fold1_seed_20261501`
- `outputs/_work/p05_neural_road_generation/target_a_joint_hierarchical_m2_20260801_fold1_seed_20261502`

## 2026-08-01：M54–M65 普通 Segment 真实 free-run 与完整写出

### 1. 纠正旧 M46/M49 来源泄漏

复核 M37→M38→M46→M49 字段来源后确认：M46 的 Road membership 和 BREAK
虽为 free-run，但 `effective_decision` 继承 M24 已给定来源，Fold1
`source_exact=1.0`。因此 M49r11/r12 的自动覆盖约 `53%` 只能解释为
“来源已知时的条件化 Road/break/materializer 组件结果”，不能解释为真实
端到端结果。本轮不删除这些历史工件，但从正式端到端基线中撤出。

### 2. M54 锚定门与 M59 来源+完整 Road 集合

M54 对一个普通 Segment 的全部 required anchors 做独立 set gate，不允许
Road 分数修改锚定对象。M54 在 M46 的 920 Segment 范围内有 908 个可对齐
对象，recall gate 接受 628；已知锚定正确 627、错误 1。

M59 对 M5 的完整 Road proposal 做固定三 seed listwise ensemble；三 seed、
batch size 和 epoch 数均在 Fold1 前冻结。每个模型 882,626 参数，ensemble
共 2,647,878 参数。Fold1 指标：

| 指标 | M59 |
|---|---:|
| source exact | `0.886957` |
| complete Road exact | `0.726087` |
| KEEP Road exact | `0.903803` |
| USE Road exact | `0.558140` |
| 10+ Road exact | `11/30=0.366667` |

在 M54 recall gate 接受的 628 个对象中，来源+完整 Road 集合正确 466、错误
162；三 seed 完全一致时接受 468，正确 410、错误 58。该结果是真实
free-run 的“先保召回”Road 阶段结果，不是安全发布结果。

### 3. M60/M61 BREAK、M63 角色与 M64 access

M60 为所有标签成员和 M59 实际选择的 Road 建立 BREAK 任务。Fold1 M59
预测为 USE 的 455 个 Segment、1,866 条 Road 全部进入 M61；其中 320 条为
模型选择但不是真值成员的 inference-only Road。`selected_by_m37` 从未进入
M45 特征，因此复用冻结 M45 checkpoint 不改变模型输入合同。

M45 recall 阈值 `0.001` 在 M59 selected scope 上对 1,491 条 NO_BREAK Road
产生 1,206 个 false positive，Segment exact 仅 `35/410=0.085366`。strict
Fold2 冻结的 balanced 阈值 `0.95` 将 false positive 降为 1，Segment exact
提升至 `376/410=0.917073`；break recall 为 `17/55=0.309091`。完整图目标下，
错误打断会破坏本来正确的主干，因此 M62 正式研究组合使用 balanced，而不是
以子任务 recall 滥报 BREAK。

M62 真实 free-run 完整 Road/BREAK 工作点：

| 工作点 | 接受 | 覆盖 | 完整正确 | 已知错误 |
|---|---:|---:|---:|---:|
| RECALL | 627 | `0.681522` | 466 | 161 |
| STABLE_ENSEMBLE | 468 | `0.508696` | 410 | 58 |

M63 对 M59 选中的 Road 全量输出角色，候选缺失为 0。RECALL 范围 1,782 条
Road 中预测 MAIN 1,776、ATTACHED_SWSD 6；有完整角色真值的 420 个 Segment
全部 exact。INTERNAL_CONNECTOR 仍没有稳定预测，符合仅 1 个 Segment 监督
的已知限制；安全角色只接受 Fold3 校准的高置信 MAIN。

M64 用 M59 来源和 Road 清单重新写入 carrier condition 后运行冻结 access
head。128 个有完整 access 真值的 Fold1 ordinary Segment：access set exact
`0.429688`；RECALL 已接受范围为 `0.546667`，Road+access 联合 exact
`0.200000`；STABLE 范围分别为 `0.607143/0.321429`。其他 Segment 没有完整
access 真值，必须记 Review，不能补成正确或错误。

### 4. M65 确定性 RoadGraph 写出

M65 首次整图写出被 materializer 以“同一 source Road 最终所有权区间重叠”
阻断，证明 hard legality 生效且没有 silent fix。随后仅在各工作点内部计算
重叠区间：RECALL/STABLE 分别形成 23/13 个 raw Road 冲突组；只回退冲突
Segment，未扩为 Case fallback。最终两套 GPKG 均通过合法性检查：

| 指标 | RECALL | STABLE |
|---|---:|---:|
| 自动物化 | `492/920=53.48%` | `415/920=45.11%` |
| 正向 KEEP | 273 | 241 |
| USE_RCSD | 219 | 174 |
| fallback | 428 | 505 |
| 已知错误 | 71 | 31 |
| Review 自动项 | 487 | 412 |
| Road / Node | `2238 / 2914` | `2112 / 2697` |
| skeleton mutation | 0 | 0 |
| silent fix / content repair | false / false | false / false |

RECALL 已知错误由 Road 58、access 4、Road+access 9 组成；STABLE 为 Road 24、
access 4、Road+access 3。高召回回退主因包括锚定 322、角色 41、access 26、
所有权冲突 20、BREAK/ownership 6。当前最关键的可训练瓶颈是来源/完整 Road
集合排序和 M59 条件下的 access 泛化，而不是继续扩大候选。

### 5. 结论

本轮完成了“普通 Segment 优先”的真实端到端研究里程碑：神经系统从锚定、
来源、完整 Road 集合、BREAK、角色到 access 输出业务方案，确定性层只执行
Node/几何/ID 写出、合法性检查与已确定的局部 fallback。它尚未满足安全发布：
已知错误和 Review 自动项均非零，完整策略 paired comparison、五折三 seed、
城市级 I/O 与 AdvanceRight RCSD_ONLY/MIXED_SPLICE 仍未完成。因此正式结论
保持 **NO_GO**，但不再是“模型不能出完整结果”；下一迭代只优化普通 Segment
真实 free-run 错误，AdvanceRight 继续后置。

完整 P05 回归在同步 `_lock_anchor` 三返回值测试契约后通过：
`754 passed, 1 warning`。warning 为 PyTorch Transformer 的
`enable_nested_tensor/norm_first` 性能提示，不是业务或功能失败。

主要工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_proposal_ensemble_m59r1_20260801_fold1_seed_20261580`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_true_free_run_plan_m62_20260801_fold1_seed_20261583`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_m59_access_m64_20260801_fold1_seed_20261585`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_true_free_run_materialized_m65_recall_20260801_fold1_seed_20261586`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_true_free_run_materialized_m65_stable_20260801_fold1_seed_20261586`

## 2026-08-01：M66–M68 普通 Segment Road 方案定向收敛

### 1. M66 USE 平衡训练

M59 的 252 个完整 Road 错误中，209 个发生在 `USE_RCSD`。M66 只在
inner Fold2 比较 `USE_RCSD` 行权重 `1.0/1.25/1.5/2.0`，以 KEEP/USE
完整 Road exact 宏平均为首要选择指标；Fold1 不参与权重选择。inner 选择
`1.25`，Fold1 相对 M59 的结果为：

| 指标 | M59 | M66 |
|---|---:|---:|
| source exact | `0.886957` | `0.892391` |
| complete Road exact | `0.726087` | `0.731522` |
| KEEP Road exact | `0.903803` | `0.899329` |
| USE Road exact | `0.558140` | `0.572939` |
| 10+ Road exact | `0.366667` | `0.366667` |

M66 提升 5 个完整 Road 方案，收益主要来自 USE；KEEP 小幅下降 2 个。
该模型保持 3 seed、每个 882,626 参数，候选集、锚定门和业务骨架均未改变。

### 2. M67 完整下游重放

M67 以 M66 实际选择的 Road 重新建立 BREAK 任务，并贯穿冻结的 Road 角色、
access 和确定性 RoadGraph 写出。相对 M65：

| 指标 | M65 RECALL | M67 RECALL | M65 STABLE | M67 STABLE |
|---|---:|---:|---:|---:|
| 自动物化 | 492 | 484 | 415 | 415 |
| 已知错误 | 71 | 67 | 31 | 28 |
| Review 自动项 | 487 | 479 | 412 | 412 |
| 正向 KEEP | 273 | 267 | 241 | 242 |
| USE_RCSD | 219 | 217 | 174 | 173 |

RECALL 自动物化下降 8 个，是 M66 新选择造成的共享 Road/所有权区间冲突被
合法性层局部回退；没有扩成 Case fallback。STABLE 覆盖不变、已知错误减少
3 个。两套 GPKG 均为 EPSG:3857，且 `skeleton_mutation=0`、
`silent_fix=false`、`content_repair=false`。冻结 access head 在 M66 条件下
整体 exact 从 `0.429688` 降为 `0.421875`，证明只改 Road loss 不能解决
access 的训练/推理 carrier 条件不一致。

### 3. M68 source/cardinality 辅助 loss

M68 仅使用每个推理候选已有的 source 和 Road cardinality 建立训练期 group
NLL，不把标签作为推理输入。inner 选择 `source=0.15/cardinality=0.05`，但
Fold1 complete Road exact=`0.729348`、USE exact=`0.562368`，均低于 M66；
仅 source exact 提升至 `0.895652`。因此 M68 不晋升，也不进入整图重放。

### 4. 当前判断

M66 可作为下一轮普通 Segment 条件模型基线，但收益仍小，M68 已证明继续
调整同一 340D proposal summary 的 loss 不足以收敛。该 summary 只保留
selected/excluded Road embedding 的 mean/max/difference 和聚合关系统计；
下一步应让 decoder 直接观察 proposal 内每条 Road 及其 pair relation，重点
解决 reachable proposal 内的 source/完整 Road 排序。AdvanceRight 继续后置，
正式结论仍为 **NO_GO**。

新增工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_use_balanced_ensemble_m66_20260801_fold1_seed_20261587`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_m66_pipeline_m67_20260801_seed_20261588`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_group_aux_ensemble_m68_20260801_fold1_seed_20261589`

## 2026-08-01：M69–M81 普通 Segment 结构与 access 证据迭代

### 1. M69–M72：直接 member-aware Road decoder 未形成可晋升系统

M69 让 complete-plan scorer 直接观察 proposal 内 Road member；Fold1 complete
Road exact 从 M66 的 `673/920=0.731522` 提升到
`680/920=0.739130`，但 source exact 从 `0.892391` 降到 `0.873913`，
USE exact 从 `0.572939` 降到 `0.560254`。M70 将 M69 重放到完整下游后，
RECALL/STABLE 自动物化为 `508/433`，但已知自动错误为 `80/37`，均高于
M67 的 `67/28`；Road 改善没有转化为更好的完整业务系统，因此不晋升。

M71 将摘要与 member-aware 分支直接融合，Fold1 complete Road exact 降至
`0.725000`；M72 只训练 member residual，inner complete Road exact 为
`0.678363`，未通过相对 M66 的 inner gate。两条路线均停止。新增网络保持
proposal 顺序等变、padding mask 和 relation 索引 hard validation；失败归因
于模型效果，不是 I/O 或候选身份错误。

### 2. M73–M77：OOF carrier 条件化 access 的业务一致性与上限

M73 首次补齐 M66 五折 OOF free-run carrier，覆盖 `3156/3156` 个唯一普通
Segment，且每个对象只使用其 held-out fold 预测：

| 指标 | M73 五折 OOF |
|---|---:|
| complete Road exact | `2361/3156=0.748099` |
| source exact | `0.901458` |
| KEEP exact | `0.910850` |
| USE exact | `0.610298` |

在 882 个有 access 完整监督的集合中，只有 273 个与 free-run carrier
候选兼容、234 个同时满足锚定与 carrier 条件、204 个 Road 已完全正确；
这给出了 access 训练可辨识范围，不能把其余项强制补成正确标签。

M74 只用 OOF anchor + OOF free-run carrier 训练 access，并施加 carrier hard
mask；Fold1 128 个完整监督 Segment 上 access exact=`30/128=0.234375`、
carrier compatibility=`1.0`、Road+access exact=`19/128=0.148438`。相比旧
M43，M74 放弃了 carrier 外非法选择，因而作为业务一致的 access head 保留；
它不是高精度突破。M76 将其接入 M66 全链路后，最终 plan+access 仅从
`16/128` 提到 `17/128`，自动覆盖基本不变。

M75 的显式 cardinality decoder 虽减少低估，但产生较多高估，Road+access
降至 `15/128=0.117188`；M77 的 per-Road 0/1/2 结构 decoder 降至
`14/128=0.109375`。两者均保持 carrier compatibility=`1.0`，但不晋升。
误差审计显示，在 M74 Road 已正确的 36 个 Segment 中，错误 access 主要是
真值含两个 `SPLIT_ROAD` 而模型只选一个 `REUSE`；这不是继续放宽 hard mask
可以解决的问题。

### 3. M78/M79：access 可行性反哺完整 Road 方案，确立当前研究基线

M78 从 111,185 条推理期 access candidate 构造 15D 可行性摘要，并附加到每个
完整 Road proposal；明确排除 access label、`in_locked_plan`、locked 字段和
终态结果。三 seed 模型每个 885,506 参数。inner Fold2 同时改善 Road、source、
KEEP 和 USE 后才评估 Fold1：

| 指标 | M66 | M78 |
|---|---:|---:|
| complete Road exact | `673/920=0.731522` | `687/920=0.746739` |
| KEEP exact | `0.899329` | `0.921700` |
| USE exact | `0.572939` | `0.581395` |
| source exact | `0.892391` | `0.857609` |

source 单项退化，但 source + 完整 Road 清单联合 exact 增加 14 个；因此 M78
按完整业务方案目标晋升，同时保留 source 退化为下一轮显式风险。

M79 以 M78 实际 Road 输出重新计算 BREAK、角色、M74 access 和确定性写出：

| 指标 | M67 RECALL | M79 RECALL | M67 STABLE | M79 STABLE |
|---|---:|---:|---:|---:|
| plan 接受 | 627 | 628 | 471 | 475 |
| plan complete exact | 465 | 476 | 410 | 423 |
| plan 已知错误 | 162 | 152 | 61 | 52 |
| 自动物化 | 484 | 510 | 415 | 422 |
| fallback | 436 | 410 | 505 | 498 |
| 物化后已知自动错误 | 67 | 85 | 28 | 27 |
| Road exact | 481 | 492 | 481 | 492 |
| plan+access exact（128） | 16 | 16 | 16 | 16 |

RECALL 遵循用户确认的“先保召回”研究口径，覆盖增加 26，但已知自动错误也
增加 18，不能作为安全发布工作点；STABLE 增加 7 个自动结果、Road exact
增加 11，已知自动错误从 28 降到 27。两套图均为 EPSG:3857，且
`skeleton_mutation=0`、`silent_fix=false`、`content_repair=false`。
因此当前研究基线固定为 **M78 complete Road scorer + M74 carrier-conditioned
access + M79 pipeline**，正式发布结论仍为 **NO_GO**。

### 4. M80/M81：后验 blend 不晋升

M80 只在 Fold2 选择 M66/M78 标准化分数混合系数 `alpha=0.75`；Fold1 Road
exact 为 `688/920=0.747826`，仅比 M78 多 1 个。M81 全链路 RECALL complete
exact 回落到 472、已知 plan 错误升到 156；STABLE 虽接受 482、exact 427，
但已知 plan 错误升到 55。物化后 RECALL/STABLE 已知自动错误为 `86/29`，
均高于 M79 的 `85/27`，Road exact 也从 492 降到 488。M80/M81 不晋升，
后续不得把这 1 个 Fold1 Road 增益解释为系统改善。

### 5. 回归与下一步边界

新增 member-aware、member residual、Road-group access 三个结构模块定向测试
`9 passed`；完整 P05 回归 `763 passed, 1 warning`。唯一 warning 仍为
PyTorch Transformer 的 `enable_nested_tensor/norm_first` 性能提示。

本轮结论是：普通 Segment 已有可完整写出的 recall-first 研究基线，但尚未
收敛到安全发布；下一轮继续优先解决锚定、source/完整 Road 方案和 access
联合错误。AdvanceRight 继续后置，不恢复 `RCSD_ONLY/MIXED_SPLICE` 训练。

主要工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_m66_oof_m73_20260801_seed_20261594`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_free_run_access_m74_20260801_fold1_seed_20261595`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_m74_pipeline_m76_20260801_seed_20261597`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_access_evidence_plan_m78_20260801_fold1_seed_20261599`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_m78_pipeline_m79_20260801_seed_20261600`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_blended_plan_m80_20260801_fold1_seed_20261601`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_m80_pipeline_m81_20260801_seed_20261602`

## 2026-08-01：M82–M90 source 与锚定对象重建

### 1. M82–M84：source 分层未改善完整 Road 目标

M82 将 source 选择与 Road bundle 选择分层，inner 最终仍选择 M78 direct，
Fold1 complete Road exact 保持 `687/920=0.746739`。M83 加入 source auxiliary
loss 后 source exact 提升到 `0.868478`，但 complete Road exact 降到
`684/920=0.743478`；M84 的条件 source branch 仍选择 M83 direct，未恢复
Road 指标。三条路线均不晋升，证明当前损失不是单独强化 source 分类即可解决。

### 2. M85/M86：独立锚定候选对象 selector 有效

M85 在严格 Fold2 gate 下，将 Fold1 有完整候选监督的锚定对象 exact 从
`753/906=0.831126` 提升到 `776/906=0.856512`。M86 随后补齐五折 OOF，
3,318 个有监督 SUCCESS 锚定对象的 acceptable exact 从
`2690/3318=0.810729` 提升到 `2816/3318=0.848704`，五个 fold 均提升。
M86 只替换既有候选中的唯一对象，不修改 status、候选集合、T01 骨架或
下游 Road 方案，因此作为新的锚定对象选择组件保留。

### 3. M87–M90：release gate 尚未收敛

M87 在 M86 OOF 对象上重训 Segment anchor-set gate：高召回工作点在 Fold1
接受 1,018/1,628，其中已知正确 734、错误 146、未知 138；安全工作点接受
568，其中错误 4。M89 加 agreement/投票条件可把 M79 scope 的错误压到 0，
但正确接受仅 563，低于旧 M54 的 627。M90 加入 old/new candidate delta、
vote、margin 等 512D 锚定特征后，validation recall 仍有 10 个错误和 13 个
未知，validation safety 仍有 3 个错误。结论：M86 对象选择晋升，M87–M90
gate 均仅保留为研究输出，正式安全结论仍为 **NO_GO**。

## 2026-08-01：M91–M98 普通 Segment 高召回端到端重建

### 1. M91：补齐五折 OOF 高召回锚定门

为避免把 Fold1 M87 gate 灌入其他训练折，M91 对 5,821 个普通 Segment 建立
严格五折 OOF gate；每折模型均排除 outer fold 和相邻 inner fold。高召回
分支接受 3,481 条，各折已知正例 recall 为 `0.929260–0.992509`，但包含较多
错误/未知项，固定标记为 `RECALL_RESEARCH_ONLY_NOT_PRODUCTION`。缺失完整
anchor feature 的 Road 监督样本不删除、不补造原因，统一以 `UNRESOLVED`
进入 fallback 分母。

### 2. M92/M93：Road encoder 与完整方案重新条件化

M92 首次用 M86 OOF 已选锚定对象和 M91 OOF gate 重训 Road graph encoder，
不再复用含旧锚定状态的 M5 cache。Fold1 920 条中有 720 条进入 Road 判断；
encoder direct Road exact=`686/920=0.745652`，已进入锚定门的 Road exact=
`530/720=0.736111`。M93 重新生成 3,156 条普通 Segment 的双来源完整集合
候选并训练 listwise selector：Fold1 Road exact=`655/920=0.711957`，
anchor+Road exact=`514/920=0.558696`；10+ Road 从 M92 的 `1/30` 提升为
`6/30`。候选 Oracle=`851/920=0.925`，主要损失位于完整方案排序而非候选缺失。

### 3. M94–M96：同链路 access evidence gate

M94 的 Fold2 access-evidence scorer 将同链路 Road exact 从 `229/342` 提升到
`240/342`，USE 不退且 10+ Road 保持 `3/16`，但旧 M78 gate 错用不同锚定
链路的 M66 `5/16` 作门槛而拒绝。M95 新 seeds 的 10+ Road 降到 `2/16`，
按同链路 gate 正确拒绝。M96 用 M94 固定 seeds 复现 Fold2 后才查看 Fold1：

| 指标 | M93 | M96 |
|---|---:|---:|
| complete Road exact | `655/920=0.711957` | `675/920=0.733696` |
| anchor + Road exact | `514/920=0.558696` | `528/920=0.573913` |
| KEEP exact | `0.908277` | `0.865772` |
| USE exact | `0.526427` | `0.608879` |
| 10+ Road exact | `6/30` | `8/30` |

M96 提升 USE 和大集合，但 KEEP 退化，下一轮必须做同一链路的分支平衡。

### 4. M97 降级、M98 纠正后的完整写出

M97 虽已写出 RoadGraph，但 M62 下游仍读取旧 M54 gate，违反“普通 Segment
free-run 锚定最终状态是下游硬前置”，因此降级为旧门兼容诊断。M98 改为
M91 Fold1 OOF gate 后重新组合 M96 Road、冻结 BREAK/role/access heads 和
确定性物化：

| 指标 | M98 RECALL | M98 STABLE |
|---|---:|---:|
| plan 接受 | `719/920=0.781522` | `598/920=0.650000` |
| 锚定+Road+BREAK 完整方案正确 | `477/920=0.518478` | `444/920=0.482609` |
| 已知 plan 错误 | 242 | 154 |
| 自动物化 | `474/920=0.515217` | `430/920=0.467391` |
| 最终 Road exact | `508/920=0.552174` | `508/920=0.552174` |
| plan+access exact（128） | 14 | 14 |

M98 access 在 128 个完整监督 Segment 上：access exact=`26/128=0.203125`，
Road+access exact=`14/128=0.109375`。两套 GPKG 均为 EPSG:3857，且
`skeleton_mutation=0`、`silent_fix=false`、`content_repair=false`；fallback
保持 Segment 局部。M98 仍复用旧 BREAK、role、M74 access 与 validity
checkpoint，只是正确数据流组合基线，不得解释为完成五折联合重训或安全发布。

### 5. 当前结论与下一步

普通 Segment 已从“个位数安全发布覆盖”推进到一个可完整输出、可审计的
高召回研究链路，但 78 个已知锚定错误、KEEP/USE 不平衡和 `14/128` 的
Road+access 是明确未收敛项。下一步必须补齐 M96 Road 方案的严格五折 OOF，
再以同一 free-run carrier 重训 access、BREAK 和 validity；禁止继续复用旧
M66/M54 条件结果冒充新链路。AdvanceRight 和 Movement 继续后置，正式结论
仍为 **NO_GO**。

主要工件：

- `outputs/_work/p05_neural_road_generation/target_a_anchor_candidate_selector_oof_m86_20260801_seed_20261607`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_set_gate_oof_m91_20260801_seed_20261612`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_conditioned_encoder_m92_20260801_fold1_seed_20261613_r1`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_conditioned_plan_m93_20260801_fold1_seed_20261614`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_anchor_access_plan_m96_20260801_fold1_seed_20261621`
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_m96_corrected_pipeline_m98_20260801_seed_20261623`

## 2026-08-02：M99–M137 普通 Segment 优先收敛与评价口径修正

### 1. M99–M126：完整 Road 候选池与严格五折 OOF

本轮继续冻结 AdvanceRight/Movement，只训练普通 Segment。M99/M100 先补齐
严格五折 OOF Road 方案，M120 再以 nested gate 组合既有 Road decoder；随后
M123/M124 将 M5 与 M93 的完整 `KEEP_SWSD/USE_RCSD` 方案合并为同一候选池，
M126 用三 seed listwise ensemble 降低排序方差：

| 指标 | M120 | M124 | M126 |
|---|---:|---:|---:|
| 五折 complete Road exact | `2366/3156=0.749683` | `2396/3156=0.759189` | `2414/3156=0.764892` |
| source exact | - | `0.887200` | `0.899240` |
| 10+ Road exact | `45/142` | `50/142` | `52/142` |

M126 候选 Oracle=`3009/3156=0.953422`，说明正确完整方案通常已在候选池中；
当前主要损失仍是跨 Case 排序。Fold1 单独比较时，M120=`680/920`，高于
M126=`672/920`，因此 Fold1 端到端链继续使用 M120，五折总体研究基线使用
M126，不用单一 Case 结果覆盖五折结论。

### 2. M129–M132：零已知错误组合与 access 评价范围纠正

M129 只使用推理期证据训练 Road 方案有效性门。selection fold 上的
`ZERO_ERROR` 阈值不能直接解释为跨城市零错误：五折自动接受
`1341/3156`，其中正确 1316、错误 25。该门不得单独作为正式发布门。

Fold1 内将 M89 的零已知锚定错误 consensus 与 M129 Road 门相交后，M130
得到 182 个普通 Segment：锚定、完整 Road、BREAK 和角色方案均为
`182/182` exact，且 raw Road 所有权冲突为 0。M131 随后完整物化：

| 指标 | M131/M132 |
|---|---:|
| 自动普通 Segment | `182/920=0.197826` |
| 正向 KEEP_SWSD | 164 |
| USE_RCSD | 18 |
| fallback | 738 |
| skeleton mutation | 0 |
| silent fix / content repair | false / false |

M131 旧汇总把 `automatic_fully_supervised` 记为 0，原因是它要求每个分支都
具有独立的 terminal access 标签。M132 按已确认业务合同纠正：

1. 正向 `KEEP_SWSD` 已输出 exact 的完整 T01 Road 方案，access、Node 和方向
   直接采用冻结 T01 realization；RCSD access 标签对该分支不适用；
2. 当前 18 个 `USE_RCSD` 均为两个 required anchor 独立锁定唯一 `NODE:`
   JunctionUnit，完整 Road/BREAK/角色 exact；确定性层只枚举该 JunctionUnit
   内与已选 Road 相交的全部端点并写 Node ID，方向/拓扑 hard validation
   已通过，未作修补；
3. `ROAD:` 锚定、Junction+Road 复合锚定、无锚定真值或仍需额外 access
   选择的路径不在该推导范围内，继续 Review/fallback。

因此 M132 将这 182 条记为 `derived_business_exact=182/182`，其中
`FROZEN_T01_KEEP_DETERMINISTIC=164`、
`EXACT_ANCHOR_ROAD_BREAK_TOPOLOGY_DETERMINISTIC=18`。这是 Fold1 普通
Segment 当前安全研究工作点，不外推为五折或生产发布结果。

### 3. M133–M137：发布门与二级重排均未形成实质提升

M133 分别校准 KEEP/USE 阈值，在 M89 Fold1 锚定范围内从 182 扩到 198，
但新增项含 2 个危险 `USE_RCSD -> KEEP_SWSD`；M134 独立 KEEP expert 扩到
205 时含 6 个错误。两者均不晋升，说明当前不是继续换阈值或单独训练 KEEP
门可以解决的问题。

M135 在 pooled plan loss 上增加 source auxiliary loss，Fold1 Road exact=
`677/920`，高于 M126 的 672，但低于 M120 的 680，且多数投票仅 675，结论
`NO_PROMOTION`。M136 将 M126 top-12 完整方案缓存为 694D 二级输入，五折
top-12 Oracle=`2913/3156=0.923004`。M137 用严格 outer/selection fold 训练
二级 Set Transformer，最终 Road exact=`2415/3156=0.765209`，只比 M126 多
1 条，同时 source exact 少 13 条、10+ Road exact 少 1 条。脚本的机械
“多 1 条即 promote”标记不作为工程晋升结论；综合准确性、稳定性、复杂度和
计算成本，M137 仅保留为诊断证据，主基线不变。

### 4. 当前结论

普通 Segment 已形成两个清楚但不同的工作点：

- recall-first Road 研究基线：五折 M126=`76.49%`，Fold1 当前链路
  M120=`73.91%`；
- Fold1 零已知错误完整物化工作点：M132=`182/920=19.78%`，其中
  KEEP=164、USE=18。

候选 Oracle 已超过 95%，继续扩大候选、扫描发布阈值或堆叠同类二级 reranker
都不是下一优先级。下一轮应回到共享 encoder 的业务证据表达，使 source、
完整 Road bundle、锚定对象和有向拓扑在同一 forward 中形成可区分表示；
AdvanceRight 继续后置，直到普通 Segment 的 recall-first 与安全工作点同步
提升。

## 2026-08-02：M138–M145 普通 Segment 锚定与完整 Road 联合基线

### 1. M138–M141：纠正为同一 forward 的锚定硬门禁

M138–M141 将 required anchor 候选选择、锚定状态和完整 Road 方案置于同一
forward。锚定对象先独立唯一确定；其离散结果锁定并从 plan 梯度中分离，
Road decoder 不能反向修改锚定。M141 使用 M86 严格 OOF 锚定教师证据，
Fold1 的 anchor exact=`690/906=0.761589`、gated complete Road exact=
`653/908=0.719163`、anchor+Road joint exact=`523/906=0.577263`。该结果优于
同轮其他联合变体，但低于独立 M126 Road 基线，不能晋升为发布模型。

### 2. M142/M143：局部 Road 锚定专家不晋升

M142 只训练 `ROAD:` 锚定对象专家，在 ordinary Fold1 范围相对 M86 出现
6 个修正和 6 个新增错误；限制为仅覆盖 M86 已判为 Road 的对象后也只有净增
1 条。M143 增加显式集合大小辅助头，inner Fold2 改善，但 outer Fold1 的
Road exact 从 `0.665370` 降到 `0.657588`。两者均为 `NO_PROMOTION`；剩余
错误主要是跨 Case 的 Road 集合成员与 cardinality 表达，不再继续堆叠局部
Road expert。

### 3. M144：严格五折普通 Segment 高召回端到端基线

M144 对 v107 与 v189 可正确连接的 3,125 个普通 Segment 建立严格五折 OOF
联合评价；31 个没有 required anchor 的对象不被补造为成功。结果如下：

| 指标 | M144 五折 |
|---|---:|
| 强制 gated output | `3119/3125=0.998080` |
| anchor exact | `2388/3123=0.764649` |
| raw complete Road exact | `2381/3125=0.761920` |
| gated complete Road exact | `2370/3125=0.758400` |
| anchor + gated Road joint exact | `1910/3123=0.611591` |
| Road exact（已正确锚定） | `1910/2388=0.799832` |
| 10+ Road exact | `52/142=0.366197` |

`99.81%` 只表示研究链路能够输出，不是安全发布覆盖；`61.16%` 才是锚定与
完整 Road 同时正确的当前端到端 exact。按现状推导，固定当前 Road decoder
而让锚定完美时，上限约 `75.82%`；固定当前锚定而让 Road 完美时，上限约
`76.46%`。因此最终 80% 联合目标不能只修一个分支。M144 固化为
`TARGET_A_ORDINARY_JOINT_HIGH_RECALL_BASELINE_NO_GO`，正向 KEEP_SWSD、
ABSTAIN fallback 和安全发布仍必须分开统计。

### 4. M145：独立锚定预训练不晋升

M145 将允许训练折内的 T03/T04/T10 锚定监督用于同结构独立预训练，再接回
M141。Fold1 anchor exact 从 `690/906` 降为 `689/906`，joint exact 从
`523/906` 降为 `518/906`，gated Road exact 从 `653/908` 降为 `648/908`。
结论不是丢弃 T03/T04 人工真值，而是停止“独立候选列表预训练后直接接回”
这一路径；这些强标签下一轮进入共享业务依赖子图 encoder 的多任务 loss。

### 5. 修正方案 A 的下一步

普通 Segment 继续优先，AdvanceRight 暂停训练，Movement 保持关闭。下一轮
用同一依赖子图显式表达 focal Segment、required anchors、候选 RCSD Road、
共享 Junction/Node、access 和所有权冲突；锚定先输出且形成硬门禁，完整 Road
方案在锁定锚定条件下解码。城市级 Road/Node/Junction 索引只读一次，forward
按动态业务依赖子图组装，最终 decoder 只在冲突连通组内组合和执行已确定的
Segment/Junction fallback，不扩张 T01 骨架或重新判断业务证据。

## 2026-08-02：M146–M149 普通 Segment 依赖图与显式 Road 成员验证

### 1. M146–M148：相邻普通 Segment 压缩上下文不晋升

M146 将相邻普通 Segment 的锚定与 top-12 方案加入单向依赖图，并以隔离测试
确认下游 plan loss 不能反向修改锚定。Fold1 相对 M141 的 raw Road exact 从
`654` 增到 `661`，但 anchor exact 从 `690` 降到 `679`，joint exact 从
`523` 降到 `519`。M147 保留独立锚定路径、只向 plan decoder 注入相邻上下文，
Fold1 joint exact 增到 `528/906`，因此进入严格五折 M148。

M148 五折 joint exact=`1924/3123=0.616074`，比 M144 多 14 条；但 gated Road
exact 从 `2370/3125` 降到 `2365/3125`，强制输出从 `3119/3125` 降到
`3104/3125`，10+ Road 仍为 `52/142`。相对 M126 的 3,156 条方案只有 11 条
发生变化，其中 4 条修正、1 条新增错误、6 条仍错误。结论为 694D 相邻方案
压缩向量没有充分暴露具体 Road 成员、所有权和 Road—Road 关系，不晋升。

### 2. M149：显式 Road 成员图仍未超过当前基线

M149 对 M126 top-12 的 37,196 个完整候选方案显式读取 115D Road 证据与 13D
Road—Road 关系，模型 606,787 参数，不使用终态真值、AdvanceRight 或
Movement。Fold2 只选择固定 epoch，Fold1 仅评价一次。结果如下：

| 指标 | M69 Fold1 | M149 Fold1 |
|---|---:|---:|
| 完整 Road exact | `680/920=0.739130` | `668/920=0.726087` |
| KEEP 完整 Road exact | `0.928412` | `0.859060` |
| USE 完整 Road exact | `0.560254` | `0.600423` |
| source exact | `0.873913` | `0.871739` |
| 10+ Road exact | `11/30` | `9/30` |

M149 提高了 USE，但以明显损伤 KEEP、source 和大集合为代价，研究结论为
`NO_PROMOTION`。当前 top-12 缓存的 `mixed_plan_count=0`，所以本轮没有验证
T06 明确允许的“RCSD 主干 + 附属 SWSD 保留”；不得据此宣称混合场景已经
学会，也不得补造通用 HYBRID。

### 3. 当前收敛判断与下一步

普通 Segment 仍未收敛：M144 是当前锚定+Road 高召回联合基线，M126/M120
继续作为完整 Road 排序基线，M132 继续作为 Fold1 零已知错误物化工作点。
M146–M149 共同证明，直接把相邻压缩上下文或显式 Road 图作为同一最终 scorer
残差，主要造成 KEEP/USE 偏置迁移，不能解决 source 与完整成员集合的冲突。

下一轮改为分层条件化 decoder：先在锁定锚定下稳定输出正向 KEEP/USE source，
再只在 USE 分支解码完整 RCSD Road 成员、角色、所有权和 access；KEEP 分支
直接输出完整冻结 SWSD 方案。source 不得由成员分数事后改写，ABSTAIN 仍与
正向 KEEP 分开。AdvanceRight 继续后置，Movement 保持关闭。

## 2026-08-02：M150–M153 source-first 条件化验证

### 1. source 与 Road 成员分支已实现硬隔离

M150 首次把 KEEP/USE source 和完整 Road 成员 decoder 分为两条独立可训练
路径。source loss 到 Road 分支、plan loss 到 source 分支的非零梯度均为 0；
推理先唯一确定 source，再只在该 source 的预枚举完整方案内排序。若预测 source
没有候选，保持不可用，不得静默切换。模型不读取终态真值，AdvanceRight 与
Movement 均不进入 loss。

M150 Fold1 source exact=`0.900000`、USE exact=`0.604651`，但 KEEP exact=
`0.829978`，完整 Road exact=`657/920`。M151 只在 Fold2 从固定阈值网格选择
source 边界，Fold1 提升到 `676/920`，但 KEEP=`0.906040`、10+ Road=`9/30`，
仍低于 M69，不晋升。

### 2. 冻结组件组合与原始 Road source encoder 均未晋升

M152 将独立 source 与 M69 三 seed Road member decoder 组合，source 锁定后
M69 只能在该 source 内排序。结果为 `663/920`、KEEP=`0.906040`、USE=
`0.545455`、source=`0.897826`、10+ Road=`12/30`。大集合改善，但整体和两类
平衡均不足，结论 `NO_PROMOTION`。

M153 不再使用 694D proposal 汇总判断 source，而以独立参数直接编码 115D
Road、13D Road—Road 关系、候选来源和锁定锚定状态；梯度隔离继续通过。
Fold1 source=`0.905435`、USE=`0.591966`，但 KEEP=`0.847875`、完整 Road=
`659/920`、10+ Road=`9/30`。事后仅作容量诊断的 Fold1 最优阈值也只有
`670/920`，低于 680；该阈值未用于模型选择或晋升。source 校准路线到此停止。

### 3. 真值 source 上限审计定位 USE 成员排序瓶颈

将 source 真值锁定、只审计现有 Road decoder 时：

| decoder | Fold1 完整 Road exact | KEEP | USE | 10+ Road |
|---|---:|---:|---:|---:|
| M69 | `734/920=0.797826` | `1.000000` | `0.606765` | `12/30` |
| M126 base | `745/920=0.809783` | `1.000000` | `0.630021` | `9/30` |
| M150 plan branch | `743/920=0.807609` | `1.000000` | `0.625793` | `9/30` |

这证明 source 必须继续保持独立硬门禁，但只修 source 不足以收敛：即使 source
完美，现有 USE decoder 仍有约 37% 的完整 Road 清单错误。下一轮只在 USE
分支训练候选内 hard-negative 完整 bundle/member 目标；KEEP 继续输出唯一
完整冻结 SWSD 方案，不再参与 plan 排序。晋级必须同时超过 M126/M120、提高
USE 与 10+ Road，并保持 source/KEEP 业务门禁不退化。

## 2026-08-02：M154–M158 source-locked USE 完整 Road decoder 验证

### 1. top-12 hard-negative 与关系 bundle 未超过 M126

M154 只使用真值 source=`USE_RCSD` 的 1,709 条监督对象训练 Road membership、
cardinality 和近邻 hard-negative。原始 Road 图对 1,709 个真值集合全部可达，
16,159 个负方案中 12,913 个只相差 1–2 条 Road，说明训练确实覆盖最难近邻，
但 Fold1 只有 `293/473=0.619450`、10+ Road=`9/30`。M155 再增加 95D 的
selected-selected、selected-excluded Road 关系汇总，结果为
`296/473=0.625793`、10+ Road=`9/30`，仍低于 M126 source-locked top-1 的
`298/473=0.630021`，两者均为 `NO_PROMOTION`。

### 2. M156 证明 top-12 是候选保留瓶颈，但不是当前排序解

M156 在独立 source 已锁定为 USE 后，只对 M123 已预枚举的合法 USE 方案按冻结
M126 OOF 分数重排并保留 top-32；没有增加 Road、扩充候选或读取终态特征。
Fold1 结果如下：

| source-locked USE 指标 | 结果 |
|---|---:|
| M126 top-1 exact | `298/473=0.630021` |
| top-12 Oracle | `396/473=0.837209` |
| top-32 Oracle | `415/473=0.877378` |

top-32 相对 top-12 新增 19 条可达正确方案，因此此前全局 top-12 截断确实会
过早丢失合法解；但 Oracle 只表示候选存在，不是模型精度。

### 3. M157/M158 均未把新增正确方案提升到 top-1

M157 用 115D Road、13D Road—Road 关系、95D bundle 汇总和 694D 方案证据
训练 625,027 参数成员图 decoder，Fold1 为 `294/473=0.621564`、10+ Road=
`9/30`。审计发现其 M126 有界残差最多只能改变候选间约 `0.47` 分，而 19 个
新增正确方案与原 top-1 的分差最小 `1.78`、平均 `4.45`，所以 M157 在结构上
不可能把这些方案提升到首位；该结果不能用于否定 top-32。

M158 删除这一有界硬基线，让 950,082 参数 listwise decoder 直接排序 top-32。
Fold2 严格选择 2 epoch 后，Fold1 为 `293/473=0.619450`、10+ Road=`9/30`。
相对 M126 source-locked top-1，M158 保持 293 条正确、丢失 5 条，新增 top-1
为 0；19 个新增可达方案只有 2 个进入 top-10，仍无一个成为 top-1。结论为
`NO_PROMOTION`。

### 4. 当前判断

普通 Segment 尚未收敛。M156 证明候选保留仍有可提升上限，但 M154–M158 也
证明，在当前 115D Road、13D relation 和方案汇总证据上继续增加 hard-negative、
关系汇总、候选宽度或同类 listwise reranker，不能产生跨 Case top-1 改善。
下一步先做 source-locked USE 错误方案的可辨识性审计：分别检查缺 Road、多
Road、错误连接、内部连接、access/方向/拓扑不完整和 10+ Road，确认正确方案
与 top-1 错误方案在推理期证据中是否可区分；只有确认可区分后才重建 Road-level
监督和完整集合 decoder。不得继续用候选 Oracle 解释为已收敛，也不进入五折、
独立 source/锚定接回或安全发布评价。AdvanceRight/Movement 继续后置。

## 2026-08-02：T032-R41 联合主线缺口审计

### 1. M182 的错误不能由单一局部模块解释

对 M182 的 3,125 条普通 Segment OOF 结果按锚定与 Road 集合做互斥分解；
3,123 条锚定真值可评价对象中：

| 锚定 | Road 集合 | 数量 |
|---|---|---:|
| 正确 | 正确 | 1,953 |
| 正确 | 错误 | 478 |
| 错误 | 正确 | 422 |
| 错误 | 错误 | 270 |

Road 方案错误再按 source 硬门禁分解：错误 source 为 283 条；source 已正确但
Road 集合错误为 465 条；完整 Road 集合正确为 2,377 条。锚定错误与 Road
集合错误明显交叉，修单一分支都不能独立达到 Target A 的端到端目标。

### 2. source-locked USE 错误中，多数不是候选不可达

1,709 条真值 USE 中，M182 source 正确 1,590 条、Road 集合正确 1,125 条。
465 条 source 已正确但集合错误对象分为：

| 错误类型 | 数量 |
|---|---:|
| 多选 Road | 217 |
| 少选 Road | 90 |
| 基数相同但成员错误 | 102 |
| 同时多选和少选 | 56 |

其中 top-12 已包含正确集合 272 条，top-32 已包含正确集合 330 条。说明部分
上限仍受候选保留影响，但当前主要瓶颈并非统一的“没有正确候选”。按真值 Road
数分层，M182 Road-set exact 从 1–2 Road 的 `0.782558` 下降到 3–5 Road 的
`0.609914`、6–9 Road 的 `0.487903` 和 10+ Road 的 `0.350365`，集合完整性
随规模恶化仍是明确主问题。

对 top-12 已可达的 272 对 top-1 错误方案与最近正确方案比较 694D 推理期缓存
证据：没有 exact feature collision，也没有 standardized RMS `<0.01` 的近碰撞；
中位 standardized RMS=`0.451488`、cosine=`0.953209`，中位仅 `4.47%` 维度
相差超过 1 个全局标准差。该结果只证明现有缓存能表达差异，不能证明这些差异
能够跨 Case 泛化；因此不得据此再启动同类 reranker 调参。

### 3. 当前主成绩尚未评价完整业务 PlanCandidate

正式 `PlanCandidate` 已定义 Road source、role、owner、方向、piece/split、两端
access、attachments 与 Node recipes，`TargetAJointNetwork` 也已有模型内锚定
硬门禁、ordinary plan、Clue/fallback 和条件化 AdvanceRight 的联合 forward。
但 M126/M182 的 positive 实际只按“target source + Road index set exact”定义，
主成绩没有独立核验 role、ownership、access、方向、打断/Node recipe、挂接和
最终拓扑。

已有组件证据也表明这些字段不能被当前 76.06% 代表：M74 的 128 条 free-run
监督 Segment 中 access exact=`0.234375`；M61 的 410 条可评价 Segment 中打断
相关 segment exact=`35/410=0.085366`；稀有 Road role 仍按安全约束回退。这些
是监督与端到端评价没有接回同一 ledger 的证据，不是继续增加局部模型的理由。

### 4. 主线决策

M219 cardinality fusion、同类 top-k/listwise reranker、epoch/阈值/候选宽度
扫描全部停止。下一步复用现有联合网络与共享依赖子图，在一个普通 Segment
forward 中输出锚定、source、完整 Road、role/ownership、access、方向以及
可监督的打断/Node 关键状态；各字段按现有标签范围使用 task mask 和 Case 权重，
未标注字段不补造负例。严格 OOF 同时报告完整字段可评价子集 exact 与兼容的
source+Road-set 指标。M182 只作历史对照，不得作为新模型推理输入。

审计工件位于
`outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_gap_audit_20260802/`；
仅为 ignored research output，不接生产。AdvanceRight 继续后置，Movement
保持关闭。

## 2026-08-02：T032-R42a 普通 Segment 联合单 forward Fold1 canary

### 1. 本轮验证的是联合主线，不是新的局部 scorer

联合数据层以当前正式普通 Segment 分母 4,236 为范围，一次读取并按 Segment
identity 联接锚定、PlanCandidate、Road member/role/ownership、access collection
和 parent Road break 标签。Fold1 训练/验证分别为 3,027/1,209 条。模型约
29.98M 参数，在同一次 forward 中完成模型内锚定硬门禁、正向 KEEP/USE、完整
Road 集合及关键业务状态输出；access 和 break 显式读取本次 forward 的 Road
membership，不读取旧 carrier 终态。AdvanceRight 不进 loss，Movement 关闭。

训练协议固定为 4 epoch、前 2 epoch teacher forcing、后 2 epoch free-run；没有
扫描 epoch、阈值、候选宽度或发布 gate。既有 v442 checkpoint 的 369 组可复用
参数无 missing/unexpected key 迁移；旧 AdvanceRight Road-set 专用参数不进入
新主线。相关定向回归为 `10 passed`。

### 2. Fold1 全量 free-run 指标同步改善

| 指标 | epoch 0 | epoch 4 | 变化 |
|---|---:|---:|---:|
| free-run 方案输出覆盖 | `0.546733` | `0.564103` | `+0.017370` |
| 锚定 exact | `460/604=0.761589` | `493/604=0.816225` | `+33` |
| KEEP/USE 决策 exact | `1099/1209=0.909016` | `1128/1209=0.933002` | `+29` |
| 完整 Road exact | `520/668=0.778443` | `538/668=0.805389` | `+18` |
| 锚定 + 完整 Road exact | `347/597=0.581240` | `385/597=0.644891` | `+38` |
| role exact | `533/668=0.797904` | `554/668=0.829341` | `+21` |
| ownership exact | `500/668=0.748503` | `510/668=0.763473` | `+10` |
| access collection exact | `7/84=0.083333` | `61/84=0.726190` | `+54` |
| break exact | `0/233` | `227/233=0.974249` | `+227` |
| 10+ Road exact | `0/3` | `1/3` | `+1` |
| strict full exact | `0/24` | `0/24` | 不变 |

训练 loss 从 epoch 1 的 `1.256186` 降到 epoch 4 的 `0.515632`；在切换到
free-run 后仍继续下降。更重要的是锚定、决策、完整 Road、access 和 break 在
独立 Fold1 同时改善，因此当前证据支持“联合表示可学”，不支持回退到局部 scorer。

### 3. strict full=0 尚不能解释为整体不可学，也不能被忽略

24 条 strict full 可评价 Segment 全部来自 `T10:609214532`，不是 4,236 条普通
Segment 的均匀样本；其中最终单字段正确数为：锚定 12、决策 20、Road 11、
role 16、ownership 17、access 17、break 5。14 条至少包含 break 错误，13 条
包含 Road 错误。当前独立 top-k/member head 即使各字段单项改善，也没有保证
它们共同属于同一个合法 PlanCandidate，因此 strict full 仍为 0。

该结果不能用来宣布目标 A 收敛或进入安全发布，也不能据此只调 break 或 Fold1
仅 3 条的 10+ Road。下一步补齐候选约束结构化 decoder，让一个合法方案同时
约束 Road、role/ownership、access、方向和 break/Node recipe，然后再做严格
五折 OOF。decoder 不得修改锚定、扩充候选、读取终态或执行事后修图。

正式运行工件位于
`outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_mainline_r42_20260802_fold1_seed_20261602/`；
包括 checkpoint、逐 Segment predictions、进度和 summary，仅为 ignored research
output，不接生产。

## 2026-08-03：T032-R42b–R42d 结构化 decoder、padding 门禁修正与正确五折基线

### 1. R42b 证明完整 PlanCandidate 可表达，但首次五折数据流不合法

R42b 不再独立拼接 Road、role、ownership 和 access 字段，而是只在现有合法
`PlanCandidate` 中联合选择完整方案。候选不读取终态、不扩充 Road、不改变 T01
骨架；锚定仍是模型内不可反向修改的硬门禁。4,236 条普通 Segment 的候选 Oracle
为 `4028/4236=0.950897`，103 条严格完整业务监督中的候选+access Oracle 为
`83/103=0.805825`，说明候选缺失不是当前第一瓶颈。

首次 R42b 单 seed 五折得到 plan exact=`1784/4236=0.421152`、strict full=
`31/103=0.300971`。但全折归因发现普通 Segment batch 只有 side 0 是正式 focal
Segment，side 1 是空 padding；`side_group_indices` 却把两侧都写为 group 0。
模型因此把正式 Segment 的 source 概率与空 padding 的概率求平均，再执行锚定后的
effective decision。该行为违反“每个普通 Segment 独立锚定并作 carrier 决策”的
业务边界，所以 R42b 数值全部降级为错误数据流诊断，不得作为正式基线，也不得因其
strict 数值较高而保留错误实现。

### 2. R42c 隔离了推理修正效果，R42d 在正确链路重新训练

数据层已改为 focal side=`0`、padding side=`-1`，padding 不再参与 group scatter、
锚定门禁或结构化 plan 选择。定向回归验证该不变量。R42c 使用相同 R42b checkpoint、
不重训，仅按正确数据流五折重评：plan exact=`1942/4236=0.458451`、strict=
`25/103=0.242718`、10+ Road=`13/22=0.590909`。全量 plan 上升而 strict 下降，
证明旧 checkpoint 已适应错误门禁，不能直接晋升。

R42d 从每个 fold 自己的原始锚定 checkpoint 独立初始化，固定 8 epoch（4 teacher +
4 free-run）、相同学习率和候选集合，在正确数据流上重新训练。Fold1 先行 canary
没有退化后，剩余四折按同一协议完成；没有跨折继承权重、没有阈值/epoch/候选宽度
扫描。结果如下：

| 指标 | R42d 单 seed 五折 |
|---|---:|
| 结构化方案有输出 | `4234/4236=0.999528` |
| 候选 Oracle | `4028/4236=0.950897` |
| 全量弱 plan-label agreement | `1960/4236=0.462701` |
| reachable plan exact | `1960/4028=0.486594` |
| 锚定 exact（真值已知） | `1585/2017=0.785821` |
| raw KEEP/USE decision exact | `3934/4236=0.928706` |
| 独立 Road-set exact | `1751/2300=0.761304` |
| access collection exact | `175/246=0.711382` |
| break exact | `859/884=0.971719` |
| 10+ Road 结构化 plan exact | `14/22=0.636364` |
| strict full exact | `28/103=0.271845` |

各折 plan exact 为 `0.504487/0.462366/0.373554/0.396797/0.550000`；strict
为 `17/47`、`6/24`、`4/17`、`1/10`、`0/5`。Fold4 strict 分母只有 5，
不能用 `0/5` 代替其 300 条全量 plan 评价；但 Fold2/Fold3 的 plan 与 strict
仍明显偏低，说明跨 Case 泛化尚未稳定。

### 3. 4,236 条必须按锚定真值作用域解释，不能把未知补造成错误

R42d 首次汇总中的 2,017 条实际表示“所有 required anchor 的唯一对象真值完整”，
不是全部锚定业务状态真值。该对象范围：

- anchor exact=`1585/2017=0.785821`；
- plan-label agreement=`1501/2017=0.744175`；
- anchor+完整 plan joint exact=`1255/2017=0.622211`；
- 锚定正确后 plan exact=`1255/1585=0.791798`；
- effective non-ABSTAIN=`1935/2017`，但其中仍含错误锚定，不能解释为安全覆盖。

R43 按已确认业务语义重审后，2,219 条中另有 400 条已经具备完整的
`NO_EVIDENCE/明确失败` 状态真值，只是按定义不应有 RCSD 锚定对象；它们不能继续
算作未知。另有 115 条状态已知但 `SUCCESS` 对象真值缺失，加上 1,704 条存在未知
状态，共 1,819 条才属于锚定业务真值不完整的 Review。不能把 T10 弱 KEEP 标签
反推为 required anchor 已成功；`relation_record_absent` 仍只表示真值未知，
`T11 no_valid_relation` 则是明确未锚定成功并执行 Segment fallback。

103 条 strict full 的 75 条错误中，失败项可重叠：锚定失败 42、完整 plan 失败
44、plan 内 access Road 失败 23、完整 access collection 失败 43、break 失败 7。
候选 Oracle 仍有 83 条可达，因此下一轮不能回到单一 Road scorer 或继续扩候选；
应同时提升共享 encoder 的锚定对象泛化、锁定锚定后的完整 plan 选择和 access
collection 表达。

### 4. 当前结论与验证

R42d 是当前普通 Segment 唯一业务数据流正确的联合研究基线，但仍为
`COMPLETE_RESEARCH_NO_GO`：未训练安全接受门、未验证零危险自动发布、未接
AdvanceRight，Movement 保持关闭。P05 全量回归为 `778 passed, 1 warning`；
warning 仍是既有 PyTorch Transformer 性能提示。

正式聚合工件位于
`outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_structured_r42d_oof_20260803_seed_20261620/`；
包含五折 canonical OOF predictions 与按锚定真值已知/未知拆分的 summary，仅为
ignored research output，不接生产。

## 2026-08-03：T032-R43–R44 全局归因、梯度边界与高召回端到端基线

### 1. R43 先纠正业务分母，再决定是否改网络

R43 用 R42d 五折 checkpoint 重放每个 required anchor 的状态、对象类型、对象
cardinality 和对象 identity。按正式语义，锚定业务真值完整的普通 Segment 为
`2417/4236`：其中 2,017 条要求全部 required anchor 唯一对象正确，299 条是已证明
无 RCSD 证据的正向 KEEP，101 条是明确未锚定成功并应 Segment fallback；其余
1,819 条保持 Review。

在 2,417 条业务状态可评价范围内，R42d anchor exact=`1805/2417=0.746794`，
anchor+结构化 plan joint exact=`1255/2417=0.519239`。required-anchor item 错误为：
status mismatch 330、对象类型错误 224、对象 cardinality 错误 280、同类型同基数但
identity 错误 107；同一 Segment 可同时命中多类。该结果证明锚定问题不是一个阈值
或单一 candidate scorer 可以解释。

固定 Fold1 对照进一步得到：

- 把正向 `NO_EVIDENCE` 门从禁用值 `1.0` 恢复为 `0.5`，可新增 47/71 条正确
  自动 KEEP，但同时会把 21/40 条明确 fallback 放成非 ABSTAIN；
- 把 anchor cardinality 从软条件改成硬锁，成功锚定从 `484/604` 降到
  `468/604`，因此淘汰；
- 隔离下游 Road/plan 梯度并把 anchor-only loss 恢复到 1.0 后，成功锚定增至
  `489/604`，但正向 NO_EVIDENCE 从 47 降到 36，危险 fallback 仍为 21，
  综合自动正确数反而减少，不进入五折；
- 使用 R42d 锚定 teacher 与 R43 下游 decoder 的 one-way 合并，可把 Fold1
  plan exact 提升到 `991/1209=0.819686`，且成功 joint 比 R42d 高召回基线增加
  4 条；但锚定、危险 fallback 和 Review 均未改善，只证明 teacher-student 边界
  可行，不能冒充 safety 收敛。

### 2. R44 建立真正“先保召回”的五折端到端基线

R44 沿用完全相同的 R42d 五折 checkpoint、候选和结构化 decoder，不重训、不做
阈值扫描；唯一变化是按已确认业务语义启用固定 `NO_EVIDENCE=0.5` 高召回门。
结果如下：

| 指标 | R44 高召回五折 OOF |
|---|---:|
| 结构化方案有输出 | `4234/4236=0.999528` |
| 全量弱 plan-label agreement | `3406/4236=0.804060` |
| reachable plan exact | `3406/4028=0.845581` |
| 成功对象锚定 exact | `1585/2017=0.785821` |
| 成功对象 anchor+plan joint | `1255/2017=0.622211` |
| 正向 NO_EVIDENCE anchor+plan joint | `192/299=0.642140` |
| 正向业务联合 exact | `1447/2316=0.624784` |
| strict full exact | `28/103=0.271845` |
| 明确 fallback 严格状态正确 | `28/101` |
| 明确 fallback 危险自动非 ABSTAIN | `68/101` |
| 真值未知 Review 自动非 ABSTAIN | `1608/1819` |

R44 将全量弱 plan exact 从 R42d 正式安全门下的 `46.27%` 恢复到 `80.41%`，证明
当前联合模型已经能够在高召回模式下输出完整 PlanCandidate，且主要问题不再是
完整 plan scorer 或候选覆盖。但 strict 仍为 `28/103`，正向业务联合 exact 仍为
`62.48%`，并存在 68 条已知危险自动输出；因此正式结论是
`COMPLETE_RESEARCH_HIGH_RECALL_NO_GO`，不是安全发布能力。

下一步只处理锚定 outcome safety 与 unknown Review gate：同一模型必须区分
`SUCCESS`、正向 `NO_EVIDENCE -> KEEP_SWSD`、明确失败 `ABSTAIN -> fallback`
和 Review。Road/plan decoder 不得反向修改锚定，不再继续优化局部 Road scorer。

主要工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r43_global_attribution_20260803/`；
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r43_gradient_isolated_anchor_fold1_20260803_seed_20261630/`；
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r43_teacher_student_merge_fold1_20260803/`；
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r44_high_recall_oof_20260803/`。

以上均为 ignored research output，不接生产；AdvanceRight 继续后置，Movement 关闭。

## 2026-08-03：T032-R45a 锚定 outcome 跨 Case 人工裁决准备包

R44 已证明完整 PlanCandidate 的高召回链路成立，但 1,819 个普通 Segment 的
锚定业务真值仍未知，其中 1,608 个被高召回模式自动输出。历史 M177–M186 安全
实验还表明：继续叠加同类局部置信度门即使做到零观察危险，也只能接受
`66/3125=0.021134`。因此 R45 不再新增相似 scorer，先补齐能区分
`SUCCESS / PROVEN_NO_EVIDENCE / AMBIGUOUS / CANDIDATE_MISSING` 的业务监督。

首先审计旧 v269 Phase 1 是否可直接复用。结果是：30/30 sample ID、candidate
IDs 和输入文件哈希仍一致，但当前 v339 的 object/candidate 结构特征 30/30 已
变化；另有 4/30 的 status 已在后续监督中补齐。按“候选、输入哈希、局部结构证据
均一致才允许复用”的既定规则，旧 CSV 不再继续填写，也不把旧模型排序当真值。

新 Phase 1 从当前 R43 anchor attribution、R44 business OOF 和 v339 anchor store
联合生成，按 6 个正式 T10 Case 每 Case 4 个 anchor 分层抽样：

| 项目 | 数量 |
|---|---:|
| 待裁决 SWSD 语义路口 | `24` |
| 覆盖正式 T10 Case | `6` |
| `ANCHOR_OUTCOME_UNKNOWN` | `24` |
| `SUCCESS_OBJECT_UNKNOWN` | `0` |
| R44 预测 `SUCCESS` | `7` |
| R44 预测 `NO_EVIDENCE` | `11` |
| R44 预测 `ABSTAIN` | `6` |
| 直接影响未知真值普通 Segment | `94` |
| 其中 R44 自动非 ABSTAIN | `69` |

模型预测只用于选取跨 Case、高影响和不同 outcome 的对象，不是标签，也不进入
人工答案。每个 Case 生成一个只读 GeoPackage，包含 SWSD 语义路口、直接受影响
的冻结 T01 Segment、RCSD candidate Node 与 Road。6 个包均为 EPSG:3857，几何
原样复制，`topology_changed=false`、`silent_fix=false`，所有请求对象均找到。

CSV 继续使用既有 18 列严格合同，只允许填写最后三列；扩展的 R44 预测分布、
当前监督缺口、input hashes 和 structural member IDs 保留在 JSONL。空白模板以
`require_complete=false` 读取成功，完成裁决数为 0；这只证明作用域和冻结列可被
正式回填器接受，没有写入任何标签。定向合同测试为 `9 passed`。

正式准备工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r45_anchor_outcome_phase1_20260803/README.md`；
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r45_anchor_outcome_phase1_20260803/phase1_anchor_outcome_template.csv`；
- 同目录 `phase1_anchor_outcome_queue.jsonl`、`summary.json` 和 6 个
  `visual_T10_*.gpkg`。

R45 训练任务仍未完成。人工裁决返回后，先生成 label-only overlay 并证明
inference feature store 字节不变，再训练同一模型内的 outcome/Review head 和五折
OOF；不得由 Road/Plan decoder 反向修改锚定。

## 2026-08-03：T032-R45b 同-forward outcome/Review 头 Fold1 canary

为在人工裁决返回前验证网络边界，新增可选 `AnchorOutcomeReviewHead`。它位于 base
锚定与 ordinary carrier 之间，只读取同一次 forward 的锚定 embedding、status
分布、candidate top/margin/entropy、gate、selection success、对象类型和
Node/Road×cardinality 分布，共 368D 推理期证据。它不读取 Road/plan 结果、终态、
人工答案或 Case ID；未知 status 不进入 loss。正向输出必须同时满足原 status 与
outcome head 一致、达到固定阈值，SUCCESS 还必须保持原 selection/gate 成功；任何
不一致或低置信只能变为 Review/ABSTAIN，不能改锚定对象或让 Road decoder 反向
恢复。

为兼容现有 checkpoint，该头默认关闭；启用时增加 65,123 参数，总参数量
30,985,184。canary 从 R42d Fold1 checkpoint 加载全部既有权重，只训练 outcome
头；base evidence stop-gradient。训练使用其余 4 折、固定 24 epoch、LR=`1e-3`、
正向/fallback 阈值均为 `0.5`，不扫描阈值；训练期未知锚定 occurrence 只保留作
Review 评价，不进入 loss。

Fold1 结果：

| 指标 | R44 Fold1 | R45b Fold1 | 变化 |
|---|---:|---:|---:|
| SUCCESS anchor+plan joint | `380` | `380` | `0` |
| 正向 NO_EVIDENCE joint | `47` | `38` | `-9` |
| 正向业务联合正确 | `427` | `418` | `-9` |
| 明确 fallback 危险自动输出 | `21` | `20` | `-1` |
| 未知 Review 自动非 ABSTAIN | `445` | `402` | `-43` |
| 结构化 plan exact | `0.803143` | `0.759305` | `-0.043838` |

anchor outcome occurrence 的已知 exact 为 `1469/1577=0.931516`，但 fallback
类仅 `20/58` 正确，仍有 38 个已知 fallback occurrence 被 head 正向释放；未知
occurrence 中也有 6,145 个被 raw head 正向判断。该结果说明同-forward边界能够
保守减少部分 Review 自动输出，但现有 outcome/fallback 监督无法同时保住正向
NO_EVIDENCE，不能通过“再加一个头”完成安全收敛。正式结论为
`CANARY_NO_GO`，不扩到五折，也不做阈值扫描。

实现与工件：

- `src/rcsd_topo_poc/modules/p05_neural_road_generation/target_a_anchor_outcome_review.py`；
- `src/rcsd_topo_poc/modules/p05_neural_road_generation/target_a_end_to_end_ordinary_set_network.py`；
- `src/rcsd_topo_poc/modules/p05_neural_road_generation/target_a_end_to_end_business_chain.py`；
- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r45_outcome_review_fold1_20260803_seed_20261640/`。

定向 outcome/business/ordinary 测试 `14 passed`；加入四维 Node/Road×cardinality
真实形状回归后，完整 P05 回归 `783 passed, 1 warning`。默认关闭时既有
checkpoint/state dict 不增加参数，不改变 R44 行为。下一步仍是完成 R45a 24 条
人工裁决、生成 label-only overlay，再以相同固定协议重训；若正向
NO_EVIDENCE 仍退化，则 outcome head 路线正式淘汰。

## 2026-08-03：T032-R45c Fold1 锚定推理证据缓存

为避免每次人工标签回填或 outcome head 重训都反复读取城市级 store、重复执行相同
基础网络前向，按 R42d Fold1 checkpoint 固化模型内部锚定证据缓存。一次读取全部
4,236 个普通 Segment，得到 28,496 个 anchor occurrence、4,335 个唯一 anchor；
每个 occurrence 保存 368D `float32` 推理期特征及
`case_key + segment_id + anchor_id + example_fold` identity。

缓存严格不包含标签、status 真值或 RoadGraph 终态输入；标签必须从当次有效的
label-only overlay 按 identity 连接，不能把旧标签固化进特征。缓存同时登记 source
checkpoint 与 anchor manifest 的 SHA-256，任一哈希变化都必须重算，不能跨模型或
跨候选版本复用。本次重载后 feature 完全相等、identity hash 一致、所有特征有限；
`topology_changed=false`、`silent_fix=false`。

工件：

- `outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r45_anchor_evidence_cache_fold1_20260803/anchor_evidence_occurrences.pt`；
- 同目录 `summary.json`。

缓存大小为 42,924,229 bytes，首次城市 store 读取与基础前向耗时 294.095 秒。它只
加速同 checkpoint 下的标签连接、head 重训和评价，不改变 R45b `CANARY_NO_GO`
结论，也不把 24 条尚未返回的人工裁决视为已经完成。

## 2026-08-03：T032-R45d 固定人工 overlay + 缓存训练链路

新增一次性研究 runner
`outputs/_work/p05_neural_road_generation/run_target_a_ordinary_joint_r45_manual_overlay_cached_fold1.py`，
把人工 CSV、既有 label-only overlay、R45c 缓存连接、固定 outcome head 训练和
Fold1 业务评价串成同一条带门禁链路。正式运行必须满足：

- CSV 24/24 完整且冻结列未变化；
- overlay 的 inference feature store 与 v339 源 store 字节一致；
- cache identity、R42d checkpoint SHA-256、anchor manifest SHA-256 全部一致；
- 训练折不包含 Fold1，同一 sample ID 不跨 Case fold；
- 基线必须在同一人工 overlay 下重新评价 R44 Fold1，再与 outcome head 比较；
- epoch、阈值和 promotion gate 固定，不扫描阈值；canary 通过也不声明安全发布。

当前只读 `--preflight` 结果为：缓存门禁全部通过；28,496 个 occurrence 均成功
连接现有 label store，其中 22,910 个已监督、5,586 个未知；人工 CSV 当前为
`0/24`，状态 `WAITING_FOR_MANUAL_ADJUDICATION`，`writes_performed=false`。由于人工
真值尚未返回，本轮没有用虚构答案生成 overlay，也没有启动正式训练。

24 个待裁决 anchor 与缓存 24/24 匹配，且不存在同一 anchor 跨 fold：Fold0–3
各 4 个，Fold4 为 8 个；对应 occurrence 分别为 43、34、54、41、62。每个
Fold0–3 各含 1 个独立 Case，Fold4 含 2 个独立 Case。因此固定 Fold1 canary 会用
其余 5 个 Case 的 20 个裁决 anchor 训练，以 `T10:609214532` 的 4 个 anchor、
34 个 occurrence 做未见 Case 评价；人工投入不会因折分缺口失效。

## 2026-08-03：T032-R45e 人工裁决静态审计索引

为降低 24 条人工裁决反复在 6 个 GeoPackage 中筛选和缩放的成本，生成
`outputs/_work/p05_neural_road_generation/target_a_ordinary_joint_r45_anchor_outcome_phase1_20260803/manual_previews/index.html`，
并为每个 anchor 生成一个局部 EPSG:3857 叠加图。索引覆盖 24/24 anchor、6/6
正式 T10 Case、1,177 条完整 candidate plan ID 和 96 条受影响 Segment 引用。

视图固定使用：灰色冻结 T01 Segment、红色 RCSD candidate Road、蓝色 RCSD
candidate Node、酒红色 SWSD 语义路口；橙色模型选择仅作 context，页面和图片均
明确标注 `not truth`。已抽查 60 候选、无原始 RCSD 候选和 50 候选三种典型视图，
局部范围、对象类型和说明可读。`manifest.json` 记录 queue、6 个 GeoPackage 和
24 张图片哈希；`business_decision_generated=false`、`label_written=false`、
`topology_changed=false`、`silent_fix=false`、`preview_not_training_input=true`。

## 2026-08-03：R45 人工 overlay 与 ARCH-CLOSURE-P0 分层架构收口

### 1. R45 人工裁决已消费，但 outcome head 路线不晋级

用户完成的 24 条锚定裁决按原冻结 CSV 合同进入 label-only overlay：6 条
`SUCCESS_UNIQUE`、18 条 `PROVEN_NO_EVIDENCE`。overlay 未重算任何推理 feature，
feature store 保持字节一致；24 条裁决覆盖 234 个 occurrence，其中训练折 200、
Fold1 目标折 34。

固定 24 epoch、阈值 `0.5` 的 R45 outcome head 结果为：

| 指标 | 同 overlay 的 R44 Fold1 | R45 | 变化 |
|---|---:|---:|---:|
| SUCCESS joint | `380` | `380` | `0` |
| 正向 NO_EVIDENCE joint | `53` | `44` | `-9` |
| 正向自动正确 | `433` | `424` | `-9` |
| 危险 fallback 自动输出 | `21` | `20` | `-1` |
| 未知 Review 自动输出 | `437` | `390` | `-47` |
| structured plan exact | `0.803143` | `0.755170` | `-0.047973` |

减少 Review 和 1 条危险输出的代价是损失 9 条正确正向决定并显著降低完整方案
exact，故 promotion gate 失败，结论为
`REJECT_OUTCOME_HEAD_ROUTE_AND_REDESIGN_ANCHOR_OBJECTIVE`。这不是人工裁决失败；
人工裁决已成为正式 label-only 资产，失败的是局部 outcome head 的模型边界。

### 2. R46/R47 暴露的边界问题

R46 为 focal Segment 增加 Junction-bounded 上下文后，Road、role、ownership 和
完整方案出现局部提升，但危险自动输出从 21 增至 24，40 条明确 fallback 中正确
回退从 18 降至 7；同时仍按 focal Segment 重复打包 Junction 和相邻候选，内存峰值
约 25 GB。该结果不得晋级。

R46 随后确认：同一语义 Junction 在不同 focal Segment forward 中可能得到不同
锚定结果。R47 只做唯一锚定预检，按 `case_key + semantic_junction_id` 规范化
Fold1 的 2,175 次 required-anchor 引用为 1,086 个唯一 Junction：missing=0、
candidate 越界=0、重复结果冲突=0，状态为 847 `SUCCESS`、199
`PROVEN_NO_EVIDENCE`、40 `UNRESOLVED`。该预检在 ARCH-CLOSURE-P0 中直接继承，
没有重复执行。

### 3. ARCH-CLOSURE-P0 的冻结架构和 Gate 0

本次只验证三层边界：

1. Layer A 每个语义 Junction 唯一计算、锁定并广播；本里程碑冻结已有 anchor
   checkpoint，Segment loss 不得回写锚定；
2. Layer B 以普通 Segment 为单元，引用 required anchor、完整 Plan/Road/access/
   break 候选和直接 peer 的静态证据，输出 source 与完整 RoadGraph 业务方案；
3. Layer C 只做直接 Junction 范围的确定性 `ACCEPT/FALLBACK`，不得改 anchor、
   扩候选、改 T01 骨架或递归扩大 fallback。

建立 `JunctionStore/SegmentStore/PlanStore` 后，城市数据只读取一次；4,335 个
Junction、4,236 个 Segment 和 4,236 个 Plan 均以 key 引用。模型输入与训练监督
使用不同数据对象，context terminal field、truth-derived input、T03–T06 终态输入
均为 0。

Gate 0 的 16 项全部通过：Junction 唯一性、required 引用、候选合法性、广播、
Segment 输出唯一性、Road owner 唯一性、终态 mask、两类梯度隔离、Unknown
ABSTAIN、权重/mask、无终态泄漏、一跳 fallback、T01 骨架冻结、无 silent fix 和
CRS/引用/方向/ID 合法。51 个 Case 均为 `EPSG:3857`；Segment 新增、删除、重分配
和 geometry/candidate mutation 均为 0。

### 4. 固定 Fold1 canary 与正式决策

canary 固定 Fold1、seed=`20261650`、4 epoch（2 teacher + 2 free-run）、
LR=`2e-5`、weight decay=`2e-4`、gradient clip=`1.0`，18,676,914 参数；未做
threshold、epoch、seed 扫描，也未增加 post-head、cardinality patch 或 reranker。

| 指标 | 统一基线 | canary | 变化 | Promotion |
|---|---:|---:|---:|---|
| Segment Full Exact | `8/24` | `8/24` | `0` | FAIL |
| Junction Group Exact | `6/18` | `6/18` | `0` | FAIL |
| structured plan exact | `971/1209` | `959/1209` | `-12` | 辅助退化 |
| 正确 KEEP_SWSD | `276` | `294` | `+18` | PASS |
| 正确 USE_RCSD | `139` | `109` | `-30` | FAIL |
| unsafe automatic | `21` | `21` | `0` | PASS，但非生产零危险 |
| Review/unknown automatic | `425` | `414` | `-11` | PASS |
| 10+ Road structured exact | `4/6` | `4/6` | `0` | PASS |
| skeleton mutation / silent fix / hard failure | `0/0/0` | `0/0/0` | `0` | PASS |

24 条严格可评价 Segment 的 Full Exact 结果与基线逐条相同。决策迁移中有 96 条
基线 `USE_RCSD` 被改为 `KEEP_SWSD`；structured plan 有 45 条由错变对、57 条
由对变错，5–9 Road exact 从 `22/41` 降到 `17/41`。因此 loss 从
`1.076975` 降至 `0.717193` 不能替代主指标结论，正式判定
`ARCH_CANARY_NO_GO`，严格五折未启动。

### 5. 性能、监督边界与后续约束

引用式数据管道的结构目标成立：Junction 一次性编码吞吐 843.79 Junction/s；
固定批 forward 为 701.22 Segment/s；真实最大对象含 636 Road、43 required
Junction，forward 输出有限。canary 峰值 RAM 为 5,069,647,872 bytes（约
4.72 GiB）、VRAM 为 1,884,841,984 bytes（约 1.76 GiB），R46 约 25 GB 的重复
打包问题已结构性消除。完整 P05 回归为 `783 passed, 1 warning`。

当前锚定 label store 有 5,148 个 Junction 样本，其中 4,338 个有状态监督、
3,496 个有 candidate/member 对象监督；权重 0.7 的规则重放 Silver 为 4,364 条，
权重 1.0 为 784 条。现有监督足以在不新增 Case 的前提下研究唯一 Junction 单元
模型，但严格端到端评价仍只有 24 个 Segment、18 个 Junction group，且 10+ Road
严格可评价为 0。该缺口不影响本次 NO-GO，却限制下一架构的生产能力判断。

完整规则策略继续只作离线 Silver、候选、Oracle 和对照。canary 可证明正确的正向
自动决定为 `403/1209`（294 KEEP、109 USE）；强制自动输出 `1074/1209` 中仍含
21 个已知危险和 414 个 unknown，不能称为安全覆盖。由于本 canary 在最终
Road/Node 物化、完整 hard QA 和 rule fallback 之前已经 NO-GO，网络 forward 与
完整规则链路没有同口径性能结论。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_arch_closure_p0_20260803/`；
- `outputs/_work/p05_neural_road_generation/target_a_arch_closure_p0_fold1_canary_20260803_seed_20261650/`。

下一步不得继续同类局部 canary。引用式 Store、Gate 0、统一 evaluator 和直接
Junction 协调器保留；必须重新选择规则 fallback、独立 Gold、调整 Junction/Segment
模型边界或结束当前网络结构。未经该方向确认，不启动下一训练。

## 2026-08-04：T032-UNIQUE-JUNCTION-P1 固定 Fold1 canary

用户选择在 ARCH-CLOSURE-P0 `NO_GO` 后调整 Junction/Segment 模型边界：先把
Layer A 改为真正以唯一 `case_key + semantic_junction_id` 为 forward 和监督单元，
通过后再训练只读取锁定 OOF 锚定的普通 Segment 完整 Plan。本轮未恢复 T03–T06
终态推理输入，未修改 T01 骨架，AdvanceRight/Movement 保持关闭。

固定协议为 Fold1 开发 canary、seed=`20261660`、8 epoch、LR=`2e-5`、weight
decay=`2e-4`、gradient clip=`1.0`、gate threshold=`0.5`。模型从对应 outer-fold
锚定 checkpoint 暖启动，新增无向直接依赖 ego graph、完整 member-set loss 和
Junction 结构证据；参数量 `19,422,227`。未扫描 epoch、threshold 或 seed，未新增
局部 safety head、cardinality patch 或 reranker。输入 feature/label 继续物理分离，
1,359 个 Fold1 Junction 均只输出一次，重复输出为 0。

| 指标 | 同 evaluator 基线 | P1 canary | 变化 | Gate |
|---|---:|---:|---:|---|
| 完整锚定业务 exact | `908/1145=0.793013` | `921/1145=0.804367` | `+13` | PASS |
| Gold 完整锚定业务 exact | `129/159=0.811321` | `127/159=0.798742` | `-2` | FAIL |
| Silver 完整锚定业务 exact | `779/986=0.790061` | `794/986=0.805274` | `+15` | 辅助提升 |
| SUCCESS 完整对象 exact | `791/961=0.823101` | `782/961=0.813736` | `-9` | FAIL |
| 正向 NO_EVIDENCE exact | `32/47=0.680851` | `29/47=0.617021` | `-3` | FAIL |
| dangerous automatic | `12` | `13` | `+1` | FAIL |
| unknown automatic | `165` | `169` | `+4` | FAIL |
| 唯一 Junction 重复输出 | `0` | `0` | `0` | PASS |

P1 把输出向高召回移动：SUCCESS `928→990`、ABSTAIN `237→198`、NO_EVIDENCE
`194→171`。共有 42 条完整业务结果由错变对、29 条由对变错，但 SUCCESS 对象有
27 条由对变错、18 条由错变对。Gold 分层中 T03 `1/12→3/12`、T04_Error
`62/63→63/63`，但 T03_Error `51/51→50/51`、T10 Gold `15/26→11/26`；提升
集中在 Silver，不能用总体 `+13` 掩盖 Gold 与安全退化。

训练折 3,789 个 Junction 中，Gold 624、Silver 3,165；状态监督分别为 613 与
2,580，完整对象监督分别只有 121 与 2,414。即使样本权重为 1.0/0.7，完整对象
loss 的有效监督仍主要来自 Silver。这是本次“状态召回改善、Gold/对象/安全退化”
最明确的监督失配；它具体指向缺少足量独立 Gold 完整 Node/Road anchor 集合，而
不是泛泛的 Case 数不足。按固定 Promotion Gate，结论为
`UNIQUE_JUNCTION_CANARY_NO_GO`，不进入五折，不生成新的 OOF `JunctionStore`，
也不启动 Layer B Segment Plan。

资源结果：数据读取 11.54 秒，8 epoch 训练 96.84 秒，流式 collate 50.70 秒、
GPU forward/backward 43.27 秒，约 313.02 Junction/s；峰值 RAM 3,819,712,512
bytes（约 3.56 GiB），峰值 VRAM 4,360,793,600 bytes（约 4.06 GiB）。不存在 R46
约 25 GB 的重复动态子图问题；本次失败属于目标监督与泛化，不是 IO/内存架构。
新增唯一 Junction 合同/评价测试与既有 P05 测试合并回归为
`786 passed, 1 warning`；warning 仍是既有 Transformer nested-tensor 提示。

正式研究工件：

- `outputs/_work/p05_neural_road_generation/target_a_unique_junction_p1_fold1_20260804_seed_20261660/`；
- `outputs/_work/p05_neural_road_generation/target_a_unique_junction_p1_fold1_20260804_seed_20261660/manifest.json`；
- `outputs/_work/p05_neural_road_generation/target_a_unique_junction_p1_fold1_20260804_seed_20261660/promotion_decision.json`。

## 2026-08-04：T032-UNIQUE-JUNCTION-GOLD-PHASE1 标注包冻结

用户在 UNIQUE-JUNCTION-P1 `NO_GO` 后明确授权：允许在现有 Case 内补充/复核
完整 Node/Road anchor Gold。本阶段没有新增 Case、没有训练、没有修改 T01–T12、
正式接口、几何或拓扑；目标只是在人工开始前冻结独立 Gold 队列和回填合同。

选样先限定为 6 个现有 T10 Case、`sample_weight=0.7`、状态为 SUCCESS 且完整
candidate 对象可达的 Silver Junction，再要求该 Junction 已存在冻结普通 Segment
直接引用。分层内只使用固定
`SHA256(seed|case_key|anchor_id|sampling_stratum)` 排序，不读取 UNIQUE-JUNCTION-P1
或任何其他模型的预测、分数、错误、阈值、release 结果。Silver preferred 只用于
确定 Node/Road 和集合大小分层，不写入人工模板或 QGIS 工程。

冻结结果如下：

| 范围 | 数量 |
|---|---:|
| T10:1885118 / 609214532 / 605415675 / 706247 | 各 16 |
| T10:74155468 / 991176 | 各 8 |
| Node 完整集合 | 22 |
| 单 Road | 20 |
| 2–3 Road | 21 |
| 4–9 Road | 16 |
| 10+ Road | 1 |
| 总 anchor / candidate 组合 | 80 / 4,674 |

新回填合同使用 `SUCCESS_CONFIRMED / PROVEN_NO_EVIDENCE / AMBIGUOUS /
CANDIDATE_MISSING`。`SUCCESS_CONFIRMED` 可保留多个等价正确的完整 candidate，
并要求 preferred 必须属于 acceptable 集合；多个 candidate 之间用 `;` 分隔，
candidate 内部 Road/Node bundle 的 `|` 不拆分。严格校验拒绝修改冻结字段或行哈希、
越界 candidate、重复 candidate、缺失证据说明、非 SUCCESS 错填 candidate、陈旧
sample ID 和覆盖既有权重 1.0 Gold。空白模板以 `require_complete=false` 读回为
0 条有效答案，证明人工字段当前确实为空；定向回归为 `12 passed`。

QGIS 工件包含 6 个 Case 工程、1 个总工程、6 个预览和只读 candidate/worklist/
decision 索引。7/7 工程均能读回，图层无 invalid datasource，文件 datasource
全部为相对路径；空间图层统一 `EPSG:3857`。GPKG 几何从 T01/原始 RCSD 原样复制，
未做坐标变换、拓扑修改或 silent fix。PyQGIS 生成进程退出时仍会输出只读 GPKG
provider 清理告警，但独立工程读回、feature count、相对 datasource 与预览均通过；
该告警不作为业务失败，保留为一次性 runner 清理噪声，不进入训练或正式入口。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_unique_junction_gold_phase1_20260804/`；
- `anchor_gold_phase1_template.csv` 是唯一人工答案文件；
- `anchor_gold_phase1_all_cases.qgz` 是总览工程；
- `qgis_project_qa.json` 记录 QGIS 3.40.14 读回和 CRS/datasource 门禁。

当前状态为 `WAITING_FOR_MANUAL_ADJUDICATION`。人工返回前不启动训练；返回后先
生成 label-only overlay 并证明 inference feature 字节不变，再以冻结 80 条队列和
Case-grouped 隔离设计一次 Gold-first canary。不得把本批标注用于 Fold1 后验选样、
阈值/epoch/seed 扫描或新的局部 head。

新增回填合同后的完整 P05 回归为 `795 passed, 1 warning`；唯一 warning 仍为
既有 Transformer nested-tensor 提示。

## 2026-08-04：T032-UNIQUE-JUNCTION-GOLD-PHASE1 回填与固定 canary

人工返回的 80/80 行先经过严格规范化。`manual_preferred_candidate_id` 有 27 行带
误加前缀 `|`，规范化器只删除前导分隔符，不改变任何 ID，并保存
`anchor_gold_phase1_template.pre_normalization.csv`。正式 CSV SHA256 为
`7d1a9eb69931a59f78b6d523d4b7e4398d887fdac19f24d74f0219a757cf687a`；最终
裁决分布为：`SUCCESS_CONFIRMED=77`、`CANDIDATE_MISSING=1`、`AMBIGUOUS=1`、
`PROVEN_NO_EVIDENCE=1`。77 条成功裁决都有完整冻结 `NODE:` 或 `ROAD:` candidate，
没有覆盖既有 Gold。`T10:609214532 / 604202863` 的人工 Road 组合
`5396397344754048|5396397344754037` 不在冻结 candidate 中，严格保留为
`CANDIDATE_MISSING`，没有把正确业务对象静默替换成近似候选。

label-only overlay 写入
`target_a_unique_junction_gold_phase1_overlay_20260804/anchor_store`，80 个样本恰好
80 个标签变化；`anchor_features.jsonl` 仍为 199,553,387 bytes，SHA256
`78a3f17c0d9bc47bdd516bfaf5544e7e96db8ec5eb3a9ee99b578e6b186376a6`，与输入逐
字节一致。回填后 77 条具有 candidate/object 监督，78 条为 positive gate，2 条为
Segment fallback gate；T01 骨架、几何、拓扑均未改变，`silent_fix=false`。

### 固定 Gold-first 协议

只执行一次 Fold1 canary，不恢复局部参数搜索。模型结构、base checkpoint、
seed=`20261660`、8 epoch、LR=`2e-5`、weight decay=`2e-4`、gradient clip=`1.0`、
gate threshold=`0.5` 与 UNIQUE-JUNCTION-P1 相同，参数量仍为 `19,422,227`。训练折
原始 Gold/Silver 为 `688/3101`；固定将两层的总 loss 质量设为 `0.5/0.5`，对应
Gold/Silver 单样本权重 `2.7536337209/0.6109319574`，总均值保持 1。没有扫描
weight、epoch、threshold 或 seed，没有新增 head/reranker。80 条新 Gold 由冻结
Case fold 分为训练 64、Fold1 留出 16，验证集始终使用原始标签与权重。

| 指标 | 冻结基线 | Gold-first | 变化 |
|---|---:|---:|---:|
| 全监督完整锚定业务 exact | `907/1145` | `919/1145` | `+12` |
| 全 Gold 完整锚定业务 exact | `139/175` | `139/175` | `0` |
| SUCCESS 完整对象 exact | `789/959` | `785/959` | `-4` |
| 正向 NO_EVIDENCE exact | `32/47` | `30/47` | `-2` |
| dangerous automatic | `13` | `14` | `+1` |
| unknown automatic | `165` | `170` | `+5` |
| 新 Phase1 Fold1 完整业务 exact | `10/16` | `11/16` | `+1` |
| 新 Phase1 Fold1 SUCCESS 对象 exact | `10/14` | `11/14` | `+1` |

迁移审计显示，新 Phase1 留出 Gold 有 1 条对象修复、0 条回归；其他旧 Gold 有
3 条修复、4 条回归，合并后全 Gold 净变化为 0；Silver 有 33 条修复、21 条回归，
贡献全部 `+12` 总体净改善。状态迁移包含 33 条 `ABSTAIN→SUCCESS`，同时造成已知
危险和 unknown 自动项增加。80 条队列本来从 Silver SUCCESS 对象分层抽样，最终
只有 1 条 `PROVEN_NO_EVIDENCE`，且位于 Fold3；Fold1 新留出集中没有新增
NO_EVIDENCE。因而本批数据证明 SUCCESS 完整对象监督可学，但不能证明当前结构已
获得 NO_EVIDENCE 与安全泛化能力。

Promotion Gate 仅“总体业务 exact 提升”和“一 Junction 一输出”通过；Gold 提升、
SUCCESS 对象非退化、NO_EVIDENCE 非退化、危险非增加、unknown 非增加全部失败。
正式结论为 `UNIQUE_JUNCTION_CANARY_NO_GO`。不启动五折、OOF `JunctionStore`、
Layer B Segment Plan 或第二组 Fold1 调参。该结果淘汰的是当前唯一 Junction 结构加
SUCCESS 偏置 Phase1 Gold 的路线，不等同于否定 Target A 或神经网络整体。

资源结果：数据读取 11.52 秒、8 epoch 训练 96.92 秒、总 wall 139.08 秒；吞吐约
312.77 Junction/s，峰值 RAM 3,839,373,312 bytes、峰值 VRAM 4,360,793,600 bytes。
运行工件：

- `outputs/_work/p05_neural_road_generation/target_a_unique_junction_gold_phase1_20260804_r1/`；
- `outputs/_work/p05_neural_road_generation/target_a_unique_junction_gold_phase1_overlay_20260804/`；
- `outputs/_work/p05_neural_road_generation/target_a_unique_junction_gold_first_fold1_20260804_seed_20261660/`。

回填、overlay 与固定 canary 合入后的完整 P05 回归为 `796 passed, 1 warning`；唯一
warning 仍为既有 Transformer nested-tensor 提示。

## 2026-08-05 方案 A：路口强/弱监督联合训练边界

用户正式选择方案 A：五个单点目录形成的强 Gold 按 Case 总权重 `1.0`，T10
可追溯路口弱监督权重 `0.7`；两者允许通过字段 mask 更新同一 raw-inference
encoder。Case family、目录来源和强/弱来源类别只用于 cohort audit 与分层指标，
不得进入推理特征。联合阶段后执行强 Gold consolidation，checkpoint 选择同时报告
Gold validation 与 T10 validation；两套冻结 test 均保持关闭。

此前 `JUNCTION_FIRST_CANARY_NO_GO` 关于“下一架构只能使用独立
auxiliary/teacher adapter”的限制被本次用户裁决取代；其样本分布风险和当时指标仍
作为历史实验事实保留。当前 v5/v6 的联合训练、v7 consolidation 与 v10 break
projection 仅作为探索基线，补齐来源/权重/test 隔离审计和双 validation 门禁后才可
成为 T037-R2 合规 canary。

对 v10 的强 Gold validation 做了不读取 test 的 surface 表征审计：56 个有 surface
Gold 的对象中，当前自由像素输出 mean IoU=`0.481000`、IoU `>=0.90` 为 `1/56`；
Gold mask 自身的行/列区间交集表示 oracle mean IoU=`0.977271`、IoU `>=0.90`
为 `51/56`。这说明 surface 的主要瓶颈不是目标几何无法表达，而是当前统一自由像素
decoder 没有显式学习 T03/T04 虚拟路口面的边界结构。下一固定 canary 改为结构化
surface boundary decoder，不继续扫描同构 epoch、threshold 或 seed。

### v11 结构化 surface boundary canary

v11 固定继承 v10、seed=`20261666`、16 epoch，只训练新增的 `10,054` 个 boundary
decoder 参数，其余 `11.32M` 参数全部冻结；强 Gold train 中 surface 监督 `272` 条，
validation `105` 条，test 未加载。cohort audit 复核 train/validation 有效权重=
`490/105`、跨 split group=`0`、推理 feature 中来源字段=`0`。

最优 epoch 13 的 surface mean IoU=`0.457394`、IoU `>=0.90`=`1/56`，均未超过
v10 的 `0.481000` 与 `1/56`；完整路口 proxy 仍为 `1/105`。结论为
`STRUCTURED_SURFACE_BOUNDARY_CANARY_NO_GO`，禁止继续扫描该结构的学习率、epoch、
threshold 或 seed。

失败归因不是边界表示无表达能力，而是 boundary decoder 只读取 v10 的低清 surface
logit 与 DriveZone。当前原始 Road/Node token 先汇聚到 `32×32`，在 512m 视野下约
为 16m/格；Gold surface 中位宽高约 36m，仅覆盖约 2–3 个低清格。已有高分辨率
refinement 又看不到高分辨率 Road/Node/RCSDIntersection 位置。因此下一固定 canary
只验证“raw geometry role 高分辨率栅格 + residual surface decoder”，不继续修改
boundary head。正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v11_structured_surface_boundary/summary.json`；
- checkpoint SHA256
  `f589c48cb8d3cf472f610c9e037dc09273d78377f0edfd0012e7fb6bea8073dc`。

### v12 high-resolution raw geometry surface canary

v12 继续固定 v10 与 seed=`20261666`，只训练 `38,609` 个高分辨率 residual
参数。新增输入是在现有 4m surface 网格上直接 rasterize 的七类 raw geometry role；
不包含 label、route、family 或旧策略终态，test 未加载。epoch 0 完整复现 v10；最优
epoch 7 的 surface mean IoU=`0.482840`，但 IoU `>=0.90` 仍为 `1/56`，完整路口
proxy 仍为 `1/105`。按预设的“双指标必须同时提升”门禁，结论为
`HIGHRES_RAW_GEOMETRY_SURFACE_CANARY_NO_GO`，不继续扫描同结构参数。

v11/v12 连续 NO_GO 后，停止 surface 单头路线。完整路口当前同时受业务状态 chain、
完整对象集合、surface 与拓扑制约；继续单独提高 mean IoU 即使成功也不能形成完整
业务结果。下一架构回到联合 decoder：把训练集中 `19` 个完整业务状态 tuple 与
`18` 个按字段值与 mask 去重、带显式 wildcard 的部分监督 template 建成有限 plan
catalog；旧 identifiability 工件中的 `37` 不是去重后的 plan 类别数。wildcard 表示
真值未知并强制非自动发布，不映射成 `N/A`、KEEP 或失败。plan loss 与现有字段 mask
共同训练共享 encoder，decoder 选择一个一致业务 plan，再条件化完整对象、surface
与拓扑输出。正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v12_highres_raw_geometry_surface/summary.json`；
- checkpoint SHA256
  `2a4e89d847eeb9f5b9fde0a30bcbf6ba0154c8a086e3c0df8bea360cc776e104`。

### v13 mask-aware business plan catalog canary

v13 从 joint train 建立 `37` 个 plan：`19` 个完整 tuple、`18` 个显式 wildcard
template。只训练新增的 `115,237` 个 plan-head 参数；v10 encoder、对象、surface、
拓扑和 plan-condition 均冻结。所有动态子图只编码一次，16 epoch 在缓存 320D
embedding 上完成；test 未加载。

最优 epoch 15 相对 v10 factorized state heads：

| validation | v10 状态整链 exact | v13 plan exact | wildcard/ABSTAIN |
|---|---:|---:|---:|
| 强 Gold | `0.419048` | `0.514286` | `0.514286` |
| T10 弱监督 | `0.451673` | `0.747212` | `0.330855` |

两套 validation 同时提升，对象集合、surface 和拓扑保持 v10，强 Gold 完整路口
proxy 仍为 `1/105`。结论为 `BUSINESS_PLAN_CATALOG_CANARY_GO`：有限 plan catalog
和 wildcard 安全语义成立，但尚未证明完整路口 GO。下一阶段按方案 A 让 plan loss、
字段 mask、对象集合与拓扑共同 fine-tune raw-inference encoder，再执行强 Gold
consolidation；冻结 test 继续关闭。正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v13_business_plan_catalog/summary.json`；
- catalog SHA256
  `e54a0a07ac34fa588f6e14aaeb2a328a679246835d188e742f0cb0ec8fcc98db`；
- checkpoint SHA256
  `08573e0cf054ec46724f326e548f4b164d8b991197584491b1cfb790dff45d0e`。

### v14/v15 plan joint fine-tune 与强 Gold consolidation

v14 固定 4 epoch 对强 Gold `497` + T10 `3148` 个 train 路口更新全部
`11.45M` 参数；v15 再固定 4 epoch 只用强 Gold train consolidation，同时监控两套
validation。test 未加载。最终相对 v13：强 Gold 完整 proxy=`1/105→2/105`、
surface IoU `>=0.90`=`1/56→3/56`，但强 Gold 对象 exact=
`0.415094→0.339623`、拓扑=`0.425532→0.340426`，T10 对象=
`0.407295→0.379939`。结论为 `PLAN_JOINT_CONSOLIDATION_CANARY_NO_GO`。

训练历史进一步证明这不是 checkpoint 选择偶然：v14 四轮强 Gold 对象最高仅
`0.358491`；v15 第 4 轮虽达到强 Gold 对象=`0.433962`、拓扑=`0.425532`，T10
对象却降到 `0.364742`，且完整 proxy 回落到 `1/105`。因此停止全共享 encoder 的
loss/epoch 调整，保留 v13 plan + v10 其余 decoder 为正式开发基线。下一步只允许
one-way specialist merge：专用分支可读取冻结共享表示，但其梯度和参数不得反向改变
plan、对象、拓扑或锚定状态。正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v14_v15_plan_joint_consolidation/summary.json`；
- v14 checkpoint SHA256
  `46c9e8e27438ad8e97e192b0ce878f079e128d63fbd083b788b1ec4aac558172`；
- v15 checkpoint SHA256
  `2227625bf686fed9d93c4ec86e0d83dd906835847b22cf379860f465f0b21368`。

### v16 one-way surface merge

v16 只把 v15 的 surface specialist 参数单向合入 v13，其余参数逐 key 保持不变。
强 Gold surface mean IoU 从 `0.481000` 升到 `0.487603`，但 IoU `>=0.90`
从 `1/56` 降为 `0/56`，完整路口 proxy 从 `1/105` 降为 `0/105`；业务状态、
对象和拓扑保持不变。结论为 `SURFACE_ONE_WAY_MERGE_NO_GO`，进一步证明 surface
单头无法形成完整路口收益。checkpoint SHA256：
`230111f5e12dc35f9ae0cc4dfb13f33dacbfcf70b95eef91e64b9e4a66018402`。

### v17–v19 显式 Road/Node 图证据

v17 在 v13 上加入 SWSD/RCSD arm 匹配、Road–Road 关系和 member graph adapter。
T10 validation 对象 exact 从 `0.407295` 大幅升到 `0.745440`，状态链从
`0.747212` 升到 `0.769517`；强 Gold 对象却从 `0.415094` 降到 `0.358491`，
拓扑从 `0.425532` 降到 `0.382979`。结论为
`MEMBER_GRAPH_ADAPTER_CANARY_NO_GO`。selected checkpoint SHA256：
`d1dacc1cd6b0e0ada2feba7bbc56ddaba2423c3fcca00d3640c50a3645201c17`。

v18 只用强 Gold 训练同一 Road graph teacher，强 Gold 对象 exact 只能追平
`0.415094`，拓扑降为 `0.382979`、状态链降为 `0.476190`。v19 再从原始
`rcsdnode.gpkg/rcsdroad.gpkg` 加入精确 Node–Road endpoint incidence：602 条强
监督中 591 条存在 incidence，累计 51,782 条有向边；仅 5 个 Node member 未解析、
Road member 全部解析，且未读取 truth/terminal 字段。最优结果仍为对象
`0.415094`、拓扑 `0.382979`、状态链 `0.495238`。这排除了“只缺一类端点关系
输入”的解释。v18/v19 结论分别为 `STRONG_GOLD_GRAPH_TEACHER_CANARY_NO_GO` 和
`STRONG_GOLD_NODE_ROAD_GRAPH_CANARY_NO_GO`。

### v20–v25 完整集合 decoder 与联合路由审计

v20 对现有候选空间做 label-only 可表达性审计。强 Gold 366 条完整 Node/Road
对象真值中，旧单一 candidate bundle 只能表达 265 条（`72.40%`），原子 member
集合可表达 351 条（`95.90%`）；train/validation/test 分别为
`247/260`、`53/53`、`51/53`。因此 validation 的正确集合并未被候选空间排除。
但 v13 member 排序在 Gold cardinality Oracle 下也只能得到 `27/53=0.509434`，
模型自身 cardinality 下为 `20/53=0.377358`，说明问题同时包含 member 判别与集合
终止，而不只是 candidate bundle 覆盖。

v21 新增显式 STOP 的自回归 structured set decoder，采用 permutation-aware
teacher forcing，只训练新增的 926,402 个 decoder 参数。30 epoch 最优 epoch 8
的强 Gold 对象与拓扑仍为 `0.415094/0.425532`，仅追平 v13；结论为
`STRONG_STRUCTURED_SET_DECODER_CANARY_NO_GO`。checkpoint SHA256：
`8198bfd2e40a4f4dfa9feeffc37f7a2975cb4c0eca71d932043cab07f1194bc1`。

v22 用同一 validation 对自由推理和 Gold 业务状态条件做 Oracle 对比。v21 自由
对象 exact=`0.415094`，强制正确业务状态后仅为 `0.433962`，只增加 1/53；action
正确时对象 exact=`0.531250`，action 错误时仍有 `0.238095`。因此失败不能简化为
先修业务分类或先修对象 decoder，二者均需改变。

v23 首先用 2,791 条 train/validation T10 member 弱监督与 300 条强 Gold member
监督训练 decoder，再用强 Gold 收口。预训练最优 epoch 2：T10 对象 exact=
`0.744681`、强 Gold=`0.452830`、强 Gold 拓扑=`0.361702`；强 Gold fine-tune
后对象降为 `0.396226`，拓扑为 `0.446809`。T10 能学习集合结构但不能可靠迁移到
强 Gold，结论为 `WEAK_PRETRAIN_STRONG_FINETUNE_CANARY_NO_GO`。

v24 按 Gold action 分别训练 `direct_relation`、`group_existing_rcsd_nodes` 和
`split_rcsdroad_generate_rcsdnode` 三个 Oracle 专家。修正首轮审计脚本漏加载 v13
baseline checkpoint 后，以相同 seed 重跑；三个专家对象 exact 分别为
`10/16`、`2/5`、`14/32`，合计 `26/53=0.490566`，仍低于预设 0.60 门槛。
`direct` 不超过 v13，`group/split` 有局部收益但不足以支持 mixture-of-experts
实现，结论为 `ACTION_EXPERT_ORACLE_CANARY_NO_GO`。

v25 复核同一 v13 checkpoint 在全 validation、仅对象监督和按 action 分批三种
batch 组成下的输出。不同比较均为对象集合差异 0、business plan 差异 0，object、
cardinality、member 最大 logit 浮动分别不超过 `6.86e-6/7.16e-6/9.30e-6`；
结论为 `BATCH_INVARIANCE_AUDIT_GO`。v24 首轮异常由审计脚本漏加载 checkpoint
造成，不是模型 padding 或 batch 污染，首轮错误对照不进入正式结论。

### v26 encoder + business trunk + structured decoder 联合收口

v26 是当前架构最后一个关键假设检验：不再冻结 encoder，只冻结已稳定的 T07
Step1/Step2 边界和 surface 生成器；开放 raw geometry、candidate/member encoder、
业务 trunk、plan heads、structured set decoder 与 break heads，共 10,901,836 个
可训练参数。先用强/弱 member 监督联合预训练 3 epoch，再用强 Gold 收口 12 epoch；
test 始终未加载。

联合预训练最优 checkpoint 的强 Gold 状态链=`0.641509`、action=`0.830189`、
final state=`0.905660`，明显超过 v13；但对象 exact=`0.283019`、拓扑=
`0.255319`、完整 proxy=`0/53`。强 Gold 收口按对象优先选择的 checkpoint 得到对象
`0.433962`、拓扑 `0.468085`，但状态链降到 `0.333333`、final state 降到
`0.495238`，完整 proxy 仍为 `1/105`。训练历史中存在状态链约 0.66、对象约 0.40
的点，但没有 checkpoint 能同时超过 v13 的状态链、对象和拓扑。

结论为 `JOINT_ENCODER_STRUCTURED_DECODER_CANARY_NO_GO`。这不是 epoch 或阈值
未收敛，而是当前共享表示存在可重复的任务梯度冲突：业务状态优化损害完整对象集合，
对象集合优化又损害业务链。停止当前架构的 seed/epoch/loss/head、Road graph、
action expert 和 threshold 扫描；冻结 test 不得用于选择下一架构。

当前正式开发基线仍为 v13 的 business plan checkpoint，v16–v26 均不得作为发布
模型。下一架构必须同时满足：

1. 业务证据 encoder 与 Node/Road 对象 encoder 参数隔离，对象 loss 不反向改写
   T07/T03/T04/T05 关键业务状态；
2. 业务状态只以 one-way 条件进入完整对象与 break decoder，但对象方案仍是神经
   系统输出，不恢复旧规则策略；
3. 对象 encoder 直接使用真值无关的原始 Road/Node endpoint incidence、arm 与
   相对几何，并以完整连通子图而非独立 object/cardinality 为训练单位；
4. 强 Gold 与 T10 弱监督使用独立 teacher adapter 或 source-specific normalization，
   推理期不输入 Case family/source，避免 v17/v23 已证实的域迁移冲突；
5. 进入下一次训练前先以强 Gold train/validation 证明 plan candidate 的开发集
   可辨识性；未达到预设门槛不读取冻结 test。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v17_member_graph_adapter/summary.json`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v19_strong_gold_node_road_graph/summary.json`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v20_structured_decoder_audit/summary.json`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v22_business_route_oracle_audit/summary.json`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v24_action_expert_oracle/summary.json`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v25_batch_invariance_audit/summary.json`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v26_joint_encoder_structured_decoder/summary.json`；
- v26 checkpoint SHA256
  `fb6c9e6e5c0bb29540e87b9fd482fbb294b20fe537754d2f79410623e72f2b8e`。

### v27 参数隔离的 one-way 对象分支

v27 按 v26 确认的边界实现独立 Node/Road 对象 encoder：业务分支继续加载并冻结
v13 checkpoint；对象分支独立读取原始几何、candidate/member 和精确 Node–Road
endpoint incidence，经独立 Set/Graph Transformer 输出对象、member、cardinality、
自回归 STOP、拓扑和 break 方案。业务 plan 仅以 stop-gradient 的 one-way 条件进入
对象分支，因此对象 loss 不能反向修改 T07/T03/T04/T05 业务状态。模型总参数
15,370,818，其中对象分支可训练参数 3,918,779。训练只使用 247 条强 Gold train，
验证使用 53 条强 Gold validation；test 未加载。

固定 24 epoch、seed=`20261727` 的最佳 epoch 为 9。完整对象集合 exact 仍为
`22/53=0.415094`，只追平 v13；拓扑 exact 从 v13 的 `0.425532` 降为
`0.361702`。冻结的全量 validation 业务状态链保持 `0.514286`，参数隔离和单向条件
边界通过，但对象 exact 未达到预设 `0.60` 门槛，结论为
`ONE_WAY_OBJECT_BRANCH_CANARY_NO_GO`。

该结果排除了“仅因共享 encoder 梯度冲突而无法学习完整对象集合”的解释：梯度冲突
是真实问题，但不是唯一瓶颈。即使对象分支参数完全隔离、正确解在 validation
member 空间 `53/53` 可表达、且 591/602 个样本已具备原始 Node–Road incidence，
当前独立对象表示仍不能学会完整 Road/Node 组合与拓扑。停止该结构的 hidden size、
epoch、seed 和 threshold 扫描；下一步必须改变监督/解码问题本身，以完整连通方案的
对比排序或条件化子图生成为基本训练单位，不能继续沿用独立 member/cardinality/STOP
head 的局部修补。冻结 test 继续保持未读。

正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_joint_canary_20260805_v27_one_way_object_branch/summary.json`；
- checkpoint SHA256
  `51556dc0310a4719a208677b2a9f5fbb570b345cdaf8120e39d8cd1874483349`。

## 2026-08-04：T032-JOINT-ARCH-CLOSURE-P1 同 forward 联合训练

### 训练边界

本轮不再把锁定的 `JunctionStore` 当作 ordinary 的离线终态输入，而是按冻结 T01
的直接业务依赖构建动态子图：每个 `case_key + semantic_junction_id` 在连通组内只
forward 一次，先输出锚定状态和完整 Node/Road candidate，再把 live embedding、
对象置信度及已选对象关系广播给所需普通 Segment。Segment decoder 只能在已有完整
Plan candidate 中选择，不能修改锚定、扩充候选、改变 T01 骨架或重新判断 fallback
事实。连通组在 Junction 边界停止，不使用递归 fallback closure；空间切片和引用式
store 只承担一次读取及查询加速。

固定协议为 Fold1、seed=`20261670`、4 epoch、前 2 epoch teacher forcing、后 2
epoch 真实 free-run、LR=`2e-5`、weight decay=`2e-4`、clip=`1.0`，Gold/Silver
anchor loss 总质量固定为 `0.5/0.5`。共享 anchor 参数使用 PCGrad；没有扫描 seed、
epoch、weight 或 threshold，没有增加 local head/reranker。AdvanceRight 和 Movement
关闭，T07 继续作为前置证据，T01–T12 实现与接口均未修改。

组件审计得到 1,192 个直接依赖连通组，其中训练 822、验证 370；最大组为 247 个
Segment、201 个 Junction，P95 均为 13，没有跨 Case 连通组。模型参数量
38,099,141，超过原先 10–20M 研究预估，因此只作为联合架构 canary，不是部署模型。
训练耗时 483.68 秒，总 wall 608.39 秒；峰值 RAM 5,926,096,896 bytes、峰值 VRAM
14,187,800,064 bytes。四轮中发生共享梯度冲突的连通组分别为 240、238、255、251，
占每轮 822 组的约 29%–31%。

### 完整结果

| 层级指标 | 同次初始化 | 联合训练后 | 变化 |
|---|---:|---:|---:|
| 锚定完整业务 exact | `801/1007` | `804/1007` | `+3` |
| 锚定 Gold 业务 exact | `23/42` | `22/42` | `-1` |
| SUCCESS 完整对象 exact | `775/935` | `777/935` | `+2` |
| 正向 NO_EVIDENCE exact | `30/47` | `33/47` | `+3` |
| 锚定 dangerous automatic | `13` | `17` | `+4` |
| 锚定 unknown automatic | `170` | `194` | `+24` |
| Segment Full Exact | `6/24` | `9/24` | `+3` |
| Junction Group Exact | `5/18` | `6/18` | `+1` |
| structured plan exact | `909/1209` | `982/1209` | `+73` |
| positive KEEP_SWSD | `286` | `294` | `+8` |
| positive USE_RCSD | `110` | `124` | `+14` |
| unsafe automatic | `22` | `25` | `+3` |
| unknown automatic | `381` | `433` | `+52` |

相对上一代冻结 ARCH-CLOSURE-P0 canary，联合结果的 Segment Full Exact 为
`9/24` 对 `8/24`，Junction Group Exact 同为 `6/18`，structured plan exact 为
`982/1209` 对 `959/1209`，positive USE 为 124 对 109；同时 unsafe automatic
为 25 对 21、unknown automatic 为 433 对 414。因此联合表示对普通完整方案有可
复现实质增益，但未达到安全发布边界。

### 有界迁移归因与结论

普通方案共有 90 条 `wrong→exact`、17 条 `exact→wrong`，Full Exact 为 3 条修复、
0 条退化。新增 4 个危险锚定全部是监督真值 `ABSTAIN` 从初始正确回退被联合训练
释放：2 条变为 `SUCCESS`、2 条变为 `NO_EVIDENCE`，没有任何危险项反向修复。其中
3 个 Junction（`607598902`、`520233234`、`523519858`）直接对应 3 个新增危险普通
Segment；Segment 的真值作用域始终为 `EXPLICIT_FALLBACK`，没有作用域扩张，也没有
decoder 反向修改锚定。unknown 普通自动项净增 52 条来自 57 条新释放与 5 条回退。

这证明当前 NO-GO 的首要原因不是动态子图、候选覆盖、Junction fallback 边界或普通
Plan 表达能力，而是 ordinary loss 经共享 encoder 改写了锚定决策。PCGrad 只能降低
梯度冲突，不能保证锚定业务输出不退化。正式结论为
`JOINT_ARCH_CLOSURE_CANARY_NO_GO`：不扩五折，不做同结构的 loss/epoch/threshold/
seed 扫描。保留直接依赖子图、唯一 Junction 一次 forward、live 条件化及结构化
candidate decoder；下一架构必须让 ordinary loss 只学习下游条件表示，不能写入
独立锚定决策参数。该隔离仍属于神经网络系统内部边界，不恢复 T03–T06 旧策略，也
不把规则判定重新放回推理期。

正式研究工件：

- `outputs/_work/p05_neural_road_generation/target_a_joint_arch_closure_fold1_20260804_seed_20261670/summary.json`；
- `outputs/_work/p05_neural_road_generation/target_a_joint_arch_closure_fold1_20260804_seed_20261670/outer_fold_1.pt`；
- 同目录初始/最终 anchor、Segment、Junction predictions 与 scoreboard。

新增联合数据流、live Junction 梯度/绑定边界和直接连通组测试后，使用 WSL 仓库
`.venv`（PyTorch `2.9.1+cu128`）执行完整 P05 回归：`799 passed, 1 warning`，
唯一 warning 为既有 Transformer nested-tensor 提示。Windows 全局 Python 不含
`torch` 的首次收集失败属于环境误用，不计为代码回归；正式结果只采用上述完整退出。

## 2026-08-04 T037 Junction-first T07–T05 P0

### 范围与标签审计

用户将优先级明确调整为语义路口，并选择把 T07 与 T03/T04/T05 一起纳入模型替代
范围；T01 继续冻结业务骨架，Segment、AdvanceRight 和 Movement 全部关闭。模型
推理只读取 T01/SWSD、原始 DriveZone、原始 RCSDIntersection 和原始 RCSD
Road/Node；旧 T07–T05 终态只作 label/evaluation。T07 Step1 仍严格为
DriveZone-only。

首版审计误用稀疏 `t07_step1_audit.csv`，把 Step1 覆盖报告为 0。修正版改为从
`step1_has_evd/nodes.gpkg` 和 `step2_anchor_recognition/nodes.gpkg` 按 SWSD
语义路口 mainnodeid 聚合，并把实体存在、可监督和组内冲突分开。正式结果：

| 标签范围 | 可监督 / 分母 | 值域 |
|---|---:|---|
| T07 Step1 | `4459/4459` | yes=3690，no=769，冲突=0 |
| T07 Step2 | `3690/4459` | yes=1759，no=1919，fail1=8，fail2=4，冲突=0 |
| T07 relation | `4459/4459` | 10 类正式 relation state |
| T03 | `1531/4459` | accepted/rejected、A/B/C、4 类 relation state |
| T04 | `387/4459` | accepted/rejected/runtime_failed、5 类 relation state |
| T05 surface | `3593/4459` | T02_INPUT/T03/T04 |
| T05 junctionization/graph/relation | `3624/4459` | 4 类 plan、4 类 graph、成功/失败 |
| 完整 anchor status/candidate/member | `4338/3321/3490` | 多解集合保留 acceptable set |

审计总范围为 5,148 个唯一路口、736 个 Case。inference store 的 13 类 source role
全部来自原始输入，T03/T04/T05 终态 role 为 0；Step1 固定只取 64D object 中的
11 个 SWSD/DriveZone 维度，candidate、RCSDIntersection 和 RCSD Road/Node 通道
均不存在。审计结论为 `JUNCTION_FIRST_LABEL_AUDIT_GO`，工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_first_t07_p0_audit_20260804_r1/summary.json`；
- `junction_label_coverage.jsonl` SHA256
  `7fd816808c3c398be86eac06c0aed38e9fe496c19df74c56c32b51b322f20679`。

### 分层网络与固定 canary

P0 网络共 15,517,518 参数。Step1 是物理独立的 DriveZone-only encoder；Step2
是独立 raw RCSDIntersection encoder；两者输出作为 stop-gradient 条件进入后续
route、T03/T04/T05 任务，避免后续 loss 反向改写前置硬门禁。后续共享 raw
object、candidate bundle 和 Node/Road member Set Transformer；完整 anchor 同时
输出 status、候选完整 bundle、对象类型、cardinality 与 member set。确定性层仍未
进入训练，也未调用旧 T07–T05 推理结果。

协议固定为 Fold1、seed=`20261671`、18 epoch、batch 32、AdamW LR=`2e-4`、
weight decay=`2e-4`、clip=`1.0`；前 6 epoch teacher forcing，7–11 退火，12–18
完全 free-run。未扫描 seed、epoch、loss weight、threshold 或局部 head。初跑将
缺少 T07 stage 标签的单点 T03/T04 route 错置为 `UNRESOLVED`，其完整 anchor
exact=`0.785153`、联合 exact=`0.696836` 只作为标签缺陷诊断，不作为正式结果。

单点 Case 按目录业务作用域改为 label-only T03/T04 route 后，以相同配置重跑一次。
正式 Fold1 结果：

| 输出 | accuracy / exact | 监督量 |
|---|---:|---:|
| T07 Step1 | `0.965714` | 1225 |
| T07 Step2 | `0.832845` | 1023 |
| route | `0.937454` | 1359 |
| T03 surface / relation | `0.933941 / 0.838269` | 439 / 439 |
| T04 surface / relation | `0.835294 / 0.717647` | 85 / 85 |
| T05 junctionization / graph / relation | `0.880359 / 0.957129 / 0.971087` | 1003 |
| candidate bundle exact | `0.856195` | 904 |
| member set exact | `0.757544` | 961 |
| 完整 anchor exact | `879/1145 = 0.767686` | 1145 |
| T07–T05 关键状态联合 exact | `872/1359 = 0.641648` | 1359 |

错误 ledger 把 raw `SUCCESS` 拆为 13 条状态型危险、202 条状态为 SUCCESS 但完整
Node/Road 集合错误、32 条 Gold 不完整不可确认；另有 41 条真实 SUCCESS 漏召回。
完整正确 SUCCESS 为 716，完整正确非 SUCCESS 为 163。对象集错误随 cardinality
上升明显，但单对象也有 69 条错误；因此不能把问题简化为 10+ Road 长集合，也不能
用统一置信度阈值代替对象集建模。

单点最差类同样未通过：T03 成功 Case 完整 anchor exact=`1/12`，T04=`0/7`；
T03_Error=`51/51`、T04_Error=`63/63`。这说明单点成功/失败 truth 必须继承，但其
缺少城市完整 T07 前序观测，不能直接和 T10 free-run route 当作同一分布训练。下一
架构只能用独立 auxiliary/teacher adapter 消费这些高权重标签，再蒸馏到共享 raw
encoder；不得把 Case family 作为推理输入。

正式结论为 `JUNCTION_FIRST_CANARY_NO_GO`。该结果证明分层网络能端到端输出业务
状态和完整对象，且主要状态任务已达到 0.83–0.97；但零危险、完整对象和最差类仍未
收口。普通 Segment、AdvanceRight、Movement 保持关闭，不扩五折，不做同结构
epoch/threshold/seed 搜索。正式工件：

- `outputs/_work/p05_neural_road_generation/target_a_junction_first_canary_20260804_fold1_seed_20261671_r1_route_label_fix/summary.json`；
- checkpoint SHA256
  `7a704616eb06711e45dd910bdc4f9da4072eeca3367ffe2887982b96a128db6a`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_first_canary_error_audit_20260804_r2_route_label_fix/summary.json`；
- error ledger SHA256
  `003c65293d5b49e6fbbc5e182ad657d28f69629ac6f96f86955e6031d5e8e27b`。

新增 Junction-first 数据合同、分层网络、stop-gradient、完整 candidate/member
对象集 decoder、loss 和单点 route label-only 测试后，在 WSL 仓库 `.venv`
（PyTorch `2.9.1+cu128`）执行完整 P05 回归：`806 passed, 1 warning`。唯一
warning 仍为既有 Transformer nested-tensor 提示。

## 2026-08-06 完整 JunctionResult 合同与 Oracle 收口

本阶段按用户要求停止训练，重新以“一个 SWSD 语义路口对应一个完整业务结果”审计
标签和候选表达能力。开发集共 4,288 条，其中强 Gold 602 条、T10 弱标签 3,686 条；
冻结测试原有 106 条，其中 1 条只在合同发现阶段暴露并隔离，后续正式盲测仅允许使用
剩余 105 条。该阶段未执行模型训练，Oracle 只表示标签合同和候选域是否能够表达
正确结果，不代表模型精度、自动接受覆盖或发布安全。

完整输出合同固定为：Step1 DriveZone-only 证据状态、已有/虚拟/无有效面方案、完整
RCSD Node/Road 锚定集合、唯一主锚定、Node 等价关系、Road 打断操作、物化后拓扑、
质量状态与 ABSTAIN。确定性层只执行面矢量化、Road 打断、Node ID 生成、拓扑校验和
写出，不重新选择业务对象。当前 `RealityChangeClue=true` 缺少足够的路口级两类监督，
因此 P0 不训练 Clue 二分类；只有已证明无 RCSD 证据时可派生 `clue=false`，其他记录
保持 UNKNOWN。

虚拟面不要求与历史规则面几何 exact，也不再把规则相交所得的全部成员当作必须 exact
复现的集合。正式监督改为三态约束：锚定关联的 Node/Road 为 `REQUIRED`，规则正式
禁止的可见 Node/Road 为 `FORBIDDEN`，其余对象为 `UNKNOWN`。1,685 条适用记录中，
1,680 条可监督、5 条 REQUIRED/FORBIDDEN 冲突隔离为 Review；1,528 条成功锚定记录
的 REQUIRED 候选可达率为 `1,528/1,528=100%`，不存在候选表达阻断。6 条
`NO_RCSD_EVIDENCE` 的 T04 must-cover Road 只作构面参考并保持 UNKNOWN；76 条质量
状态记录只监督状态/原因，不补造成成员集合。

在该合同下，物化后拓扑 Oracle 可表达 `1,626/1,685=96.50%`，完整结果 Oracle 可
表达 `1,621/1,685=96.20%`。结论为 `CONSTRAINT_ORACLE_GO_WITH_REVIEW`：现有标签与
候选域足以启动下一代路口网络，但 5 条冲突记录必须保持 Review，缺失字段继续按 mask
训练，不能为了扩大分母补造真值。

下一代技术合同采用 `Role-separated Graph/Set Encoder + staged multi-task heads +
candidate-constrained structured decoder`，建议参数量 5–8M。主表征为 21D 原始几何
token 与 8D RCSD 拓扑边；既有 64D/12D 推理期特征只作逐维审计后的兼容辅助输入，
不得进入 Step1。训练必须从真实端到端 free-run 链路起步，再依次使用 teacher
forcing、scheduled sampling、完整结构 decoder 和安全校准；同一城市原始 GIS 只
解析一次，并以对象 ID 索引的城市级特征仓为动态业务子图提供切片。

正式审计工件：

- `outputs/_work/p05_neural_road_generation/target_a_complete_junction_result_contract_oracle_20260806_v1r4/`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_result_derived_label_overlay_20260806_v1r3/`；
- `outputs/_work/p05_neural_road_generation/target_a_virtual_surface_constraint_overlay_20260806_v1r2/`；
- `outputs/_work/p05_neural_road_generation/target_a_junction_model_contract_20260806_v1/`。
