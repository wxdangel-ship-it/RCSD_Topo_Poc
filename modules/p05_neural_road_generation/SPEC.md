# SPEC：P05 神经网络 F-RCSD Road 直出 POC

## 1. 模块定位

P05 是 `Active POC / 成果模块`。其长期研究目标是用神经网络从业务证据直接生成符合 T06 Step3 语义的 F-RCSD Road/Node；它不修改 T01–T12 正式业务契约或现有实现，也不把实验指标提升为生产质量口径。

当前正式研究路线是 2026-07-25 授权、2026-07-27 修正 fallback 作用域并于 2026-08-04 扩展 T07 边界的 **Target A：T07–T06 联合业务决策与约束 RoadGraph 生成**，完整合同位于 `specs/p05-target-a-joint-roadgraph-20260725/`。T01 Segment 集合、Junction—Segment 关系、SegmentAccess 和 PhysicalMovement 存在性冻结，T10 继续负责数据与编排。模型先从原始 DriveZone、RCSDIntersection、SWSD/RCSD Road/Node 学习 T07/T03/T04/T05 路口 evidence、surface、relation、graph-consumable/junctionization 与完整锚定对象；路口阶段独立通过零危险门后，才允许训练普通 Segment、条件化 ADVANCE_RIGHT、RealityChangeClue 与 fallback。旧 T07–T06 策略在 Target A 推理期完全退出，终态只作训练标签和评价；T07 Step1 仍严格 DriveZone-only，RCSDIntersection 从模型内 Step2 才可见。第一版不启用 Movement、不接生产，也不修改 T01–T12 实现或接口。

2026-08-06 已完成下一阶段训练前的完整 `JunctionResult` 合同与 Oracle 可表达性
审计。当前路口阶段以唯一 SWSD 语义路口及其动态业务依赖子图为 forward 单元，输出
面方案、完整 RCSD Node/Road 锚定集合、唯一主锚定、Road 打断操作、物化后拓扑、
质量状态与 ABSTAIN。虚拟面不要求复现旧规则面几何或 exact 成员集合，而按
`REQUIRED / FORBIDDEN / UNKNOWN` 三态监督：1,685 条适用记录中 1,680 条可监督，
5 条冲突隔离 Review；成功锚定记录 REQUIRED 候选可达 `1,528/1,528=100%`，完整
结果 Oracle 可表达 `1,621/1,685=96.20%`。该结论只授权进入新网络结构实现，不是
模型精度或安全发布 GO。下一代模型采用角色分离的 Graph/Set encoder、分阶段多任务
head 与候选约束 structured decoder；T07 Step1 仍保持 DriveZone-only 物理防火墙。

Target A 不是自由重建业务骨架。模型不得新增、删除、合并、拆分或重分配 T01 Segment/Junction，不得改变 PhysicalMovement 存在性，不得使用 PTO-A 改写骨架。语义路口锚定是模型内前置硬门禁，多候选不能由后续 Road 分数代选；锚定失败或歧义必须回退。普通 Segment 输出完整 Road 清单、业务角色、所有权、access、方向、条件化 Node 和打断配方；`KEEP_SWSD` 是正向业务决定，`ABSTAIN -> fallback` 单独统计。ADVANCE_RIGHT 只能在相邻普通 Segment 最终 access 锁定后条件化解码，不能反向改变普通 Segment。确定性层只执行模型给出的 split/clip/reverse/splice、ID/schema/CRS 写出和通用合法性校验，不重新作业务判断。

锚定结构 decoder 以共享 object encoder 输出、原子 RCSD Node/Road
成员、SWSD/RCSD arm 摘要和原始端点拓扑边为推理输入，联合输出
`success_required_rcsd_junction / rcsd_present_not_junction /
no_related_rcsd` 证据角色、Node/Road 类型、cardinality 与完整成员集合。
训练标签与推理 batch 物理分离；多解标签按任一可接受的类型、数量和完整
成员集合计算，不压成单解。类型只能在现有原子候选类型中选择。cardinality
阈值解码与期望下界不一致时，安全门禁只能把已有自动 proposal 降级为
`ABSTAIN`，不得改写锚定对象、Road 集合、候选作用域、业务骨架或 fallback
作用域。

一条最终 RCSD Road 片段只能由一个正式 Segment 所有；无 owner Road 只用于 Junction 内部或多 Segment connectivity。RCSD 主干允许由一条或多条 RCSD Road/片段组成。普通 Segment 禁止通用 HYBRID，唯一允许的普通 Segment 混源 carrier 是 T06 已定义的“主干 RCSD 替换、附属/侧向 SWSD 保留”。ADVANCE_RIGHT 的 `MIXED_SPLICE` 是独立的条件化几何方案，不属于通用 HYBRID：仅当两侧相邻普通 Segment 最终 access Road 来源一侧为 RCSD、另一侧为 SWSD 时，模型才可输出 RCSD Road、SWSD Road、两侧保留区间和 splice 位置；最终 Road role 仍为 `ADVANCE_RIGHT`，所有权仍属于该提右 Segment，确定性层只执行已选配方。任一对象、区间或位置不明确时只回退该 ADVANCE_RIGHT Segment。Segment 内部 RCSD 连接树满足“聚合后为树、所有叶都挂接当前 Segment 选择的 RCSD 主干、无外部叶”时，其 Road 同时进入 `frcsd_road_ids` 与 `owned_frcsd_road_ids`。

截至 2026-07-29，Target A 已完成锚定、普通 Segment、相邻 ordinary
source/access 条件化 AdvanceRight、有限作用域 decoder，以及 whole-Road、
端点复用和独立 `MIXED_SPLICE` 的确定性 materializer 研究实现。
AdvanceRight 链路已从 P13 的 candidate-local scorer 升级为：先锁定两侧
普通 Segment 的 `SWSD / RCSD / UNRESOLVED`、完整 Road 清单和 RCSD
access，再选择完整提右 Road 组合、父 Road、打断/片段、挂接和 splice
recipe；后层不能反向改变普通 Segment。

v218 在同一 1,221,363 参数 shared encoder 上联合微调 AdvanceRight
carrier 与 geometry heads，严格 OOF complete plan+geometry raw
exact=`0.177215`、geometry action exact=`0.268519`、raw end-to-end
complete exact=`0.006329`，自动接受仍为 `0/474`。该轮普通 Segment
完整 Road/access 是 forward 前固定的 OOF 条件，474 个 AdvanceRight
中只有 3 个两侧 ordinary `Road set + source + access` 同时正确，因此
v218 证明局部联合梯度有效，但不是 anchor/ordinary/AdvanceRight 全链
端到端联合模型。v219–v222 进一步把普通 Segment 的完整 Road 清单与
AdvanceRight access 父 Road 拆成共享 encoder 上的独立业务角色，并复用
普通 Segment 预训练 checkpoint。当前业务合法的 v222 以锁定 source
约束 Road 候选：847 个有监督 ordinary 侧的 Road-set exact=`0.081464`，
948 个侧的 source exact=`0.907173`，563 个 RCSD 侧的 access exact=
`0.948490`；两侧 ordinary exact 与 raw end-to-end complete exact 均为
`0.006329`，自动接受仍为 `0/474`。这说明 source/access 已不是首要瓶颈，
完整 ordinary Road 清单才是当前决定性约束；下一轮应在全部普通 Segment
监督上预训练 role-aware Road encoder，再以较低学习率接入 access、
AdvanceRight 与 geometry heads，而不是继续局部调整 AdvanceRight 或
`MIXED_SPLICE` scorer。v223–v228 已完成该验证：v223 以 v142 ordinary
预训练和 `0.1×` 学习率把 Road-set/端到端 exact 提升至
`0.095632/0.008439`；跨 anchor-graph 结构迁移 v175 在同 seed v226
退化为 `0.075561`，已淘汰。v227r1 在与 joint 相同的 unordered-set
forward 上用 3,160 个普通 Segment 训练 ownership/role 辅助头，ordinary
总体 complete exact=`0.610443`，低于 v142 的 `0.625712`；但同 seed
接入的 v228 在 847 个有监督相邻侧上 Road-set exact=`0.102715`，raw
end-to-end exact=`0.014768`（7/474）。其 source/access/AR plan exact
分别为 `0.897679/0.946714/0.510549`，自动接受仍为 `0/474`，因此只保留
same-forward 角色预训练的弱正向资产，下一轮转向普通 Segment 大 Road
bundle 的数量与结构完整性，不再扫描角色 loss 或提右 scorer。
v105r1 的全部 8,863 个冻结 Segment 所有权/有限 fallback
审计仍保留为历史诊断：自动 ordinary=`855`、AdvanceRight=`0`，重复 Road
所有权与骨架 mutation 均为零，但 577 个强标签可评价自动对象中仍有 84 个
业务错误。T033–T035 仍为诊断性 **NO_GO**，不接生产；完整结果见 Target A
`validation-summary.md`。

截至 2026-07-30，v229–v234 已把普通 Segment 从独立 Road membership
升级为 order-free 结构化 set expansion。v231/v233 的完整 Road set
exact 为 `0.713291/0.707911`，但 10+ Road Segment exact 仅
`0.184932/0.219178`，失败主要来自提前 STOP 和漏选。首次 v234 虽以两个
strict Case-OOF seed 的业务状态与完整 Road set 一致性作为发布门，但错误
放行 26 个 required-anchor 失败的 USE，已废止。修正后的
v234r1 要求 KEEP/USE 均服从锚定前置门禁，并要求两个 seed 对完整 Road set、
逐 Road ownership 和业务角色一致；自动接受 `113/3160`，全部为正向 KEEP，
coverage=`0.035759`、selected business truth `113/113` 正确，
USE=`0`、unsafe/unverifiable automatic=`0`。

v235r2–v240r1 随后把 AdvanceRight 条件输入改为相邻普通 Segment 的最终
access Road 状态，显式区分正向 KEEP 与 fallback SWSD。两个独立 strict
OOF seed 只在锁定后的完整方案一致时发布；v240r1 自动接受 `414/474`，
coverage=`0.873418`、完整方案 exact=`1.0`、unsafe automatic=`0`，
且 414 条全部为 `SWSD_ONLY`。v241r1 对 51 Case 执行最终状态 materializer：
414/414 提右决定可物化，Road/Node/attachment 为
`14,193/12,745/868`，hard failure、skeleton mutation、silent fix、
content repair 均为 0；ordinary USE/preflight fallback 均为 0，45 个既有
T01/source blocker 保持直接对象局部阻断。该结果只证明 SWSD-only 提右
条件路径局部 PASS；普通 USE 的完整执行、
RCSD_ONLY/MIXED_SPLICE、Clue/scope 和完整 RoadGraph 仍未通过，Target A
总体继续 **NO_GO**、不接生产。下一轮冻结该局部 PASS，集中治理普通
Segment 大 Road bundle 的结构化完整性。

`621989990` 人工可锚定裁决触发了 required-anchor 数据完整性复核。按当前
51 Case inventory 和精确目标 Segment 重建的 v107 有 5,148 个锚定样本，
比旧 v19 多 584 个既有 Case 内 required anchors；旧 4,564 个样本无删除，
排除直接依赖集合后的 truth-free 核心特征零漂移，但 2,145 个样本的
Segment 内直接依赖集合得到补全。因此 v50–v105 保留为历史诊断，不能再
作为当前完整监督作用域的最终性能结论。相同配置/seed 重训的 v109 虽将
anchor gate accuracy 提升到 `0.959889`、accepted coverage 提升到
`0.164918`。v110 将 32 个 unsafe-to-release 正式拆为 `17` 个有监督
错误和 `15` 个不可验证自动项；后者含 14 个
`relation_record_absent` 真值未知对象及 1 个 exact candidate 被 mask
的 SUCCESS，不得补造为失败或对象错误。`621989990` 自身折外预测为 `NO_EVIDENCE`，
被 independent gate 安全拒绝为 `ABSTAIN`。T030d 继续 **NO_GO**，
因此未继续重训 downstream ordinary/AdvanceRight。

T032-R2 随后在 v111 完整继承 `621989990`、已证明无证据、
T11 `no_valid_relation` 和 `relation_record_absent` 三态政策后，完成
200,963 参数共享 anchor/ordinary gate 的 strict-nested OOF。锚定对象
选择保持独立，Segment loss 只约束 required-anchor 可判定性和有限
Segment fallback，不能反向选择对象。v113 以共享 gate 与独立对象模型
置信度的保守合取接受 1,072 个 anchor，其中 safe=`1,019`、
supervised error=`25`、unverifiable=`28`；接受 835 个普通 Segment，
其中 safe=`808`、supervised error=`5`、unverifiable=`22`。与 v110
取交集仍有 15+9 个 anchor 危险项及 4+8 个 Segment 危险项，且覆盖更低。
因此 T032-R2 实现与单 seed 诊断已完成，但发布门仍为 **NO_GO**，不向
Road/carrier、AdvanceRight 或完整 RoadGraph 下游释放。

T012 已于 2026-07-29 完成。旧 14,415 个未经证明的
`CORRIDOR_COMPONENT` 候选已退出；v114 改为保留全 MAIN 连通分量候选，
并只对“物理并行 Road 聚合后为单树、所有叶均挂接当前 MAIN、无外部叶”
的子图输出 `INTERNAL_CONNECTOR_TREE`。51 Case 共生成 6,651 个内部连接
树候选，逐候选 hard-valid、叶/挂接、所有权与物理边计数全部通过，
`EPSG:3857` 51/51、`silent_fix=false`、骨架 mutation=0。完整 Road
清单可达性由 4,409/5,829 增为 4,410/5,829，旧 9 个完整清单零丢失。
当前只有
`T10-Error-2:986209_996008_1 / 986209_996008_1`
这一条可达标签必须包含内部连接 Road；T06 提供完整 Road 清单监督，
MAIN/INTERNAL_CONNECTOR 角色由已确认树形条件证明，现有 Case 没有第二条
同类可达正例。v120 在该 held-out 对象仍漏选内部连接 Road，v119 的
required-anchor 发布门将其拒绝；共享 gate 仍有 25 个 anchor 监督错误和
5 个 Segment 监督错误，因此继续 **NO_GO**。`621989990` 仍是人工确认
应成功锚定的正标签；当前模型 `NO_EVIDENCE -> ABSTAIN` 只算安全 fallback，
不能改写业务真值或计为正向 KEEP。

截至 2026-07-28 的阶段性结果已完成锚定与 T032 普通 Segment 的严格单 seed
Case-OOF 研究实现。普通 Segment decoder 显式先输出
`KEEP_SWSD / USE_RCSD / ABSTAIN` 关键业务状态，再在该状态内选择完整 Road
清单；状态内归一化不能替代完整 carrier 输出。当前按安全优先选择的结构基线为
v45：候选可达且通过锚定条件的完整 plan exact=`0.936338`、
KEEP=`0.970816`、USE=`0.797847`、自动决策覆盖=`0.989618`，
最差 fold=`0.850498`、最差 USE fold=`0.756881`。v45 继承 v44 的逐
Road 成员集合并限制其只参与业务状态内的 Road 清单排序，同时增加对称的
SWSD 两端 arm ↔ 候选 Road 端点匹配，让距离、叶端点、方向对齐和 OOF
锚定关系以受控残差参与业务状态与 bundle 选择。相对 v41，v45 修复
`117`、回归 `65`，净改善 `52`；`within-USE_RCSD` 错误由 `67` 降到
`34`，六个主要 T10 Case 均净改善或持平。但仍有 `267` 个自动完整 plan
错误，且 v45 只完成单 seed 严格 OOF。T030d 锚定
零危险门与 ordinary 发布门均为 `NO_GO`；
该阶段当时未启动 AdvanceRight、联合 fine-tuning、完整 RoadGraph 发布或生产接入；
后续已按 2026-07-29 状态继续研究，但仍未取得发布授权。

v46 进一步把每个 OOF 锚定结果区分为当前 Segment 端点对应的 local anchor
和另一端的 foreign anchor。它将 exact 提升到 `0.936576`、USE 提升到
`0.813397`、最差 fold 提升到 `0.857143`，但 KEEP 降到 `0.967242`；
相对 v45 仅修复 `41`、回归 `40`，净改善 `1`。更重要的是危险方向
`KEEP_SWSD -> USE_RCSD` 从 `98` 增至 `110`，而
`USE_RCSD -> KEEP_SWSD` 从 `135` 降至 `118`。因此 local/foreign
关系证明了端点条件化证据能够移动 USE/KEEP 边界，但 v46 不满足安全优先，
只保留为诊断实验，不替代 v45。

v47 在不改变 v45 锚定或 carrier 排序的前提下增加 14,913 参数的
strict-nested safety head，只允许把自动 `USE_RCSD` 改成 `ABSTAIN`。
它从 798 个 raw USE 中接受 189 个，其中 180 个正确、9 个危险，
accepted USE coverage=`0.236842`，仍为 `NO_GO`。v48 再加入来自全量
8,863 Segment truth-free candidate store 的共享语义路口邻接统计，
接受 217 个 USE、危险增至 14，亦为 `NO_GO`。现有 8,863 条 plan
标签只有 5 条具有 Clue/fallback-scope 监督；4,238 个普通 Segment
训练样本中只有 4 条（3 个 `clue=false/NONE`、1 个
`clue=true/JUNCTION`）。因此当前标签只能监督最终 Road 方案，不能可靠
辨识“KEEP 的业务原因、现实冲突与影响对象”。该缺口必须由明确的
Clue/scope 人工或正式可审计标签补足，不能从 KEEP 终态反推，也不能用
post-hoc safety 阈值补造。

为避免把“缺监督”泛化成要求新增 Case，当前已从既有 51 Case 生成
`target_a_clue_scope_adjudication_20260728_02` 标签准备包：363 个待裁决
普通 Segment 覆盖 22 个 Case，其中 P0 safety 危险 20、P1 carrier
错误 247、P1 锚定 fallback 44、匹配正确对照 52。5 条既有用户人工
裁决被单独锁定继承。准备包只展示现有标签、v45/v47/v48 证据、required
anchor 及直接相关普通 Segment；363 条新裁决均保持
`UNKNOWN/PENDING`，T06/T11 自动映射为 `0`。其中的
`carrier_verdict / keep_reason / clue / fallback_scope /
affected_segment_ids` 仍是待用户确认的补标草案，未进入模型训练或正式
业务源事实。

队列已进一步按缺失监督拆分：363 条都需要完整 carrier plan 复核，其中
128 条 KEEP 对象需要 `keep_reason + Clue + scope`，44 条需要锚定结果
复核。第一批只含 P0 safety 危险与匹配正确对照，共 72 条 carrier plan；
其中 47 条同时需要 KEEP/Clue/scope。剩余 291 条单独保留，第一批确认前
不进入裁决或训练。

Target A 的硬安全门为 unsafe auto RCSD、Review auto、unreachable auto、skeleton mutation、silent fix 和新增 RoadGraph hard failure全部为零，并保持至少 49 `LEGAL` + 2 `EXPECTED_FAIL` 的历史安全边界。正式评价同时比较完整现有策略，分别报告自动决策整图 exact 与 fallback 后最终 RoadGraph exact。现有 P1–P13、M2R、R2、PTO/JSG 结论继续作为历史实验事实；其中 P13-P0 只证明局部 AdvanceRight carrier scorer `SELECTION_NO_GO`，不再定义当前模型范围。

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

方案 A 历史首阶段在冻结 51 Case 上重建完整 T01 Segment 骨架、当时策略 `SUCCESS_DIRECT/SUCCESS_WITH_FALLBACK/FAIL` 基线、Segment/Movement carrier-only 标签、RealityChangeClue 和当时登记的最小依赖 fallback。全部 `advance_right` 必须作为 Segment 表达，当前 `SegmentConnector` 数为零；策略和标签覆盖率、来源完整率为 100%，骨架 mutation、content repair 和 silent fix 为零。两轮独立 run 的 skeleton/baseline/label/clue/fallback signature 必须一致。该段只记录历史 P1 工件，不授权 Target A 采用传递闭包；Target A 当前作用域以本文件开头的显式有限 directive 为准。本阶段不训练模型，完成条件以对应 SpecKit 为准。

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

## 11. Target A T014 materializer 当前状态（2026-07-29）

Target A 已实现 typed `DecisionLedger -> RoadGraph` 确定性执行器。模型/ledger
必须显式给出 source Road、Road 角色与 owner、方向、slice/break、reverse、
join mode、Node recipe、完整 access binding 和 attachment position；执行器只做
稳定 ID、split/clip/reverse/splice、Node/Road 写出和通用 hard validation，
不得选择最近 Road、补造 access、改变骨架、扩大 fallback 或修复不连续几何。
正向 `KEEP_SWSD` 与 `ABSTAIN -> fallback SWSD` 分开输出。

普通 Segment access 的正式执行单位已修正为一个冻结 access 下的完整
Road/Node 集合，不要求唯一 Road；access 可来自 `pair_node`、`junc_node`
或 T01 `source_segment_access/target_segment_access` 明确给出的
AdvanceRight 内部挂接 Node。只有 AdvanceRight 的 RCSD 侧附件才必须从
已选 access 集合中再指定唯一父 Road 片段、打断位置和共享最终 Node；
SWSD fallback 侧允许复用冻结 access Node/JunctionUnit。

v132 对 51 Case 严格物化 `8,818/8,863` 个冻结 Segment、14,193 条
Road；51/51 Case 都能物化其依赖完整子图，45/51 可完整物化冻结
skeleton。剩余 45 个局部 blocker 仅含 38 个 `FROZEN_ACCESS_INVALID`、
2 个 `FROZEN_INDEPENDENT_ROAD_INVALID` 和 5 个 owned
`MultiLineString` 不连续 Road；`STANDARD_LEDGER_UNRESOLVED=0`、
`ADVANCE_RIGHT_LEDGER_UNRESOLVED=0`。旧 v122/v123 的 1,243 个普通
Segment 与 431 个 AdvanceRight blocker 来自错误的“唯一 access Road”
假设，已被 v132 推翻，不得再解释为标签不足。审计为 CRS
metric/consistent 51/51，materialization hard failure=0，
`skeleton_mutation=0`、`silent_fix=false`、`content_repair=false`。完整 P05
回归 `500 passed`，`compileall` 通过。materializer 的最大 Case wall 由重复全图
Road/CRS 扫描修正为 owner 索引和 canonical CRS cache 后的 `47.26s`，
51 Case v132 wall=`185.37s`。这仍是逐 Case 审计器；城市推理必须一次
加载只读 Road/Node 索引、内存传递依赖子图并最终一次写出。

普通 access 训练标签也已按完整集合重解释。v126 的 2,904 个 access 对象中，
2,000 个有可解析集合，1,972 个需要同时输出多条最终 Road，只有 1 个存在
真正多解；原 1,665 个可训练对象及权重全部保留。旧单 Road v93
`raw exact≈0.778` 不能再解释为完整 access 正确率。首轮 253,121 参数
set decoder v127 的严格 5-fold OOF 完整集合 exact=`0.339002`、
mean set F1=`0.639804`、teacher exact=`0.586168`，23 个自动接受中仍有
4 个危险项，结论 **NO_GO**。

v135/v136 在同一 882 个 example 上加入 Set Transformer、显式集合大小头和
严格 top-k decoder。只用 teacher view 的 v135 OOF exact=`0.337868`；
teacher+strict-OOF 双视图训练、仅以 OOF view 早停的 v136 将 OOF 完整集合
exact 提升到 `0.433107`、mean set F1=`0.742805`、集合大小
exact=`0.713152`，参数量 446,737。上游 release-eligible 仍只有 25 个，
唯一自动接受项错误，故 v136 仍为 **NO_GO**，正式安全执行必须全部 fallback。

AdvanceRight 挂接监督已按 T06 最终 access Road 口径重建。1,481 条 T06
动作中，725 条仅为确定性 Node 规范化，不是模型目标；756 条 Road
打断/端点复用动作中，619 条能在正式关系范围内唯一映射为“相邻普通
Segment 的最终 access Road 片段 + 挂接端点”强监督，76 条只保留 0.3
弱辅助监督，61 条因依赖未解析、相邻 Segment 最终非 RCSD 或 carrier
缺失而屏蔽。619 条强监督中 563 条在冻结推理候选中精确可达。基于这
563 条的 v137 side attachment scorer 使用 144D 推理期特征、230,081
参数，严格 5-fold Case-OOF exact=`0.943162`，source=`0.942029`、
target=`0.944251`、最差 Case=`0.895349`。但其上游完整 access
release-ready 为 0，自动接受仍为 0；该结果只证明挂接候选判别力，
不代表完整 AdvanceRight 或 RoadGraph 已可发布。

T014 仍未关闭：自动 RCSD ledger 的零危险发布、56 条 AdvanceRight
强监督候选不可达、普通完整 Road/access 与 AdvanceRight Road/geometry
同一 forward 的联合解码、真实自动提右 materialization、城市级一次写出和
最终 RoadGraph exact 尚未完成，不接生产。独立 `MIXED_SPLICE` 已完成
合成整图执行和训练输出绑定，但不得据此替代真实 Case 验收。

## 12. Target A ordinary 结构化方案选择当前状态（2026-07-30）

v244r1 在严格 fold2 canary 中以三动作结构化 decoder 输出完整 Road set，
complete exact=`0.701754`、Road macro F1=`0.847126`、unsafe automatic=0；
10+ Road exact 仅 `2/16`，不能扩完整 OOF。v245 truth-free beam
oracle@16=`0.897661`，但 10+ Road 仅 `7/16`，说明正确方案多数可提出，
仍有长集合候选不可达和方案选择两类问题。

v246 32D 完整方案 reranker 没有提高 raw exact，但把 fold2 零危险自动覆盖
提高到 `113/342=0.330409`。v247 直接加入 672D graph/Road embedding 后
跨 Case 退化为 raw exact=`0.611111`、10+ Road=`0/16`，不得扩模型或完整
OOF。下一步只能研究 case-invariant 的 ownership、角色、access 和端点关系
方案比较；truth cardinality、T03–T06 终态和 held-out 标签仍不得作为推理输入。

v248–v255 已完成该关系方案比较。v249 结构化能量 raw exact 提高到
`0.716374`，但 10+ Road 仍为 `2/16` 且出现 1 条 unsafe automatic；
v253 relation-only same-plan pair F1 达到 `0.654739`，却没有改善完整方案
选择。v254/v255 改用 listwise complete-plan loss 后，必须把正确 ABSTAIN 与
carrier 方案 exact 分开：reachable-plan exact 分别为
`241/306=0.787582`、`239/306=0.781046`，10+ Road reachable exact 仅
`1/7`、`2/7`，零危险自动覆盖分别为 `90/342`、`97/342`，均未超过 v246。

v250 多视图 truth-free 方案并集的 oracle 可达为 `311/342=0.909357`，但与
当前锚定 hard gate 相交后只有 `214/342=0.625731`。因此 Target A 的下一阶段
不是继续独立调 ordinary decoder，而是 Case 级 combined batch：同一 forward
编码 SWSD 语义路口锚定候选与普通 Segment 完整 Road 方案，使锚定与 carrier
监督共享 encoder；推理时锚定头仍须独立输出唯一对象或歧义/无有效关系状态，
carrier 分数不得反向选择、修改或绕过锚定结果。

## 13. Target A 锚定—ordinary 同一 forward 当前状态（2026-07-30）

目标 A 的普通 Segment 网络 forward 单位正式采用“一个 focal Segment +
全部 required semantic anchors + 每个 required anchor 的一跳直接锚定依赖 +
该 Segment 的完整 Road plan 候选”。不得把城市、完整 Case 或共享 Road/Node
的传递闭包作为单次 forward 单位；城市文件只读索引应一次加载，业务子图在内存
中组装，最终结果一次写出。当前 4,196 个真实子图的对象数 P95/max 为
`14/47`，而完整 Case 传递闭包最大达到 3,117 个对象。

锚定头和 carrier 头可以共享 evidence encoder，但消息方向和发布语义必须满足：

- ordinary 对象不能向 anchor 决策发送消息；同一 anchor 在不同 focal Segment
  中的 status/candidate 输出必须一致；
- 锚定头独立输出唯一 RCSD Node/Road bundle、`NO_EVIDENCE`、`AMBIGUOUS`
  或 `ABSTAIN`；carrier 和 RoadGraph decoder 均不得替它选择对象；
- carrier 与锚定可以共享 context encoder，但原始锚定 evidence 分支必须
  保留；在证明不降低 relation/type、零危险与跨 Case 稳定性之前，
  carrier loss 不得直接改写锚定语义 encoder，更不能绕过或修改锚定离散
  结果；
- 冻结条件桥只允许把原始 object evidence 与锚定模型的
  relation/type/cardinality 摘要传给 ordinary decoder；锚定 teacher 在
  carrier forward 中必须 `eval + no_grad`，后层不得借条件化重新选择或
  改写 anchor proposal；
- `USE_RCSD` 要求全部 required anchors 唯一成功；
- 只有经独立安全证明的 `NO_EVIDENCE` 才允许 `KEEP_SWSD` 在没有具体 RCSD
  anchor 对象时成为正向业务结果；
- `relation_record_absent` 只表示真值未知，不能自动转换为成功、失败、
  `NO_EVIDENCE`、`KEEP_SWSD` 或 `RealityChangeClue`。

v257r3 首次完成上述同一 forward 严格 fold2 训练，参数量 18,415,507；
anchor prediction inconsistency=`0`，concrete anchor exact=
`210/277=0.758123`，all-plan exact=`533/603=0.883914`，但安全自动正确仅
`23/603` 且有 1 个 Review 自动项。直接或辅助 anchor-plan compatibility 的
v258/v259 均降低完整 plan exact，路线停止。

v260r1 补上正向 `NO_EVIDENCE -> KEEP_SWSD` 后，outer truth-ready 从
`212/603` 增至 `235/603`，但单独 status 概率的无证据证明产生 1 个 outer
危险项。v262 将无证据分数限制为
`min(P(NO_EVIDENCE), 1-P(unique-anchor gate success))`，inner-only 校准后
unsafe/review 均为 0；all-plan exact=`522/603=0.865672`，ready free-plan
exact=`184/235=0.782979`，concrete anchor exact=`207/277=0.747292`，
安全自动正确仅 `5/603=0.008292`。正式结论仍是
**`TARGET_A_CASE_JOINT_NO_GO`**，不得扩完整 OOF 或接生产。

当前 fold2 有 198 个 required anchor 缺少 status 或具体 candidate 真值，
影响 356 个 ordinary Segment；56 个已进入模型未验证 release 候选，必须由
安全阈值阻断。v263/v264 已形成 30 条 Phase 1 人工锚定队列和只读
EPSG:3857 可视审计包，覆盖 91 个受影响 Segment。v265 已按同一语义路口、
同一推理输入、同一候选集合和同一局部结构证据复核现有 T03/T04/T11 真值：
跨样本严格可复用数为 0；另有 1 个 T11 已知正确 Road 不在冻结候选集，
固化为 `CANDIDATE_MISSING`，全量剩余 197，Phase 1 仍为 30。人工结果只能是：

- `SUCCESS_UNIQUE` 并从冻结 candidate 集合选择一个唯一对象；
- 有正式证据的 `PROVEN_NO_EVIDENCE`；
- `AMBIGUOUS`；
- 正确对象不在候选集合的 `CANDIDATE_MISSING`。

人工裁决只写 label-only 工件，不修改 T01–T12，不得从模型预测或
`relation_record_absent` 补造真值。回填时必须逐列校验 v263 冻结证据，
`SUCCESS_UNIQUE` 原样命中一个完整候选，其他三类不得填写候选，且四类均需
证据说明；输出 inference feature store 必须保持字节一致。任一 required
anchor 已明确失败时，该 Segment 立即局部 fallback，不等待其余 anchor 监督
齐全。

## 14. Target A recall-first 端到端模型当前状态（2026-07-31）

Target A 已形成第一版可训练、可强制输出的同一 forward，但尚未完成最终
RoadGraph 发布验收。forward 单位为一个 AdvanceRight、两侧相邻普通 Segment
及其 required anchors；城市数据和索引只读一次，依赖子图在内存组装。旧
T03–T06 终态不作为推理输入，锚定仍是模型内前置门，提右不能反向修改普通
Segment。

v386r1 在严格外层 fold1 上输出 143/143 个提右研究结果。106 个有完整 Road
集合监督的对象 top-1 exact=`86/106=0.811321`；正确 Road 集合在 beam-16
中为 `106/106=1.0`。v387r2 从 50D 提右局部证据、普通方案成员和原始 side
Road candidates 构建 269,875 个 103D 几何 proposal，218/218 个需要新增
打断、挂接或衔接动作的监督对象可达；不使用旧 OOF condition 或终态选择，
单对象最大 5,188 个 proposal，运行内只读一次并跨 epoch 复用。

v388r1 冻结 v386r1 的锚定、ordinary 和 Road-set 权重，只训练 365,953 参数
几何头，避免破坏 recall。外层 fold1 指标为：

| 指标 | 结果 |
|---|---:|
| 强制研究输出 | `143/143=1.0` |
| Road top-1 exact | `86/106=0.811321` |
| Road beam-16 recall | `106/106=1.0` |
| 几何 top-1 complete exact | `30/67=0.447761` |
| 几何 beam-16 complete recall | `67/67=1.0` |
| Road + 几何联合 top-1 complete exact | `33/77=0.428571` |
| Road + 几何联合 beam-16 recall | `77/77=1.0` |

以上是 recall-first 研究基线，不应用置信发布门，`automatic_decision=false`。
正向 `KEEP_SWSD` 仍是业务决定；`ABSTAIN -> fallback` 仍单独统计。29 个
`SWSD_ONLY` 的正确几何结果是“无新增动作”，不进入 218 个 proposal 分类
分母，但继续进入端到端 Road 结果评价。

v390r3 尝试把 Road 与几何 beam 平铺为最多 81,920 个四类可解释组合：
`SWSD 无新增动作`、`两侧 RCSD 挂接`、`source RCSD + 中间衔接` 和
`target RCSD + 中间衔接`。候选覆盖为 239/239，但外层 top-1 降至
`32/77=0.415584`，decoder top-16 recall 降至 `63/77=0.818182`。该路线因
组合空间过大、239 个联合监督过于稀疏而判定 NO_GO；不能通过增加 epoch、
通用 HYBRID 或扩大评估 beam 继续解释为收敛。

当前正式保留 v388r1 + v389。下一步只收敛两个可辨识错误面：完整 Road
cardinality/成员排序，以及 SOURCE/TARGET_ATTACHMENT/MIDDLE_SPLICE
分类型几何 top-1。五折 OOF、完整 Node/方向/拓扑写出、确定性物化后的最终
RoadGraph exact、与现有完整策略对比及零危险发布门尚未完成；Target A
总体仍不接生产。

## 15. 普通 Segment 联合模型优先级修正（2026-08-02）

上一节的 AdvanceRight 组件实验继续作为历史证据，但不再是当前训练优先级。
当前按修正方案 A 优先收敛普通 Segment：模型在同一业务依赖子图 forward 中
先输出 required anchor 的唯一锚定对象与状态，锚定失败立即形成 Segment 局部
fallback；锚定结果锁定后，完整 Road decoder 才能输出 KEEP_SWSD 或
USE_RCSD 的完整 Road 清单、用途、所有权、access、方向及所需打断。Road
分数不得反向修改或绕过锚定。

M144 已形成严格五折高召回研究基线：强制 gated output=
`3119/3125=0.998080`，anchor exact=`2388/3123=0.764649`，gated complete
Road exact=`2370/3125=0.758400`，anchor+Road joint exact=
`1910/3123=0.611591`。强制输出覆盖不等于安全发布覆盖；该基线仍为
`TARGET_A_ORDINARY_JOINT_HIGH_RECALL_BASELINE_NO_GO`。正向 KEEP_SWSD 与
`ABSTAIN -> fallback` 必须分开统计。

下一版共享 encoder 必须显式表示 focal Segment、required anchors、候选
RCSD Road、共享 Junction/Node、access 和所有权冲突。T03/T04 人工真值与
T10 分级监督进入同一多任务训练，但旧 T03–T06 终态不得成为推理输入。
城市级索引一次读入，forward 按动态业务依赖子图组装；空间切片只能用于查询
加速，不能截断业务依赖。AdvanceRight 暂停训练，Movement 保持关闭，直到
普通 Segment 的高召回联合 exact 与安全工作点同步提升。

M146–M149 已验证把相邻普通 Segment 压缩方案或显式 Road 成员图直接叠加到
同一最终 scorer 会造成 KEEP/USE 偏置迁移，未超过 M69/M120。下一版 decoder
必须先在锁定锚定下独立确定正向 KEEP/USE source，再条件化执行完整 Road
方案：KEEP 输出完整冻结 SWSD 方案；USE 才解码 RCSD Road 成员、用途、
所有权与 access。成员分数不得反向修改 source，ABSTAIN 仍单独进入局部
fallback。当前候选缓存未覆盖 T06 明确允许的附属 SWSD 保留样本，该场景须
以已有明确业务候选单独验证，不得扩展为通用 HYBRID。

M150–M153 已实现并验证 source-first 硬隔离，但均未超过普通 Segment 基线；
最好结果 M151=`676/920`，M153 即使事后选择 Fold1 最优 source 阈值也只有
`670/920`。因此不得继续以 source 阈值扫描解释为收敛。真值 source 条件下，
M69/M126/M150 完整 Road exact 分别为 `79.78%/80.98%/80.76%`，KEEP 均为
100%，而 USE 仅为 `60.68%/63.00%/62.58%`。当前下一训练目标收窄为锁定
source 后的 USE hard-negative 完整 Road bundle/member decoder；KEEP 直接
输出唯一完整冻结 SWSD 方案。Road 成员分数仍不得反向修改 source 或锚定，
AdvanceRight/Movement 继续后置。

M154–M158 已完成上述 source-locked USE canary。M154 member/cardinality
hard-negative、M155 relation bundle、M157 top-32 member graph 和 M158 无界
direct listwise 的 Fold1 exact 分别为 `293/473`、`296/473`、`294/473`、
`293/473`，均未超过 M126 的 `298/473`；10+ Road 均未超过 `9/30`。
M156 只扩大既有合法 USE 方案的保留宽度，使 Fold1 Oracle 从 top-12 的
`396/473` 提升到 top-32 的 `415/473`，但 M158 没有把新增 19 个正确方案中的
任何一个提升为 top-1。Oracle 不得视为模型输出精度。

因此当前不得继续扫描同类 reranker、epoch、阈值或候选宽度。下一研究阶段必须
先对 source-locked USE 的 top-1 错误方案做推理期证据可辨识性审计，按缺 Road、
多 Road、错误连接、内部连接、access/方向/拓扑不完整及 10+ Road 分层；只有
确认现有 Road/关系证据能区分正确与错误完整方案后，才允许重建 Road-level
监督和完整集合 decoder。source 与锚定硬门禁不变，KEEP 仍输出唯一完整冻结
SWSD 方案，AdvanceRight/Movement 继续后置。

## 16. Target A Junction 唯一锚定—Segment 完整方案架构收口（2026-08-04）

ARCH-CLOSURE-P0 已将当前普通 Segment 主线收敛为三层边界：Layer A 按唯一
`case_key + semantic_junction_id` 计算并广播锚定；Layer B 按唯一
`case_key + segment_id` 读取锁定锚定并选择完整 Road/access/break/Node Plan；
Layer C 只在同一 Junction 的直接关联 Segment 范围执行确定性
`ACCEPT/FALLBACK`。Segment Plan 不得反向修改锚定，Road member 不得反向修改
source，fallback 不得沿 `Junction—Segment—Junction` 递归扩张。

引用式 `JunctionStore/SegmentStore/PlanStore` 和 16 项 Gate 0 已通过：一个
Junction 一份结果、required 引用/候选/广播合法、一个 Segment 一个完整 Plan、
Road owner 唯一、Unknown/终态 mask 与两类梯度隔离正确、无 T03–T06 终态推理
输入、T01 骨架不变、CRS/方向/ID 合法且 `silent_fix=0`。P0 固定 Fold1 canary
的 Segment Full Exact 仍为 `8/24`、Junction Group Exact 仍为 `6/18`，
structured plan exact `971/1209→959/1209`，正确 USE `139→109`，正式结论
`ARCH_CANARY_NO_GO`。引用式缓存把峰值 RAM 从 R46 约 25 GiB 降至约 4.72 GiB，
因此 IO/重复子图问题已关闭，但旧锚定边界不得进入五折。

用户随后选择重训真正的唯一 Junction Layer A。UNIQUE-JUNCTION-P1 固定
Fold1、seed=`20261660`、8 epoch、LR=`2e-5`、gate=`0.5`，以无向直接依赖
ego graph、结构证据和完整 member-set loss 训练 19,422,227 参数模型；未扫描
epoch/threshold/seed，也未增加局部 safety head 或 reranker。完整锚定业务 exact
从 `908/1145=0.793013` 提升到 `921/1145=0.804367`，但 Gold 从
`129/159=0.811321` 降至 `127/159=0.798742`，SUCCESS 完整对象从
`791/961` 降至 `782/961`，正向 `NO_EVIDENCE` 从 `32/47` 降至 `29/47`，
dangerous automatic `12→13`、unknown automatic `165→169`。正式结论为
**`UNIQUE_JUNCTION_CANARY_NO_GO`**；不得生成五折 OOF `JunctionStore`，也不得
启动读取该结果的 Layer B Segment Plan。

该 NO-GO 否定本次唯一 Junction 训练目标与现有监督配比，不否定唯一 forward
边界或整个神经网络方向。训练折 Gold/Silver 为 `624/3165`，完整对象监督仅
`121/2414`；按现有 `1.0/0.7` 权重，对象 loss 仍由 Silver 主导，实测提升集中在
Silver `+15`，Gold `-2`。当前具体缺失的监督信号是独立 Gold 的完整 Node/Road
anchor 集合，尤其 T10 Gold；不能泛化为候选不可达或 Case 整体不足。继续目标 A
前必须由用户重新选择：新增/复核该 Gold 监督、接受规则 fallback 的混合边界，或
结束当前结构。未经新边界授权，不得在 Fold1 继续调 loss、权重、epoch 或阈值。

正式工件位于
`outputs/_work/p05_neural_road_generation/target_a_unique_junction_p1_fold1_20260804_seed_20261660/`；
完整 P05 回归为 `786 passed, 1 warning`。本阶段未修改 T01–T12、正式接口、
几何或拓扑，不接生产。

用户于 2026-08-04 在 P1 `NO_GO` 后明确授权：允许在现有 Case 内补充/复核完整
Node/Road anchor Gold。该授权只改变下一阶段的监督边界，不新增 Case，不恢复
T03–T06 终态推理输入，也不授权继续 Fold1 调参。Phase 1 已在 6 个现有 T10
Case 中冻结 80 个 SWSD 语义 Junction：Fold0–3 各 16 条，Fold4 的两个 Case
各 8 条；覆盖 22 个 Node 集合、20 个单 Road、21 个 2–3 Road、16 个 4–9 Road
和唯一 1 个 10+ Road 对象。选样只使用既有 Silver SUCCESS 的对象类型/集合大小、
冻结直接 Segment 引用和固定 SHA256 排序，不读取模型预测、分数、错误或发布结果。

人工模板与 QGIS 工程不显示 Silver 选择或模型输出。`SUCCESS_CONFIRMED` 允许保存
多个等价正确的完整 candidate，并显式指定 preferred；其他裁决继续区分
`PROVEN_NO_EVIDENCE / AMBIGUOUS / CANDIDATE_MISSING`。严格回填器拒绝修改冻结
字段、越界 candidate、缺失证据说明、覆盖既有 Gold 和拆分 Road/Node bundle。
人工结果返回后只生成 label-only Gold overlay，并在冻结选样与 Case-grouped 隔离下
重建一次 Gold-first canary，推理 feature 必须字节不变。

初始标注包位于
`outputs/_work/p05_neural_road_generation/target_a_unique_junction_gold_phase1_20260804/`；
补齐原始 SWSD/RCSD 图层后的正式人工包为同根目录的 `_r1` 版本。80 条队列、4,674
个完整 candidate 组合、6 个相对路径 QGIS 工程及总工程均通过读回，空间图层统一
`EPSG:3857`，几何未修改、拓扑未改变、`silent_fix=0`。人工结果中的 27 个
`manual_preferred_candidate_id` 前缀 `|` 已规范化且保留原 CSV 备份；最终裁决为
77 条 `SUCCESS_CONFIRMED`、1 条 `CANDIDATE_MISSING`、1 条 `AMBIGUOUS` 和 1 条
`PROVEN_NO_EVIDENCE`。label-only overlay 保持 inference feature SHA256
`78a3f17c0d9bc47bdd516bfaf5544e7e96db8ec5eb3a9ee99b578e6b186376a6`
逐字节不变。

固定 Fold1 Gold-first canary 沿用 UNIQUE-JUNCTION-P1 的 19,422,227 参数结构、
seed=`20261660`、8 epoch、LR=`2e-5`、weight decay=`2e-4`、clip=`1.0` 和 gate
threshold=`0.5`，只将训练折 Gold/Silver 总 loss 质量固定为 `0.5/0.5`；未扫描
weight、epoch、threshold 或 seed。新 80 条按 Case-grouped 拆为训练 64、Fold1
留出 16。完整业务 exact `907/1145→919/1145`，新留出 Gold `10/16→11/16`；但
全 Gold `139/175→139/175`、SUCCESS 完整对象 `789/959→785/959`、正向
NO_EVIDENCE `32/47→30/47`、危险自动 `13→14`、unknown 自动 `165→170`。
因此正式结论仍为 `UNIQUE_JUNCTION_CANARY_NO_GO`，不得进入五折、OOF
`JunctionStore`、Layer B 或同类 Fold1 局部调参。80 条以 SUCCESS 对象为主，只有
1 条 `PROVEN_NO_EVIDENCE` 且不在 Fold1 留出集，不能据此声称 NO_EVIDENCE 已有
新增跨 Case 监督；1 条人工 Road 组合不在冻结候选集，继续保留为候选覆盖缺口，
不得补造为可训练成功标签。回填、overlay 和固定 canary 合入后的完整 P05 回归为
`796 passed, 1 warning`；唯一 warning 仍为既有 Transformer nested-tensor 提示。

用户后续授权继续按目标 A 验证同 forward 联合边界。T032-JOINT-ARCH-CLOSURE-P1
以 T01 的直接 `Junction—Segment` 业务依赖连通组为 forward 单元；每个唯一
Junction 只计算一次并先输出锚定状态和完整对象，普通 Segment 再读取 live
embedding 与已确认对象关系选择完整 Road/access/break/Node Plan。Segment decoder
仍不得反向选择锚定、扩充候选、改变骨架或把 fallback 沿相邻 Junction 递归扩张。

固定 Fold1 canary 使用 38,099,141 参数、seed=`20261670`、4 epoch（2 teacher +
2 free-run）和 PCGrad，未扫描参数。Segment Full Exact `6/24→9/24`、Junction
Group Exact `5/18→6/18`、structured plan exact `909/1209→982/1209`；但锚定
dangerous automatic `13→17`，ordinary unsafe automatic `22→25`，unknown
automatic 分别 `170→194`、`381→433`。新增 4 个危险锚定中有 3 个直接导致新增
危险 Segment；不存在跨 Junction fallback 扩散或 decoder 反向改锚定。四轮各有
238–255/822 个连通组出现 anchor/ordinary 共享梯度冲突。

正式结论为 `JOINT_ARCH_CLOSURE_CANARY_NO_GO`。该结果保留动态直接依赖子图、唯一
Junction 一次 forward、live 条件化与候选约束 decoder，淘汰 ordinary loss 直接
写入锚定决策参数的共享训练方式。下一架构必须在神经系统内部隔离该梯度写入；这不
恢复 T03–T06 旧策略，也不允许确定性层重新判断锚定业务事实。不得对本 Fold1 继续
做 loss、epoch、threshold、seed 或局部 head 搜索，AdvanceRight 继续后置。
本阶段完整 P05 回归为 `799 passed, 1 warning`；唯一 warning 为既有 Transformer
nested-tensor 提示。

## 17. Target A Junction-first Gold 数据与正式成功门（2026-08-04）

用户确认当前本地数据为本阶段全量数据，并授权 P05 自行决定训练/验证/测试划分。
五个权重 1.0 的 Gold 目录为 `POC_Data/T03`、`POC_Data/T03_Error`、
`POC_Data/T04`、`POC_Data/T04_Error` 和 `POC_QA/T03_Error`；这些 Case 的
当前正式规则重放结果视为人工确认。T10 中只有可明确追溯到具体 SWSD 语义路口的
锚定结果可按 0.7 监督，背景路口不得生成标签。完全重复输入只保留一个样本身份；
同 ID 多输入版本若终态业务签名一致则保持同 split 并均分该 Case 的 1.0 总权重，
终态冲突进入 `LABEL_REVIEW`，不得训练或测试。

743 个 Gold 目录记录归并为 716 个 Case ID；正式重放得到 surface
accepted/rejected/runtime_failed=`399/321/23`，RCSD 锚定业务状态
在 T05 延续前为 SUCCESS/NO_RCSD_EVIDENCE/QUALITY_ISSUE=`156/19/568`。399 个
accepted surface 已全部继续执行 T05：343 个完整 SUCCESS、19 个正向
NO_RCSD_EVIDENCE、37 个 Road-only 打断端点拓扑不完整；最终业务状态为
SUCCESS/NO_RCSD_EVIDENCE/QUALITY_ISSUE=`343/19/381`。706 条可用于完整路口 Gold，
37 条只用于 action/safety，不补造完整拓扑。24 个多版本 Case 中
8 个终态一致、16 个终态冲突。最终冻结 700 个 Case group、708 个输入版本为
train/validation/test=`490/105/105` 个 group，输入版本=`497/105/106`，有效权重
同为 `490/105/105`；同一
Case、语义路口或输入版本不跨 split，训练集覆盖全部现有终态组合。测试集不得用于
结构、loss、epoch、阈值或 seed 选择。

路口阶段 GO 要求：Gold 冻结测试 raw 完整路口 exact `>=0.85`、自动业务决策覆盖
`>=0.80`、自动接受完整正确率 `=1.0`、危险自动接受和真值未知自动接受均为 0、
已证明异常不得判正常且异常或安全 `ABSTAIN` recall=`1.0`；T10 留出 weighted
exact `>=0.75`。完整路口 exact 同时比较 surface、锚定状态、RCSD 对象完整集合、
聚合/打断方案、重构拓扑与质量状态。相同输入/输出/环境下总耗时不得超过现有
T07+T03+T04+T05 规则链的 1.5 倍，城市输入只允许完整读取并建立一次索引。上述
任一门禁未通过时普通 Segment、AdvanceRight、Movement 均继续关闭。
