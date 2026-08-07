# Tasks

## Phase 1：源事实与数据合同

- [x] T001 更新 P05/项目级源事实，保留旧实验历史；
- [x] T002 建立 Target A label schema 与五个人工裁决；
- [x] T003 建立 scope/weight/mask adapter；
- [x] T004 建立 inference feature 与 label 物理隔离；
- [x] T005 建立 leakage audit；
- [x] T006 生成数据预检与监督覆盖报告。

## Phase 2：候选与业务约束

- [x] T010 构建 truth-free anchor candidates；
- [x] T011 构建 ordinary complete plan candidates；
- [x] T012 构建 RCSD internal connector tree candidates（v114 对物理并行
  Road 聚合后执行树、叶节点仅挂接 MAIN、无外部叶和完整所有权证明；
  6,651 个候选全部通过，旧 9 个可达完整 Road 清单零丢失）；
- [x] T013 构建 conditional AdvanceRight plan candidates（含两侧普通 Segment
  最终 source/access Road 锁定、完整提右 Road 组合、几何/挂接候选）；
- [ ] T014 实现 ownership/access/topology hard masks（Road 唯一所有权、
  有限 fallback、骨架不变和确定性 Node/方向/split/reverse/splice/
  attachment materializer 已实现并通过 51 Case T01 fallback 审计；
  v132 已按完整 Road/Node access binding 重建为 45/51 Case 可完整物化、
  51/51 可物化依赖完整子图，8,818/8,863 个 Segment 严格物化；
  `ADVANCE_RIGHT_LEDGER_UNRESOLVED=0`。v207 已以纯推理字段选出一个真实
  ordinary whole-Road 方案并双跑一致；v208 对 348 个同类自动 USE 方案
  审计，114 个可直接执行，234 个因冻结 access 方向语义不一致被逐 Segment
  hard mask；v209 已将 1 个自动 RCSD + 25 个显式 Segment fallback 组成
  完整 26-Segment Case，一次物化 38 Road/41 Node/58 access，骨架变化、
  silent fix 和内容修复均为 0。全链 ledger 已修正 AdvanceRight
  `source_access_road_id/target_access_road_id` 的正式含义：它们引用相邻
  普通 Segment 的最终 access Road，不是提右自有 carrier；新增端点复用型
  AdvanceRight 编译器，可执行完整提右 Road + 两侧锁定 binding/父 Road/
  child endpoint，并按 RCSD `ROAD_POSITION`、SWSD
  `FROZEN_ACCESS_NODE` 分开写出。AdvanceRight 正向 KEEP 也不再无条件
  复用 T01 fallback，而必须提供与两侧最终 access 条件一致的执行指令。
  对旧 v103 的 474 条 strict OOF 做只按预测字段的结构审计，49 条
  （10.3376%）满足“两侧显式 `REUSE_ENDPOINT` + 非 MIXED”编译范围，
  但安全门自动接受为 0；该范围只证明执行合同，不产生发布覆盖。
  方案 A 裁决后已新增独立 `ADVANCE_RIGHT_MIXED_SPLICE` 编译器：
  显式执行相邻普通 RCSD access Road 打断、RCSD/SWSD retained interval、
  中间/端点衔接、两侧 attachment 和最终方向；普通 Segment 仍无通用
  HYBRID。v212 将中间 split 的 `SOURCE_PART/TARGET_PART` 作为多解候选
  进入 113D 几何头，135/139 条预测 MIXED 已具完整结构 recipe，但自动
  接受为 0。v217 进一步串联 v146 普通/挂接条件后，完整
  plan+geometry raw exact=`0.162447`、端到端 raw exact=`0.006329`、
  自动接受 0，说明分阶段条件误差仍未收敛；
  旧 1,243 个普通 Segment 和
  431 个 AdvanceRight blocker 来自错误的“唯一 access Road”假设，已撤销，
  不再作为缺标签结论。尚缺 Road/打断锚定、普通 junc access 集合、
  AdvanceRight 中间父 Road 打断/片段/splice 自动指令、真实自动提右完整
  Case 与城市级一次写出，因此任务不关闭）；
- [x] T015 实现所有权联合约束与显式有限 `FallbackDirective`；删除通用传递
  conflict components，并以 `J1—S1—J2—S2` 测试证明作用域止步。

## Phase 3：模型

- [x] T020 实现 geometry/set/heterogeneous shared encoder；
- [x] T021 实现 anchor head 与 unique/ambiguous/abstain；
- [x] T022 实现 ordinary complete-plan head；
- [x] T023 实现 clue/affected/scope head；
- [x] T024 实现 conditional AdvanceRight head；
- [x] T025 实现 constrained RoadGraph decoder；
- [x] T026 实现 DecisionLedger。

## Phase 4：训练

- [x] T030 anchor pretrain；
- [x] T030a T03/T04 正式重放并以 T05 最终关系重建锚定监督；
- [x] T030b learned resolved/unresolved gate 与 strict inner-only safety；
- [x] T030c 冻结 base 的 posthoc gate 和独立 evidence encoder；
- [ ] T030d 锚定零危险发布门（补全 required-anchor scope 后的 v109
  /v110 strict safety 接受项中仍有 17 个有监督错误和 15 个不可验证
  自动项；v51 的 14 个只保留为旧不完整 store 历史诊断）；
- [x] T031 ordinary teacher-forcing training；
- [x] T032 OOF anchor conditioned ordinary training（严格单 seed 诊断完成，
  当前 `NO_GO`；v136 以显式集合大小 + top-k 和 teacher/OOF 双视图把
  完整 access OOF exact 从 v127 的 `0.339002` 提升到 `0.433107`，
  但唯一自动接受项错误，仍全部 fallback）；
- [x] T032-R1 精确 Error 标签作用域、Phase 1 的 72 条人工裁决和 6 条指定
  裁决回填；修正任一 required anchor 失败即 Segment fallback 的训练/推理
  硬门；v55/v56/v57 均为 `NO_GO`；
- [x] T032-R2 共享 anchor/ordinary gate 联合训练，以 Segment fallback
  loss 约束 anchor false positive，同时保持锚定对象唯一选择独立输出；
  v112/v113 已在完整 5,148 required-anchor scope 上完成 strict-nested
  单 seed OOF，v113 仍有 25 个锚定监督错误、28 个不可验证锚定、
  5 个 Segment 监督错误和 22 个不可验证 Segment，发布门 `NO_GO`；
  T012 后的 v119 重训仍有 25 个锚定监督错误、28 个不可验证锚定、
  5 个 Segment 监督错误和 21 个不可验证 Segment；v110∩v113 仍非零
  危险且覆盖更低，不向 Road/carrier 下游释放；
- [x] T033 AR teacher-forcing training（v97/v103 单 seed strict-nested
  诊断完成；v134 将 756 条 T06 挂接动作重建为 619 强监督、76 弱监督、
  61 屏蔽，排除 725 条确定性 Node 规范化；v212/v217 已把独立
  MIXED_SPLICE parent-piece recipe 接入几何训练，但正式发布门仍
  `NO_GO`）；
- [x] T034 OOF ordinary-access conditioned AR training（v95/v97/v103
  完成推理期 access 条件化与严格 OOF；v137 在 563 条候选精确可达
  强监督上取得 side attachment OOF exact=`0.943162`，但 56 条强监督
  仍候选不可达且上游完整 access release-ready=0，发布门 `NO_GO`）；
- [x] T035 joint fine-tuning（v104r1 已在“相邻普通 Segment 两侧
  source/access → 条件化 AdvanceRight”依赖层联合训练；不代表
  anchor/ordinary/AdvanceRight 全量共享 encoder 已完成，结果
  `NO_GO`；v201/v204 已补 ordinary Road shared encoder + 完整方案
  acceptable-set/validity 联合梯度的 fold 0 诊断，raw exact 提升到
  0.719542/0.722813，但危险自动项为 19/22；v218 在 v217 同一严格
  OOF 条件上进一步让 AdvanceRight carrier 与 geometry head 联合更新，
  complete plan+geometry raw exact 从 `0.162447` 升至 `0.177215`，
  geometry action exact 从 `0.203704` 升至 `0.268519`，但普通 Segment
  完整 Road/access 条件仍是固定 OOF 输入，raw end-to-end 仍为
  `0.006329`、自动接受仍为 0；v219–v222 又把 ordinary 完整 Road
  集合与 access 父 Road拆成共享 encoder 上的独立 heads，并复用 v142
  普通 Segment 预训练 checkpoint。当前业务合法的 v222 在 847 个有监督
  ordinary 侧上 Road-set exact=`0.081464`、source exact=`0.907173`、
  563 个 RCSD access exact=`0.948490`，两侧 ordinary exact 和端到端
  exact 均为 `0.006329`，自动接受仍为 0；v223 证明 ordinary 使用
  `0.1×` 学习率可把 Road-set/端到端 exact 提升到
  `0.095632/0.008439`。v224–v226 排除了跨 anchor-graph 结构直接迁移
  v175 encoder；v227r1 在同构 set forward 上用 3,160 个普通 Segment
  做 ownership/role 辅助预训练，ordinary 总体 complete exact
  `0.610443`，低于 v142 的 `0.625712`，但同 seed 接入的 v228 在提右
  依赖侧取得 Road-set exact=`0.102715`、端到端 exact=`0.014768`。
  v228 自动接受仍为 0。以上均 `NO_GO`，不扩完整 3-seed）；
- [ ] T036 5-fold × 3-seed OOF（v97/v103/v104r1 均只完成单 seed ×
  5 Case folds；单 seed 已出现危险自动项或零自动覆盖，不扩另外两个
  seed）；

## Phase 5：测试与 QA

- [x] T040 unit tests；
- [x] T041 leakage audit（feature/label 隔离与训练 outer/inner 隔离均已通过）；
- [ ] T042 deterministic double-run（v207 单真实 Segment和 v209 完整
  26-Segment Case 的 canonical hash 双跑一致；尚缺全 51 Case 与训练推理
  主链双跑，任务不关闭）；
- [ ] T043 CRS/几何/拓扑验证（候选层和 v122/v123 materializer 审计均
  已由 v132 access-collection materializer 审计替代：CRS
  metric/consistent 51/51，`silent_fix=false`、`content_repair=false`、
  所有权与骨架审计已通过；已严格物化 8,818/8,863 个冻结 Segment，
  其余 45 个源事实 invalid/不连续几何对象均局部阻断。v209 已完成一个
  含自动 RCSD 普通 Segment 的完整 26-Segment Case RoadGraph 物化；
  v208 的 234/348 方向 hard-mask 说明完整发布仍缺普通计划的有向可达
  预检；端点复用型自动 AdvanceRight 已接入 materializer 单元全链，
  独立 MIXED_SPLICE split/splice 已完成合成整图执行与训练输出绑定，
  但 v217/v218/v222 没有真实自动接受结果，仍未完成真实 Case 级验证。v134 的
  619 条强挂接监督最终端点几何最大回投误差
  `1.862645149e-09m`，尚未形成完整提右 RoadGraph 验收，不能关闭）；
- [ ] T044 49 LEGAL + 2 EXPECTED_FAIL 安全基线；
- [ ] T045 完整策略 paired comparison；
- [ ] T046 自动决策与 fallback 后整图 exact；
- [ ] T047 category/fold worst-case；
- [ ] T048 城市级无标签 I/O/runtime profile（若有城市数据）。

## 完成条件

上述任务全部有可定位工件；任一 unsafe auto、Review auto、unreachable auto、
skeleton mutation、silent fix 或新增图 hard failure 非零，正式结论必须为 NO_GO。

## 2026-07-26 第一轮训练状态

- 已完成单 seed × 5 Case folds 的诊断性 anchor cross-fold，以及普通 Segment
  teacher-forcing cross-fold；尚未完成 T032–T036。
- v4 anchor 表示加入 T01 语义路口道路臂、原始 RCSD 候选道路臂匹配和
  DriveZone 相对证据；不使用 T03–T06 终态输入。
- v4 anchor OOF `5179/5179` 覆盖，status accuracy=`0.898629`，
  supported macro F1=`0.791797`，对象 acceptable exact=`0.841587`。
- 折外安全门禁接受 `240/5179`，其中正确 `236`、错误 `4`，因此
  anchor 阶段为 **NO_GO**。
- 在 `4238` 个候选可达普通 Segment 中，`88` 个通过全部 required-anchor
  门禁；其中 `4` 个依赖错误锚定。串联既有普通方案 OOF 后 `83/88`
  Road 方案 exact，仍有 `5` 个错误自动方案；fold 4 门禁覆盖为 `0`，
  不具备五折锚定条件化普通 Segment 重训条件。
- conditional AdvanceRight、完整有限作用域 decoder、最终 RoadGraph、安全基线和
  完整策略 paired comparison 尚未执行，不能把本阶段解释为目标 A 完成。
- 补充两个 seed 后，三种子诊断性共识仍有 `4` 个错误自动锚定；串联普通
  teacher-forcing 方案后有 `11` 个错误整链结果，T032 继续禁止启动。
- 旧 runner 使用 outer held-out 做 early stopping，三种子数值已降级为
  诊断证据。严格 outer/inner nested runner 已完成锚定阶段重训；
  T036 仍须在锚定安全门通过后完成整个目标 A 的 `3 seeds × 5 folds`。

## 2026-07-27 严格锚定 OOF 与 T01 依赖图结论

严格 outer/inner nested 的旧单锚定 forward（v8）完成
`3 seeds × 5 folds`。各 outer fold 的安全阈值只由 inner-validation 确定。
三种子共识接受 `281/5179`，其中安全 `275`、危险自动锚定 `6`；
Fold 2 安全自动锚定为 `0`，锚定门禁为 **NO_GO**。

为验证“缺少 T01 业务依赖上下文”这一具体假设，v9 增加由冻结 T01
`pair_nodes/junc_nodes` 派生的直接依赖 ego graph：

- 不读取 T03–T06 终态，不改变 T01 骨架；
- 每个 focal 锚定只观察其 T01 直接依赖锚定对象；
- 依赖邻居只提供推理期上下文，不复制邻居标签或候选监督；
- `5179` 个 forward group，平均 `5.0568` 个有效对象，最大 `43`；
- 模型参数量 `17,825,294`。

v9 严格 OOF：

| seed | status accuracy | supported macro F1 | 对象 acceptable exact |
|---:|---:|---:|---:|
| 20260727 | 0.813864 | 0.625808 | 0.811234 |
| 20260827 | 0.835296 | 0.655002 | 0.815224 |
| 20260927 | 0.782197 | 0.585386 | 0.819521 |

inner-only 三种子共识接受 `1312/5179`，其中安全 `1281`、危险自动锚定
`31`，accepted coverage=`0.253331`；危险项包括 `17` 个 NODE 与
`14` 个 ROAD，Fold 2 安全自动锚定仍为 `0`。因此 v9 同样为
**NO_GO**，且安全性显著劣于 v8。T032–T036 继续禁止启动。

该结果只否定“现有联合 head 加 T01 直接依赖图即可过锚定门”这一实现，
不否定目标 A。下一轮应把锚定拆成证据/可判定性门、条件化对象类型
（Node 或 Road/打断）和结构化唯一对象/最小 Road 组合。

## 2026-07-27 v10 分层锚定迭代

v10 已把锚定显式拆为：

1. 独立 evidence/status head，不读取已选候选；
2. Node/Road 可接受类型集合 head；
3. 锁定类型后的条件化对象选择，后层不能反向改变类型。

现有标注可直接监督该拆分：`3542` 个 SUCCESS、`190` 个 NO_EVIDENCE、
`1447` 个 ABSTAIN；`3258` 个对象监督中，`2280` 个只接受 Node、
`898` 个只接受 Road、`80` 个 Node/Road 均可接受。多解样本使用集合 loss，
未强造单一类型真值。模型参数量为 `18,818,992`。

单 seed 严格 `5-fold nested OOF`：

- status accuracy=`0.798031`；
- supported macro F1=`0.598006`；
- 类型 acceptable exact=`0.934009`；
- 对象 acceptable exact=`0.812462`；
- 类型正确但对象错误=`396`。

按各 outer fold 的 inner-validation 独立确定单 seed 诊断安全阈值后：

- 自动接受=`1387/5179`；
- 安全自动锚定=`1351`；
- 危险自动锚定=`36`；
- accepted coverage=`0.267812`；
- 危险标签：ABSTAIN `14`、NO_EVIDENCE `3`、SUCCESS 对象错误 `19`；
- Fold 2 自动接受=`0`。

因此 v10 单 seed 已足以判定不值得继续消耗资源扩展另外两个 seed；
当前分层实现仍为 **NO_GO**，T032–T036 继续禁止启动。下一轮应针对
“类型内具体对象/最小 Road 组合”增加结构化对象监督或 decoder，而不是继续
调整类型 head。

## 2026-07-27 v11 结构化对象 decoder 诊断

v11 在 v10 上增加：

- 由推理期候选成员清单派生的同类型、相等、严格子集、严格超集、
  Jaccard、成员数与对称差关系；
- relation-aware 类型内候选聚合；
- balanced per-candidate validity BCE，与 acceptable-set loss 联合训练。

关系输入不保存或 embedding raw ID，也不使用锚定标签。模型参数量
`19,318,833`。由于 pairwise 候选关系使训练成本约增至 v10 的 2–3 倍，
预先约定先观察前两个 outer folds，若不能形成稳定改善则终止。

结果：

| fold | status accuracy | supported macro F1 | 对象 acceptable exact |
|---:|---:|---:|---:|
| 0 | 0.932318 | 0.850114 | 0.826556 |
| 1 | 0.752024 | 0.493170 | 0.791011 |

Fold 0 状态指标明显上升，但对象 exact 仅比 v10 同折 `0.825726` 高
`0.000830`；Fold 1 三项均显著恶化。该结构呈现 Case/seed 特异收益，
没有跨折稳定性，且计算成本明显增加，因此在 Fold 2–4 前主动终止。
v11 只作为诊断失败工件保留，不扩三种子，不改变 T032–T036 的禁止状态。

## 2026-07-27 v12–v20 正式锚定迭代

- v12 组合式对象 decoder 完整五折对象 exact=`0.820135`；v13r1 候选残差
  和 v14 hard cardinality 只完成前两折诊断，均未形成稳定改善。
- v15 soft cardinality 在旧监督下对象 exact=`0.829343`，但正式重放证明
  其把 T03/T04 上游成功误作最终锚定成功，旧 status 指标作废。
- 正式重放得到 `103` 个 T05 最终成功对象、`5` 个明确 NO_EVIDENCE、
  `12` 个最终原因未知 mask；成功对象中 `91/103` 候选精确可达。
- v16 使用正式 replay 标签后，strict safety=`1210` 接受 /
  `1168` 安全 / `42` 危险。
- v17 learned gate 将危险降至 `16`；v18 把全部正式 ABSTAIN 纳入联合 gate
  loss 后负迁移，危险升至 `45`。
- v19 冻结 shared/candidate，仅训练 gate head；candidate exact 与 v17
  逐样本一致，但仍有 `19` 个危险。
- v20 独立 `583D` evidence encoder（`124,994` 参数）是当前最好单 gate：
  `740` 接受 / `727` 安全 / `13` 危险，Fold 2 有 `20` 个安全接受，
  同 seed 双跑三份正式 JSONL hash 完全一致。
- v17/v19/v20 交集仍有 `10` 个稳定危险；曾以 T01 传递闭包做整组原子接受，
  虽得到 `0` 危险和 `9/5179`，但该规则违反已确认的 Segment/Junction 阻断
  边界，现只保留为反例诊断，禁止进入模型、decoder 或覆盖率结论。
- decoder 已按方案 A 改为显式 fallback 指令：Segment 只回退自身；Junction
  只影响显式列出且经冻结 T01 关系校验的直接关联 Segment；禁止传递闭包。
  Road 所有权联合求解与 fallback 作用域解耦。
- v21 candidate safety verifier 得到 `727` 接受 / `716` 安全 / `11` 危险；
  对部分错误完整对象集合仍给出 `0.98–0.999` 高分，判定
  **CANDIDATE_VERIFIER_NO_GO**。
- v22 member 集合置信度 oracle 诊断在零危险时最多保留 `90/716` 个安全决定，
  不能作为事后校准器。
- v23 member loss 使对象 exact 小幅升至 `0.823231`，但 macro F1 降至
  `0.759273`、ABSTAIN recall 降至 `0.818936`；v24 独立 gate 仍有
  `569` 接受 / `548` 安全 / `21` 危险。该路线终止。
- v25 已因旧、新 replay store 的候选/特征和监督语义不同而在训练前拒绝，
  禁止跨 replay 拼接旧 checkpoint、OOF 与当前 gate 标签。
- v26 移除 shared gate loss 后，Fold 0 的 status/macro/candidate 三项均降，
  Fold 1 只有 candidate exact `+0.002207`，status 与 macro 继续下降；已停止
  Fold 2–4，判定 **DECOUPLED_BASE_NO_GO**，v27 不启动。
- v28 冻结 base、仅训练 `373,122` 参数完整候选 residual；status/gate 保持
  不变，但 candidate exact 在 Fold 0 `+0.008190`、Fold 1 `-0.004415`，
  判定 **POSTHOC_CANDIDATE_RESIDUAL_NO_GO**，停止 Fold 2–4。
- 重复对象审计发现 T03/T04 与 T10 有 `13` 组相同 `anchor_id`；status 监督
  一致，但其中 1 组因完整上下文新增 RCSD 方案而具有不同 acceptable 集合。
  禁止按 raw ID 复制标签或建立 teacher 终态输入。
- 当前判定 **BEST_SINGLE_GATE_NO_GO**；T030d 未完成，T032–T036 继续禁止。

## 2026-07-28 T032 条件化普通 Segment 结论

经用户确认按方案 A 的有限 fallback 作用域继续后，T032 已使用 v20r1 的
case-OOF 锚定输出完成严格 outer/inner OOF。该启动不表示 T030d 已通过：
锚定失败的任意普通 Segment 均由硬门禁回退；正向 `KEEP_SWSD` 也只有在
required anchor 成功后才能作为自动 carrier 决定，后续 Road 分数不能修改
锚定。v35–v48 将 KEEP 排除在该门禁之外的覆盖率与自动 exact 仅保留为历史
结构对照，不能再解释为正式业务指标。

- 样本=`4238`，标签仍可达=`4194`，锚定门禁 fallback=`44`；
- v35 基础条件化完整 plan exact=`0.912017`；
- v38 增加锚定对象与候选 Road plan 的关系后 exact=`0.918455`；
- v39 有界 residual 总体=`0.920124`，但最差 fold=`0.740864`，不采用；
- v40 额外 decision loss 导致 USE 退化，判定 `NO_GO`；
- v41 显式业务状态后再选完整 Road plan、只使用 joint plan loss：
  exact=`0.923939`、KEEP=`0.955926`、USE=`0.795455`，保留为 USE 总体对照；
- v42 Case balance 最差 fold 提升到 `0.827243`，但 USE 降至
  `0.738038` 且出现最高约 `175×` 的 Case 权重，不采用；
- v43 增加 KEEP/USE 逐 Road 成员集合并让成员证据同时进入业务状态与 bundle
  选择：exact=`0.928946`、KEEP=`0.971412`、USE=`0.758373`，
  `within-USE` 错误降至 `46`，但产生明显 KEEP 偏置；
- v44 将成员证据限制在业务状态内部的完整 Road bundle 排序：
  exact=`0.929423`、KEEP=`0.967838`、USE=`0.775120`、最差
  fold=`0.843854`，`within-USE` 错误进一步降至 `37`；总体当前最好，
  但 USE 仍低于 v41，且 `T10:1885118` 相对 v41 多错 `29` 个；
- v45 增加对称的 SWSD 两端 arm ↔ 候选 Road 端点匹配：
  exact=`0.936338`、KEEP=`0.970816`、USE=`0.797847`、最差
  fold=`0.850498`、最差 USE fold=`0.756881`；相对 v41 净改善
  `52` 个样本，六个主要 T10 Case 均净改善或持平，成为当前结构基线；
- v46 将 OOF 锚定关系细分为当前端 local 与另一端 foreign：
  exact=`0.936576`、KEEP=`0.967242`、USE=`0.813397`；相对 v45
  `41` 修复、`40` 回归，只净改善 `1`，且危险 `KEEP->USE` 从
  `98` 增至 `110`。按安全优先不替代 v45，只保留为端点关系诊断；
- 全部运行 `unsafe_anchor_bypass_count=0`，但这只证明没有绕过模型锚定
  hard mask，不证明锚定对象本身零错误。
- v47 固定 v45 carrier，仅以 462D 推理证据训练 strict-nested USE
  safety head：接受 `189/798` 个 USE，其中正确 `180`、危险 `9`，
  `NO_GO`；
- v48 加入来自全量 8,863 Segment truth-free candidate store 的
  Junction 邻接统计：接受 `217/798` 个 USE，其中正确 `203`、危险
  `14`，仍为 `NO_GO`，且相对 v47 退化；
- Clue/fallback-scope task mask 全量只有 `5` 条，ordinary 训练范围只有
  `4` 条。8 个 v47 危险 `KEEP->USE` 全是权重 `0.7` 的 T10 Case
  终态标签，均没有 Clue/scope 监督。

T032 因此记为“实现与单 seed 严格诊断已完成、发布门 NO_GO”。T030d 仍未完成；
T033–T036 继续保持未启动。下一步不再进行 residual、class balance 或
Case balance 调参；保留 v45/v46/v44/v41 paired OOF，先审计
`KEEP_SWSD -> USE_RCSD` 危险错误能否被独立 safety head 拒识。v47/v48
已经证明该门禁不能由当前局部/邻接输入可靠完成；下一步先补足可审计的
KEEP 原因、Clue、Segment/Junction scope 和直接影响对象监督，再训练共享
Junction 状态与 carrier，不能从 KEEP 终态补造原因。

已完成补标前准备但未开始裁决：从现有 Case 生成 363 条
`UNKNOWN/PENDING` 队列（P0 safety 危险 20、P1 carrier 错误 247、
P1 anchor fallback 44、正确对照 52），并锁定继承 5 条用户人工裁决。
T06/T11 自动映射数为 0。待用户确认字段和值域后，才允许写回新的
label-only 工件和训练 Clue/scope head。

队列 `_02` 已按最小 review task 拆分：carrier plan 363、KEEP 原因/
Clue/scope 128、anchor 44。Phase 1 为 72 条 carrier，其中 47 条同时
需要 KEEP/Clue/scope；remaining 为 291 条。两批互斥并完整覆盖队列。

## 2026-07-29～2026-07-30 v229–v241 结构化 Road set 与最终状态条件化

- [x] T032-R3 在 3,160 个普通 Segment 上训练 count-aware 和
  order-free set-expansion decoder；v231/v233 将完整 Road set exact
  提升至 `0.713291/0.707911`，但 10+ Road Segment exact 仅为
  `0.184932/0.219178`，主要错误是提前 STOP 和集合基数低估。
- [x] T032-R4 以两个独立 strict Case-OOF seed 的完全一致结果建立普通
  Segment 发布门。首次 v234 错误地让 `USE_RCSD` 绕过 required-anchor，
  已废止。按用户确认的方案 A 修正后，v234r1 要求 KEEP/USE 均通过锚定
  前置门禁（仅显式推理期无证据证明可豁免 KEEP），并要求两个 seed 的完整
  Road set、逐 Road ownership 和业务角色一致。自动接受 `113/3160`，
  全部为正向 `KEEP_SWSD`，selected business truth `113/113` 正确，
  `USE_RCSD=0`、unsafe/unverifiable automatic 均为 0。
- [x] T033-R1 从普通 Segment OOF 结果构建 AdvanceRight 最终状态条件，
  明确区分 `POSITIVE_KEEP_SWSD`、`FALLBACK_SWSD` 和
  `AUTO_USE_RCSD`；v235r1 共锁定 868/948 个侧状态，80 个缺少直接
  owner/candidate 的侧保持局部 fallback，feature/teacher/label 物理文件
  通过 hardlink 复用，无真值进入推理条件。
- [x] T034-R1 修正 AdvanceRight 条件目标：当两侧普通 Segment 最终均为
  完整、可达且可执行的 SWSD 状态时，正式条件方案为 `SWSD_ONLY`，不再
  沿用普通 Segment fallback 前的 RCSD/Review 目标。该修正不读取 T06
  终态作为推理输入。
- [x] T035-R1 完成两个独立 strict OOF seed 和一致性发布门。v237/v239
  分别自动接受 `416/430` 个对象，二者方案无分歧；v240 只接受交集
  `414/474`，automatic coverage=`0.873418`、complete plan exact=`1.0`、
  unsafe automatic=`0`。当前自动范围全部为 `SWSD_ONLY`，不能解释为
  RCSD_ONLY 或 MIXED_SPLICE 已收敛。
- [x] T043-R1 以 v240 结果执行 51 Case 最终状态 materializer 审计。
  v241r1 的 414 个 AdvanceRight 自动决定全部可物化，Road/Node/attachment
  分别为 `14,193/12,745/868`；hard failure、skeleton mutation、
  silent fix、content repair 均为 0。错误放行的 26 个普通 USE 已在
  v234r1 门禁层退出，materializer `preflight_fallback=0`；45 个冻结
  Segment 的既有 T01/source blocker 保持局部阻断，不扩张依赖闭包。
- [x] T040-R1 新增 set expansion、双种子发布、最终状态条件化和
  materializer 合同测试；完整 P05 回归为 `598 passed, 1 warning`。
- [x] T032-R5 针对 10+ Road bundle 训练 access/主干 seed 条件化扩展、
  显式 `CONTINUE_FRONTIER/START_COMPONENT/STOP` decoder 和完整方案 beam
  audit。v244r1 fold2 overall exact=`0.701754`、Road macro
  F1=`0.847126`、unsafe automatic=`0`，但 10+ Road exact 只有 `2/16`；
  不扩完整 OOF。v245 truth-free beam oracle@4/8/16/32 分别为
  `0.830409/0.865497/0.897661/0.923977`，10+ Road oracle@16=`7/16`，
  证明当前主要瓶颈已从候选可达转为完整方案选择。
- [x] T032-R6 训练严格 inner/outer Case-disjoint 完整方案 reranker。v246
  32D 方案摘要 raw exact=`0.701754`、10+ Road=`2/16`，零危险自动覆盖
  `113/342=0.330409`；v247 加入冻结 Road embedding 后跨 Case 退化为
  raw exact=`0.611111`、10+ Road=`0/16`、零危险覆盖=`0.195906`。
  两者均不扩完整 OOF；v247 证明直接加入高维 Road embedding 会过拟合，
  不能用扩大模型代替 case-invariant 关系表达。
- [x] T032-R7 在不读取终态真值的前提下，完成关系摘要、结构化能量、
  same-plan affinity 和 pairwise complete-plan decoder 的严格 fold2
  canary。v249 raw exact=`0.716374`、10+ Road=`2/16`，但出现
  unsafe automatic=`1`；v253 的 relation-only pair F1 达到
  `0.654739`，仍未改善完整方案排序。v254/v255 经口径拆分后，
  reachable-plan exact 分别为 `0.787582/0.781046`，长集合 reachable
  exact 仅 `1/7`、`2/7`；不得把 unreachable 上正确 ABSTAIN 计作
  carrier 方案 exact。所有路线均未同时超过 v244r1 raw exact、
  v246 零危险覆盖和 10+ Road exact，不扩完整 OOF。
- [x] T032-R8 构建 Case 级 combined batch，使 SWSD 语义路口锚定候选、
  普通 Segment 完整 Road 方案及其共享 Road/Node/Junction/access 证据在
  同一 forward 中编码。锚定头仍必须独立输出唯一对象或
  `AMBIGUOUS/NO_VALID_RELATION`，carrier loss 不得反向选择、修改或绕过
  锚定结果；只有共享 encoder 可同时从锚定和 carrier 监督中学习。
  先以严格 fold2 canary 验证 concrete anchor object exact、锚定安全释放、
  reachable complete-plan exact 和零危险联合覆盖，再决定是否扩完整 OOF。
- [ ] T032-R9 按 v263 Phase 1 队列裁决 30 个 SWSD 语义路口锚定真值，
  仅允许 `SUCCESS_UNIQUE + 一个既有候选对象`、`PROVEN_NO_EVIDENCE`、
  `AMBIGUOUS` 或 `CANDIDATE_MISSING`。`relation_record_absent` 继续只表示
  真值未知，不得自动补成成功、失败或无证据。回填 label-only 工件后重训
  同一 fold；在零危险/零 Review 前不得扩完整 OOF。
- [x] T032-R9a 审计 v263 的 198 个待裁决对象能否严格继承现有
  T03/T04 正式重放或 T11 人工真值。禁止按空间近邻、模型预测或仅 ID 重名
  继承；v265 结果为跨样本严格复用 `0`。另有 1 个对象已由同 Case T11
  人工记录证明正确 RCSD Road 不在冻结候选集，固化为
  `CANDIDATE_MISSING -> Segment fallback`，全量剩余 197，Phase 1 仍为 30。
- [x] T032-R9b 实现 Phase 1 CSV 冻结列和完整作用域校验、四类人工裁决的
  label-only 覆盖、推理 feature 字节一致门及受影响 Segment gate 重算。
  `SUCCESS_UNIQUE` 必须原样命中一个完整冻结候选，其他三类不得填写候选；
  所有裁决必须有证据说明。任一 required anchor 已明确
  `AMBIGUOUS/CANDIDATE_MISSING` 时，该 Segment 立即局部 fallback，不等待
  其他 anchor 也有监督。定向 `14 passed`，完整 P05 `643 passed, 1 warning`。
- [ ] T035-R2 在普通 Segment 完整可执行方案稳定后，继续验证
  AdvanceRight `RCSD_ONLY` 与 `MIXED_SPLICE`；不得把 v240 的
  `SWSD_ONLY` PASS 外推到这两个方案。
- [x] T035-R3 建立 recall-first 同一 forward：冻结 T01 骨架，以 required
  anchor + 两侧普通 Segment + AdvanceRight 为有界依赖子图，先输出锚定、
  普通完整 Road 方案，再条件化输出提右完整 Road 集合。v386r1 外层
  fold1 对 143/143 对象强制输出；106 个 Road 监督对象 top-1 exact=
  `0.811321`，Road beam-16 recall=`1.0`。研究输出不应用发布置信门，
  正向 `KEEP_SWSD` 与 fallback 仍分开。
- [x] T035-R4 建立不读取终态选择的几何候选并接入同一 forward。v387r2
  只使用 50D 提右局部证据、普通方案成员和原始 side Road candidates，
  生成 269,875 个 103D proposal；218/218 个需要打断/挂接/衔接的监督对象
  完整可达，最大单对象 5,188，GPKG/JSON 每次运行只读一次。v388r1
  fold1 几何 top-1 complete exact=`30/67=0.447761`；v389 固定同一权重、
  Road/几何 beam 均为 16 时，联合监督 77/77 可召回，强制研究输出
  143/143。
- [x] T035-R5 验证平面 structured combination decoder。v390r3 仅允许
  `SWSD 无新增动作`、`两侧 RCSD 挂接`、`source RCSD + 中间衔接`、
  `target RCSD + 中间衔接` 四类组合，不允许通用 HYBRID、扩候选、改锚定
  或重判证据；但最多 81,920 个组合上的稀疏 softmax 使 fold1 top-1 从
  `33/77=0.428571` 降至 `32/77=0.415584`，decoder top-16 recall 也降至
  `63/77=0.818182`，判定组合平面排序 `NO_GO`，不作为下一版基线。
- [ ] T035-R6 以 v388r1/v389 为 recall-first 基线，分别收敛完整 Road
  cardinality/成员排序和分类型几何 proposal top-1；不得再扩候选或以更大
  评估 beam 抬高指标。稳定后补五折 OOF、完整 Node/方向/拓扑写出和最终
  RoadGraph exact，再进入安全发布门。
- [x] T035-R7 完成真正共享训练的 Fold1 单 seed 里程碑 M1/M2。M1 在同一
  forward 中联合训练 anchor、ordinary 完整 Road/access 和条件化
  AdvanceRight，锚定 status accuracy 从 `0.849255` 提升到 `0.901840`，
  但 reachable Road-set exact 从 `0.097378` 降到 `0.086142`、both-side
  exact 从 `0.018868` 降到 `0.009434`。M2 增加业务阶段 stop-gradient，
  Road-set exact 仍为 `0.086142`、10+ Road exact 仍为 0。因此停止直接
  多任务 loss 相加和同表示梯度隔离调参；下一轮必须更换为业务合法完整
  Road 方案的 listwise/结构化 decoder，不能继续优化 member/cardinality
  top-k。两项均 `NO_GO`，不扩五折/三 seed。
- [x] T032-R10 完成 v309 修正锚定监督 OOF 和 v313 Case-joint
  anchor/carrier forward。锚定 candidate/status/gate 分别达到
  `0.846594/0.926750/0.949467`，v313 free-plan exact=`0.880851`；
  但严格安全覆盖仅 `2.32%` 且 USE 自动接受为 0，仍为 NO_GO。
- [x] T032-R11 完成 v315–v319 posthoc 风险路线审计。单 MLP、双通道、
  二维阈值、显式 decision logits 和 Case 内 percentile 均不能把 inner
  零危险阈值迁移到 outer；停止继续做纯后置概率校准。
- [x] T032-R12 实现独立 plan validity 与独立 decision validity head，
  使排序、business decision、plan acceptable 和 decision acceptable
  物理分头。v325 四 inner fold plan exact=`0.888235`、outer exact=
  `0.880851`，outer KEEP/USE 零错误安全前缀为 `61.69%/40.74%`；
  但 fold0/fold1 USE 最高分仍含错误，严格跨折仍为 NO_GO。
- [ ] T032-R13 人工核查
  `T10:1885118 / 1881754_1898462`、
  `T10:605415675 / 500861744_600275542` 和
  `T10-Error-2:986209_996008_1 / 986209_996008_1` 的完整 Road 清单；
  只允许补充“可接受完整方案/优先方案”或确认现真值，不得根据模型预测
  反改标签。核查后保持 Case-disjoint split 重训，目标仍是每 fold 零危险且
  overall/USE 自动覆盖均至少 50%。
- [x] T032-R14 按用户确认把
  `T10:605415675 / SWSD semantic Junction 1633165` 固化为唯一
  road-only split 锚定：六条指定 RCSD Road 为完整真值，附近 RCSD Node
  `5391330021350570` 不可接受。v348r2 将共享 object embedding、原子
  Node/Road、arm 摘要和原始拓扑边固化为独立结构 decoder；v349r1 增加
  ordinal cardinality；v350r1 增加只降级 cardinality consistency gate。
  正式 gate 对 v340 的 22 个自动候选接受 21 个，21/21 正确、危险 0，
  唯一拒绝项即 1633165；该项只表示安全门禁集成 GO，Target A 整体仍
  NO_GO。结构 decoder、共享 encoder adapter、多解 loss 与门禁合同定向
  回归 `73 passed`，完整 P05 回归 `697 passed, 1 warning`。
- [x] T032-R15 将结构锚定 loss 接入 v327 Case-joint forward，并保持
  relation/member 标签在推理 batch 之外。v351r5 共 24,926,558 参数，
  ordinary free-plan exact=`0.868644`、结构 member exact=`0.779821`；
  但 relation/type exact 退化为 `0.727901/0.893274`，1633165 再次错选
  单个附近 Node，形成 `1/20` 危险自动结果，判定 NO_GO。训练集中已有
  426 条 `B + ROAD + 多 Road`、27 条 `B + ROAD + 6 Road`，因此失败不是
  同类监督缺失，而是只消费共享 embedding 时原始锚定结构证据被压缩。
  padding 组、零权重 inactive task 和训练/评估结构证据 I/O 合同已修正；
  完整 P05 回归 `700 passed, 1 warning`。
- [x] T032-R16 保留原始推理期锚定证据分支，并将其输出作为
  immutable anchor proposal 条件化下游 ordinary/RoadGraph decoder。
  v352 将 teacher 压缩到 324,108 参数，并在 held-out 1633165 上首次得到
  `B + ROAD + cardinality 6 + 六 Road exact`。v353r3 冻结 teacher、v327
  anchor/base encoder 和 ordinary heads，仅训练 25,696 参数的条件化 stem；
  总参数 24,929,538，free/all-plan exact=`0.881356/0.917355`，高于 v327，
  anchor exact=`0.801444` 且 inconsistency=0。v354 迁移旧 inner 阈值后，
  叠加 v350 正式锚定门接受 24 条且 24/24 正确，比 v350 增加 3 条；仍全部
  KEEP。冻结条件桥已固化为独立 P05 组件，完整回归
  `703 passed, 1 warning`。
- [ ] T032-R17 为冻结条件化模型补齐严格 nested inner checkpoint 与
  release threshold 校准，再重算 fold2 overall/USE 安全覆盖。v354 的
  outer-truth 零危险上限为 34 条，其中 USE 4 条，但只能作为可达性诊断，
  不得用作发布阈值；fold2 通过后再扩五折 OOF 和完整 RoadGraph gate。

## 2026-07-30 v256–v265 Case-joint canary 与锚定监督队列

- v256 证明城市/完整 Case 传递闭包不适合作为 forward 单位：最大连通组
  达 3,117 个对象；改为“一个普通 Segment + required anchors + 一跳直接
  锚定依赖”的有界业务子图后，4,196 个子图 P95/max 对象数为 `14/47`，
  数据 store 各只读一次。
- v257r3 首次让 ordinary carrier loss 经共享 encoder 回传到同一 forward
  的具体锚定候选证据；锚定输出不接收 ordinary→anchor 消息，
  prediction inconsistency=`0`。outer concrete anchor exact=
  `210/277=0.758123`，全部普通 Segment plan exact=`533/603=0.883914`
  （该指标后补入正式实现），但安全自动覆盖仅 `23/603=0.038143`，
  且有 1 个真值未知的 Review 自动项，判定 `NO_GO`。
- v258r1 直接把 anchor-plan compatibility 加入方案 logit，plan exact
  降至 `0.830846`；v259 只作辅助 loss，plan exact 仍降至 `0.815920`。
  两条 compatibility 路线均停止。
- v260r1 修正了业务门禁：已证明 `NO_EVIDENCE` 可作为正向
  `KEEP_SWSD` 的锚定例外，`USE_RCSD` 仍要求全部 required anchors 唯一
  成功。outer 真值就绪从 `212/603` 提升到 `235/603`，全部 plan exact=
  `522/603=0.865672`；但仅按 status 概率校准的无证据证明在 outer 放过
  1 个已知应成功锚定对象，unsafe automatic=`1`，不得使用。
- v262 复用同一 checkpoint，把 `NO_EVIDENCE` 证明改为
  `min(status NO_EVIDENCE 概率, 1 - unique-anchor gate 成功概率)`，
  inner-only 校准后 unsafe/review 均为 0；但自动正确仅
  `5/603=0.008292`，concrete anchor exact=`207/277=0.747292`，
  仍远低于 50% 研究 GO 和 80% 正式目标。
- v263 从 outer 500 个唯一锚定对象中识别 198 个缺少 status 或 concrete
  candidate 真值的对象，影响 356 个普通 Segment；其中 56 个已进入模型
  release 候选，但因真值未知必须阻断。Phase 1 选择 30 个锚定对象，覆盖
  91 个受影响 Segment。
- v264 生成只读 EPSG:3857 可视审计包：30 个 SWSD 语义路口、91 个冻结
  T01 Segment、187 个 RCSD candidate Node、338 个 RCSD candidate Road；
  不改几何、不改拓扑、无 silent fix。
- v265 对全量 198 条队列执行同一语义路口、同一推理输入、同一候选集合和
  同一局部结构证据的严格已有真值复用审计；T03/T04/T11 跨样本可复用数为
  0。T11 已证明 `T10:605415675 / 12833355` 的正确对象
  `ROAD:5384391266669010` 不在冻结候选集，按 `CANDIDATE_MISSING`
  局部 fallback，剩余全量 197 条；Phase 1 30 条不变。

## 2026-08-01：M54–M65 普通 Segment 真实 free-run 纠正

- [x] T032-R18 以 M54 required-anchor set gate 和 M59 三 seed listwise
  ensemble 重建普通 Segment 的真实 free-run 来源与完整 Road 集合。
  M59 同一输出同时给出 `KEEP_SWSD/USE_RCSD` 与完整 Road 清单；M46/M49
  因继承 M24 已给定 `effective_decision`，降级为来源已知的条件化组件证据，
  禁止再把其 `53%` 表述为端到端覆盖。
- [x] T032-R19 让 M59 实际选中的 RCSD Road 触发 M60/M61 BREAK 推理任务；
  真值成员只作训练标签和事后评价，不再决定 Fold1 推理对象。BREAK 使用
  strict Fold2 冻结的 balanced 阈值 `0.95`，避免 recall 阈值 `0.001`
  对 NO_BREAK Road 产生大规模误打断。
- [x] T032-R20 以 M63/M64 分别对 M59 Road 输出业务角色和 access 集合。
  M63 的 selected Road 候选缺失为 0；M64 只对 128 个有完整 access 监督的
  普通 Segment 做正确性评价，其余对象保持 Review，不补造真值。
- [x] T043-R2 以 M65 将 M54/M59/M61/M63/M64 写为真实 ordinary
  RoadGraph GPKG。高召回/稳定工作点分别自动物化 `492/415` 个 Segment；
  两者 `skeleton_mutation=0`、`silent_fix=false`、`content_repair=false`。
  同源 Road 所有权重叠只回退对应冲突 Segment，未扩成 Case fallback。
- [ ] T032-R21 收敛真实 free-run 的来源/完整 Road 集合与 access 错误。
  当前 M67 高召回/稳定物化结果仍分别有 `67/28` 个已知错误，且因
  access/角色监督不完整分别有 `479/412` 个 Review 自动项；正式结论继续
  `NO_GO`。
- [x] T032-R22 以 inner Fold2 选择 M66 `USE_RCSD` 行权重 `1.25`；Fold1
  complete Road exact 从 `0.726087` 提升至 `0.731522`，USE exact 从
  `0.558140` 提升至 `0.572939`。
- [x] T043-R3 以 M67 将 M66 重新贯穿 BREAK/角色/access/物化。STABLE
  自动物化保持 415，已知错误从 31 降至 28；RECALL 自动物化从 492 降至
  484、已知错误从 71 降至 67。两套 GPKG 无骨架变更、silent fix 或内容修补。
- [x] T032-R23 验证 source/cardinality group NLL：M68 inner 改善但 Fold1
  complete Road exact=`0.729348`，低于 M66，停止该 loss 路线。
- [x] T032-R24 建立 member-aware proposal graph encoder，让普通 Segment
  decoder 直接观察所选 Road 及其 pair relation。M69 Fold1 Road exact 提升到
  `0.739130`，但 source/USE 退化，M70 物化后已知错误高于 M67；M71 fused
  和 M72 residual 也未通过完整业务晋升条件。结构路线保留为已验证组件，
  不替换 M66/M78 基线。
- [x] T040-R5 同步 `_lock_anchor` 三返回值测试契约并执行完整 P05 回归：
  `754 passed, 1 warning`；唯一 warning 为 PyTorch Transformer 性能提示。
- [ ] T035-R8 普通 Segment 达到安全门后再恢复 AdvanceRight
  `RCSD_ONLY/MIXED_SPLICE` 训练；当前继续冻结提右优先级。
- [x] T032-R25 以 M73 补齐 M66 五折 OOF free-run carrier，并以 M74 在 OOF
  anchor/carrier 条件下重训 access。M74 对完整监督 Fold1 access exact=
  `30/128`、carrier compatibility=`1.0`；M75 cardinality 与 M77 Road-group
  decoder 的 Road+access exact 分别仅 `15/128`、`14/128`，均不晋升。
- [x] T032-R26 以不含真值/终态字段的 15D access feasibility evidence 训练
  M78 complete-plan scorer；Fold1 complete Road exact=`687/920=0.746739`，
  相对 M66 增加 14。M79 全链路 RECALL/STABLE complete plan exact 分别
  `476/423`，确定性图保持 skeleton、silent-fix 和 content-repair 三项安全
  合同。M78+M74+M79 晋升为当前普通 Segment recall-first 研究基线，仍为
  `NO_GO`，不得接生产。
- [x] T032-R27 以 Fold2-only `alpha=0.75` 验证 M66/M78 blend。M80 Fold1
  Road exact 仅多 1 个；M81 RECALL Road/错误均退化，STABLE 覆盖增加但错误
  也增加，故不晋升。
- [ ] T032-R28 以 M79 为基线继续收敛普通 Segment：优先修正锚定、source/
  完整 Road bundle 与 access 联合错误；验收同时报告 recall-first 与 stable，
  严禁用 fallback 后安全结果掩盖自动业务错误。
- [x] T040-R6 执行 M69/M72/M77 新结构定向回归 `9 passed`，并重跑完整 P05：
  `763 passed, 1 warning`；唯一 warning 为既有 PyTorch Transformer 性能提示。
- [x] T032-R29 以 M85/M86 重建独立锚定候选对象 selector。M86 严格五折 OOF
  acceptable exact 从 `2690/3318` 提升到 `2816/3318`，五个 fold 均提升；
  只替换既有候选中的唯一对象，不改变锚定 status、候选集合或下游 Road。
- [x] T032-R30 验证 M87–M90 Segment anchor-set gate。高召回工作点仍包含错误
  和未知项，安全工作点在 validation 仍非零错误；M86 selector 保留，M87–M90
  仅为研究证据，不晋升为 release gate。
- [x] T032-R31 以 M91 为 5,821 个普通 Segment 补齐严格五折 OOF 高召回 gate，
  并以 M92/M93 重新生成受 M86 锚定对象与 M91 gate 条件化的 Road encoder、
  proposal cache 和完整 Road 方案。旧 M5/M79 锚定 cache 不再作为该链路输入。
- [x] T032-R32 修正 access-evidence promotion gate 的比较范围，只允许与同一
  M91/M92 锚定链路的 M93 基线比较。M96 Fold1 Road exact=`675/920`、
  anchor+Road exact=`528/920`、USE exact=`0.608879`、10+ Road=`8/30`；
  KEEP 退化到 `0.865772`，仍需分支平衡。
- [x] T043-R4 将读取旧 M54 gate 的 M97 降级为兼容诊断；M98 改用 M91 Fold1
  OOF gate 后重新组合 M96 Road 与冻结的 BREAK/role/access heads。RECALL/STABLE
  自动物化为 `474/430`，Road exact 均为 `508/920`，plan+access 仍仅 `14/128`；
  两套图均无 skeleton mutation、silent fix 或 content repair。
- [ ] T032-R33 为 M96 普通 Segment Road 链路补齐严格五折 OOF，再重训同一
  free-run carrier 条件下的 access、BREAK 与 validity。优先收敛锚定错误、
  KEEP/USE 分支平衡和 Road+access 联合正确；AdvanceRight/Movement 继续后置。
- [x] T032-R34 以 M99–M126 重建普通 Segment 完整 Road 候选池和严格五折
  OOF。M126 complete Road exact=`2414/3156=0.764892`、source exact=
  `0.899240`、10+ Road=`52/142`，候选 Oracle=`3009/3156=0.953422`；
  五折总体保留 M126，Fold1 当前链路因 M120=`680/920` 高于 M126 的 672，
  继续使用 M120。
- [x] T043-R5 以 M129/M130 组合 M89 零已知错误锚定门、完整 Road 有效性门
  与 BREAK/角色方案，并由 M131 完整物化 182 个 Fold1 普通 Segment：
  `KEEP_SWSD=164`、`USE_RCSD=18`、fallback=738，骨架修改、silent fix 和
  content repair 均为 0。
- [x] T043-R6 以 M132 修正 M131 的完整监督口径。正向 KEEP 的 access/Node/
  方向采用冻结 T01 realization；当前 locked-`NODE:` USE 路径由 exact 锚定、
  Road、BREAK 和 hard topology 唯一确定 Node 写出。182 条均记为
  `derived_business_exact`；`ROAD:`/复合锚定或额外 access 未决路径继续 Review。
- [x] T032-R35 验证 M133/M134 分来源门和 KEEP expert。Fold1 分别扩大到
  198/205 时仍含 2/6 个错误，均不晋升；不得用降低安全标准换取覆盖。
- [x] T032-R36 验证 M135 source auxiliary、M136 top-12 缓存和 M137 二级
  reranker。M135 Fold1=`677/920`，低于 M120；M137 五折仅比 M126 多 1 条，
  同时 source 少对 13、10+ Road 少对 1，工程结论为不晋升。下一轮停止扫描
  同类发布阈值和 reranker，优先重建共享 encoder 的 source/完整 Road/锚定/
  有向拓扑联合证据；AdvanceRight 继续后置。
- [x] T032-R37 以 M138–M145 建立锚定硬门禁与完整 Road 同 forward 的普通
  Segment 联合基线。M144 严格五折强制输出=`3119/3125=0.998080`、anchor
  exact=`2388/3123=0.764649`、gated Road exact=`2370/3125=0.758400`、
  anchor+Road joint exact=`1910/3123=0.611591`；M142/M143 局部 Road expert
  与 M145 独立锚定预训练均未晋升。该结果只作为高召回研究基线，安全结论
  继续 `NO_GO`。
- [x] T032-R38 按修正方案 A 验证普通 Segment 共享业务依赖子图 encoder。
  同一图内编码 focal Segment、required anchors、候选 RCSD Road、共享
  Junction/Node、access 与所有权冲突；锚定先独立唯一输出并锁定，完整 Road
  decoder 只能在锁定结果下选择方案。T03/T04 强标签进入共享多任务 loss，
  AdvanceRight/Movement 继续后置。M148 五折 joint exact=`1924/3123`，但
  gated Road 和强制输出均低于 M144；M149 显式 Road 成员图 Fold1=
  `668/920`，低于 M69 的 `680/920`，因此均不晋升。
- [x] T032-R39 将普通 Segment decoder 改为 source-first 条件化结构：锁定
  锚定后先独立输出正向 KEEP/USE；KEEP 直接输出完整冻结 SWSD 方案，只有
  USE 分支解码 RCSD Road 成员、角色、所有权与 access。source 不得由 Road
  成员分数事后改写，ABSTAIN 与正向 KEEP 继续分开；先做 Fold1 canary，超过
  M69/M120 且 KEEP、USE、source、10+ Road 均不退化后才进入严格五折。
  M150–M153 的双向梯度隔离均通过，但最好结果 M151=`676/920`，未超过
  M69/M120；M153 Fold1 事后阈值上限也只有 `670/920`，不进入五折。
- [x] T032-R40 只重建 source 锁定后的 USE 完整 Road decoder。以 M126 top-12
  内的真值方案和近邻错误方案形成 hard-negative bundle/member loss，显式比较
  缺 Road、多 Road、错误连接 Road 与 10+ Road cardinality；KEEP 直接输出
  唯一完整冻结 SWSD 方案，不参与 plan 排序。先报告真值 source 条件 exact，
  超过 M126 的 `298/473=0.630021` 且 10+ Road 不退化后，再接回独立 source
  与锚定硬门禁做 Fold1 canary。M154 member/cardinality hard-negative 为
  `293/473`，M155 relation bundle 为 `296/473`，均未晋升。M156 将锁定 USE
  后的既有合法候选从 top-12 保留到 top-32，Fold1 Oracle 从
  `396/473=0.837209` 提升到 `415/473=0.877378`；但 M157 有界残差和 M158
  直接 listwise 分别只有 `294/473`、`293/473`，10+ Road 均为 `9/30`。
  M157 的最大相对改分约 `0.47`，而新增 19 个正确方案的最小 M126 分差为
  `1.78`，所以 M157 无法检验新增候选；解除该限制的 M158 仍未得到新增
  top-1，证明简单放宽候选并继续同类 reranker 不能收敛。
- [x] T032-R41 对 source-locked USE 的错误方案做可辨识性审计，按缺 Road、
  多 Road、错误连接 Road、内部连接 Road、access/方向/拓扑不完整和 10+ Road
  分层比较正确方案与 top-1 错误方案在推理期 Road/关系证据上的差异。只有在
  明确现有证据可区分后，才重建 Road-level 监督与完整集合 decoder；停止继续
  扫描同类 reranker、epoch、阈值或候选宽度。M182 中 465 条 source 已正确的
  USE Road-set 错误，top-12/top-32 分别已有正确集合 272/330 条；错误分为多选
  217、少选 90、等基数错成员 102、同时多选少选 56。272 对可达的正确/错误
  694D 方案没有 exact/near feature collision，但中位 cosine=`0.953209`，只能
  证明缓存特征不同，不能证明跨 Case 可学习。更重要的是 M126/M182 的 positive
  只定义 source+Road set，不含 role/ownership/access/方向/打断/Node/最终拓扑，
  因此后五类不能在该链路完成正确性审计。结论是结束局部 scorer 迭代，转为
  完整业务 ledger 的统一监督与评价。AdvanceRight/Movement 继续后置。
- [x] T032-R42 收敛到一条普通 Segment 联合主线，不再增加独立局部模型。复用
  `TargetAJointNetwork` 的锚定硬前置与共享业务依赖子图，在同一次 forward 中
  输出锚定、正向 KEEP/USE/ABSTAIN、完整 Road 成员、Road 角色与 ownership、
  source/target access、方向以及可监督的打断/Node 关键状态。现有 T03/T04 强
  标签、T10 分级弱标签和 role/access/break 的部分标签用独立 task mask 与样本
  权重进入同一 loss；未标注字段不得补造为负例。第一版 AdvanceRight/Movement
  不进 loss。严格 OOF 同时报告高召回 free-run、完整字段可评价子集 exact、
  source+Road-set 兼容指标和各监督字段覆盖，先建立可出结果的主线，再进入安全
  接受校准；M182 只作对照，不得作为新模型的推理输入。
- [x] T032-R42a 完成普通 Segment 单 forward Fold1 canary。统一读取 4,236 条
  普通 Segment，模型内先输出并锁定锚定，再联合输出正向 KEEP/USE、完整 Road
  membership/cardinality、Road role/ownership、carrier 条件化 access collection
  与 parent Road break；AdvanceRight loss=0、Movement 关闭。29,977,724 参数模型
  训练 4 epoch（2 teacher + 2 free-run），Fold1 `anchor+Road exact` 从
  `347/597=0.581240` 提升到 `385/597=0.644891`，Road exact 从
  `520/668=0.778443` 提升到 `538/668=0.805389`，access 从 `7/84` 提升到
  `61/84`，break 从 `0/233` 提升到 `227/233`。strict full 仍为 `0/24`，
  且 24 条全部来自 `T10:609214532`；因此该 canary 只证明联合表示可学，不代表
  完整 RoadGraph 已收敛或可安全发布。
- [x] T032-R42b 补齐候选约束的结构化 ordinary decoder：锚定结果继续是不可反向
  修改的硬前置；decoder 只能在模型给出的既有合法 PlanCandidate 中联合选择
  Road 清单、role/ownership、access、方向和 break/Node recipe，不得扩充候选、
  读取终态或事后修图。完成后以固定协议做严格五折 OOF；只有完整字段可评价子集、
  `anchor+Road`、10+ Road 和 free-run 方案覆盖共同改善，才进入安全接受/fallback
  校准。不得先针对 Fold1 的 break 或 10+ Road 小分母做局部调参。R42b 已完成
  结构化候选 Oracle 和单 seed 五折，但后续审计发现普通 Segment 的空 padding side
  被错误写入 group 0 并参与 effective decision 平均；R42b 数值降级为错误数据流
  诊断，不作为正式研究基线。
- [x] T032-R42c 修正普通 Segment 单侧 forward 的 group identity：正式 focal side
  固定映射 group 0，空 padding side 固定为 `-1`，不得参与锚定后 source/plan
  聚合。新增回归验证 padding 不加入 focal group；同 checkpoint 五折重评取得
  plan exact=`1942/4236`、strict=`25/103`，证明修复改变了有效门禁，旧 checkpoint
  已适应错误输入，不能直接晋升。
- [x] T032-R42d 在正确 padding/group 数据流上从各 fold 原始锚定 checkpoint
  独立重训单 seed 五折。结构化 plan exact=`1960/4236=0.462701`、10+ Road=
  `14/22=0.636364`、strict full=`28/103=0.271845`；锚定真值已知的 2,017 条中，
  anchor exact=`1585/2017=0.785821`，anchor+完整 plan joint exact=
  `1255/2017=0.622211`，锚定正确条件下 plan exact=`1255/1585=0.791798`。
  这里的 2,017 实际是“所有 required anchor 的唯一对象真值完整”范围；R43
  重新审计后确认另有 400 条具备完整 `NO_EVIDENCE/明确失败` 状态真值但不应有
  RCSD 锚定对象，真正业务状态可评价分母为 2,417，剩余 1,819 才是 Review。
  P05 全量回归 `778 passed, 1 warning`。该轮仍为 `NO_GO`，未训练发布门。
- [x] T032-R43 以 R42d 为唯一普通 Segment 联合基线，停止继续修单一 Road scorer。
  下一轮只处理跨折共同瓶颈：共享 encoder 的锚定对象泛化、锁定锚定后的完整
  PlanCandidate 选择、完整 access collection。晋级同时要求锚定真值已知范围的
  anchor、anchor+plan joint、strict full、各 fold 最差表现共同提升；锚定真值未知
  范围继续记为 Review，不得用弱 KEEP 标签补造锚定成功，也不得提前训练安全发布门。
  全局归因得到业务状态可评价 `2417`、anchor exact=`1805/2417=0.746794`，
  错误同时覆盖 status、对象类型、对象 cardinality 和 identity；cardinality 硬锁
  Fold1 使成功锚定从 `484/604` 降到 `468/604`，明确淘汰。梯度隔离 canary
  虽把 Fold1 成功锚定增至 `489/604`，却使正向 NO_EVIDENCE 减少 11 条且没有
  降低危险 fallback，未进入五折。teacher-student 边界能保留锚定并改善完整 plan，
  但只新增 4 条成功 joint，同样不能替代 outcome safety。
- [x] T032-R44 使用相同 R42d 五折 checkpoint 建立真实高召回端到端基线，不重训、
  不扫描阈值，仅把已确认的正向 `NO_EVIDENCE` 业务门从禁用值 `1.0` 恢复为固定
  `0.5`。结构化 plan exact=`3406/4236=0.804060`，但正向业务联合 exact 仅
  `1447/2316=0.624784`，strict 仍为 `28/103`；明确 fallback 中危险自动输出
  `68/101`，锚定真值未知 Review 中自动输出 `1608/1819`。该轮只证明联合模型
  已能高召回生成完整方案，正式结论仍为 `HIGH_RECALL_NO_GO`。
- [ ] T032-R45 训练锚定 outcome safety 与 unknown Review gate。必须在同一模型内
  保持锚定先行，区分 `SUCCESS`、正向 `NO_EVIDENCE -> KEEP_SWSD`、明确
  `ABSTAIN -> Segment fallback` 和真值未知 Review；Road/Plan decoder 不得反向
  修改锚定。第一目标是降低 68 条明确 fallback 危险自动输出，同时不牺牲 R44
  的成功对象锚定与正向 NO_EVIDENCE；通过后才训练普通 Segment 安全发布门。
- [x] T032-R45a 将 R44 的 unknown Review 转成最小跨 Case 人工裁决输入。旧 v269
  Phase 1 虽保持 30/30 candidate IDs 和输入文件哈希一致，但当前 v339 结构特征
  30/30 已变化，且 4 条 status 后续已有监督，因此不得继续填写旧 CSV。新批固定
  6 个正式 T10 Case、每 Case 4 个 anchor，共 24 个；按 R44 `SUCCESS /`
  `NO_EVIDENCE / ABSTAIN` 预测分层抽样，影响 94 个未知真值 Segment，其中 69 个
  当前为自动非 ABSTAIN。模型预测只用于优先级，不进入人工真值。6 个只读
  EPSG:3857 GeoPackage 均保持原始几何、无 silent fix；空白 CSV 已通过既有严格
  回填合同，定向测试 `9 passed`。R45 仍须等待裁决回填后训练，不因准备包完成而
  标记完成。
- [x] T032-R45b 实现同一 forward 内、位于锚定与 ordinary carrier 之间的可选
  outcome/Review 头，并做固定 Fold1 canary。该头只读取锚定 embedding、状态、
  candidate、gate、类型和 cardinality 的推理期证据；未知真值严格 mask；与原
  status 不一致或低置信时只能降级 Review/ABSTAIN，不能改锚定对象或恢复 Road
  carrier。固定 `0.5` 阈值、24 epoch、不扫描：危险 fallback `21 -> 20`，未知
  Review 自动输出 `445 -> 402`，SUCCESS joint 保持 `380`，但正向 NO_EVIDENCE
  joint `47 -> 38`，判 `CANARY_NO_GO`，不扩五折。可选头默认关闭，完整 P05 回归
  `783 passed, 1 warning`；R45 仍等待 R45a 的 24 条裁决后再训练。
- [x] T032-R45c 固化 Fold1 同-checkpoint 的锚定推理证据缓存。一次性读取城市级
  store 并前向 4,236 个普通 Segment，保存 28,496 个 occurrence、4,335 个唯一
  anchor 的 368D 推理期特征；缓存不含标签、status 真值或终态输入，人工标签须按
  identity 从最新 overlay 连接。重载 feature/identity 校验通过；后续只有 checkpoint
  或 anchor manifest 哈希变化时才允许重新读取城市 store 和重算基础证据。
- [x] T032-R45d 准备固定的人工 overlay + 缓存训练 Fold1 链路。正式运行前强制
  24/24 CSV 完整、label-only overlay 不改变 inference feature、cache/checkpoint/
  anchor manifest 哈希一致；训练和目标折按 Case fold 切分，并在同一人工真值下
  重算 R44 Fold1 对照，不允许通过标签分母变化制造提升。只读 preflight 已通过全部
  缓存门禁，确认当前 `0/24`，`writes_performed=false`；不使用伪造裁决试跑训练。
- [x] T032-R45e 为 24 条裁决生成只读静态审计索引，降低人工打开、筛选和定位
  6 个城市级 GeoPackage 的成本。24/24 anchor、6/6 Case、1,177 条 candidate plan
  ID 和 96 条 Segment 引用均进入索引；抽查高候选、无候选和普通候选三类视图。
  橙色模型选择显式标为 context only；该工件不生成业务决定、不写标签、不改变
  几何和拓扑，也不进入训练输入。
- [x] T032-R45f 消费用户完成的 24 条人工锚定裁决，生成 label-only overlay，
  其中 6 条为 `SUCCESS_UNIQUE`、18 条为 `PROVEN_NO_EVIDENCE`；推理 feature store
  字节不变。固定 Fold1 outcome head canary 将未知 Review 自动输出从 437 降至
  390、危险 fallback 从 21 降至 20，但正确正向 `NO_EVIDENCE` 减少 9 条，
  structured plan exact 从 `0.803143` 降至 `0.755170`，正式结论为
  `CANARY_NO_GO`，结束局部 outcome head 路线。
- [x] T032-ARCH-CLOSURE-P0 按独立任务合同验证“Junction 唯一锚定 + 普通
  Segment 条件化完整方案 + Junction 直接关联确定性协调”。建立不可变 Fold1
  baseline manifest、`JunctionStore/SegmentStore/PlanStore` 引用式管道、统一
  evaluator 和 16 项 Gate 0；Gate 0 全部通过。固定 seed=`20261650`、4 epoch
  canary 的 Segment Full Exact 仍为 `8/24`，Junction Group Exact 仍为
  `6/18`，structured plan exact 从 `971/1209` 降至 `959/1209`，正确
  `USE_RCSD` 从 139 降至 109；unsafe automatic 保持 21。结论为
  `ARCH_CANARY_NO_GO`，不进入五折，不允许继续 Fold1 局部 head、阈值、epoch、
  seed、cardinality 或 reranker 修补。引用式缓存和直接 Junction fallback 边界
  作为通过的基础设施保留；下一步必须在规则 fallback、独立 Gold、调整
  Junction/Segment 模型边界或结束当前结构之间重新选择。
- [x] T032-UNIQUE-JUNCTION-P1 用户在 ARCH-CLOSURE-P0 `NO_GO` 后选择调整
  Junction/Segment 模型边界：先以唯一 `case_key + semantic_junction_id` 为
  forward/监督单元重训 Layer A，再生成严格 Case-grouped OOF `JunctionStore`；
  只有 Layer A 固定 Fold1 canary 同时提升全监督与 Gold 的完整锚定业务 exact，且
  危险自动输出、unknown 自动输出、正向 `NO_EVIDENCE`、SUCCESS 完整对象 exact
  均不退化，才允许训练读取锁定 OOF 锚定的普通 Segment 完整 Plan。固定
  seed=`20261660`、8 epoch、LR=`2e-5`、weight decay=`2e-4`、gradient
  clip=`1.0`、gate threshold=`0.5`；禁止 epoch/threshold/seed 扫描、局部 head、
  reranker 和 Road/Plan 反向选锚定。AdvanceRight/Movement 继续关闭。
  固定 canary 已完成：完整锚定业务 exact 从 `908/1145=0.793013` 提升到
  `921/1145=0.804367`，但 Gold 从 `129/159=0.811321` 降至
  `127/159=0.798742`，SUCCESS 完整对象从 `791/961` 降至 `782/961`，正向
  `NO_EVIDENCE` 从 `32/47` 降至 `29/47`，危险自动输出 `12→13`、unknown
  自动输出 `165→169`。结论 `UNIQUE_JUNCTION_CANARY_NO_GO`；未启动五折、
  `JunctionStore` OOF 或 Layer B Segment Plan。主要监督失配是训练折 Gold
  完整对象仅 121 条、Silver 2,414 条，现有 1.0/0.7 权重下对象 loss 仍由
  Silver 主导；该事实只作下一次边界决策，不授权继续 Fold1 调参。
- [x] T032-UNIQUE-JUNCTION-GOLD-PHASE1 用户于 2026-08-04 明确授权在现有
  Case 内补充/复核完整 Node/Road anchor Gold。选样已在人工开始前冻结：只从
  6 个现有 T10 Case、权重 0.7 的 Silver SUCCESS 完整对象中，保留有冻结普通
  Segment 直接引用的 Junction，再按 Case、Node/Road 类型和 Road 集合大小以
  固定 SHA256 排序抽取 80 条；不读取模型预测、分数、错误或 release 结果。
  标注模板、6 个 Case QGIS 工程、总工程、4,674 条 candidate 组合索引和严格
  多解回填合同均已生成。人工返回后将 `manual_preferred_candidate_id` 的 27 个
  误加前缀 `|` 规范化并保留原文件备份；80/80 最终裁决为
  `SUCCESS_CONFIRMED=77 / CANDIDATE_MISSING=1 / AMBIGUOUS=1 /
  PROVEN_NO_EVIDENCE=1`。严格回填验证冻结字段、行哈希、candidate 可达、证据说明
  和既有 Gold 零覆盖；生成的 label-only overlay 保持
  `anchor_features.jsonl` SHA256
  `78a3f17c0d9bc47bdd516bfaf5544e7e96db8ec5eb3a9ee99b578e6b186376a6`
  逐字节不变。

  只执行一次固定 Fold1 Gold-first canary：保持 P1 的结构、seed=`20261660`、8
  epoch、LR、weight decay、clip 和 gate threshold 不变，不扫描任何参数；训练折
  原始 Gold/Silver 为 `688/3101`，以总 loss 质量 `0.5/0.5`、均值权重 1 的固定规则
  重加权。新批 64 条只进训练、16 条只进 Fold1 评价。完整锚定业务 exact
  `907/1145→919/1145`，但全 Gold `139/175→139/175`、SUCCESS 完整对象
  `789/959→785/959`、正向 NO_EVIDENCE `32/47→30/47`、危险自动输出
  `13→14`、unknown 自动输出 `165→170`。新留出 16 条自身从 `10/16→11/16`，
  其中对象 exact `10/14→11/14`，证明人工 SUCCESS 对象监督可学，但不能泛化为
  全 Gold 与安全改善。80 条仅 1 条 `PROVEN_NO_EVIDENCE` 且不在 Fold1 留出集，
  无法承担 NO_EVIDENCE 泛化证明；另 1 条人工 Road 组合不在冻结候选集，按
  `CANDIDATE_MISSING` 保留而未补造标签。结论仍为
  `UNIQUE_JUNCTION_CANARY_NO_GO`；不启动五折、OOF `JunctionStore` 或 Layer B，
  也不继续 Fold1 loss/epoch/阈值局部迭代。回填、overlay 与固定 canary 合入后的
  完整 P05 回归为 `796 passed, 1 warning`。
- [x] T032-JOINT-ARCH-CLOSURE-P1 在用户继续推进目标 A 的授权下，将唯一
  Junction 锚定和普通 Segment 完整 Plan 放进同一动态业务依赖子图 forward，
  用同一 anchor encoder 的 live embedding 条件化 ordinary decoder；锚定仍先
  独立输出唯一结果，ordinary 不能扩候选、改骨架或反向选择锚定。连通组只包含
  Segment 与 required Junction 的直接依赖，不使用 fallback 传递闭包；前 2 个
  epoch teacher forcing、后 2 个 epoch 真实 free-run，固定 Fold1、
  seed=`20261670`、LR=`2e-5`，以 PCGrad 处理共享 anchor 参数的冲突梯度，未扫描
  epoch/threshold/seed/weight，也未启用 AdvanceRight 或 Movement。

  单次 canary 共 38,099,141 参数，训练/验证分别为 822/370 个直接依赖连通组、
  3,027/1,209 个普通 Segment、3,115/1,220 个唯一 Junction。普通 Segment 相对
  同次初始化的 Full Exact `6/24→9/24`、Junction Group Exact `5/18→6/18`、
  structured plan exact `909/1209→982/1209`，且 90 条方案修复、17 条退化；但
  unsafe automatic `22→25`、unknown automatic `381→433`。锚定业务 exact
  `801/1007→804/1007`，同时 Gold `23/42→22/42`、dangerous automatic
  `13→17`、unknown automatic `170→194`。新增 4 个危险锚定均为监督真值
  `ABSTAIN` 被错误释放，3 个随后直接形成新增危险普通 Segment；不是 decoder
  修改锚定或 fallback 跨 Junction 扩散。训练每轮 822 个连通组中有 238–255 个
  anchor/ordinary 共享梯度冲突，PCGrad 不能守住锚定安全门。结论为
  `JOINT_ARCH_CLOSURE_CANARY_NO_GO`，不扩五折，也不继续 Fold1 参数或局部 head
  搜索。保留动态直接依赖子图、live 条件化和候选约束 decoder；下一版必须在结构上
  隔离 ordinary loss 对锚定决策参数的写入，而不是用发布后处理掩盖锚定错误。
  新增联合数据流、网络和梯度边界测试合入后的完整 P05 回归为
  `799 passed, 1 warning`。
- [x] T037-JUNCTION-FIRST-T07-P0 用户确认将 T07 纳入模型替代范围，并将下一
  阶段优先级调整为 T07/T03/T04/T05 语义路口业务，普通 Segment、AdvanceRight、
  Movement 全部后置。先冻结路口专用 inference/label store：推理只读取 T01/SWSD、
  原始 DriveZone、原始 RCSDIntersection 和原始 RCSD Road/Node；T07 Step1 tensor
  必须物理排除 RCSDIntersection；T07/T03/T04/T05 的 nodes、surface、状态、
  relation、graph-consumability、junctionization 与人工裁决只作标签/评价。随后
  建立一个 SWSD 语义路口一个输出的分层模型，显式预测 T07 evidence/已有面锚定、
  T03/T04 路由与 surface/relation evidence、T05 唯一 relation/可图消费/
  junctionization 和完整 Node/Road anchor 集合。先完成标签覆盖与候选可达审计，
  再冻结一次 Case-group Fold canary；零危险路口门未通过前不得恢复 Segment 训练。

  修正后的 label audit 覆盖 5,148 个唯一 SWSD 语义路口、736 个 Case；其中 T10
  口径 4,459 个。T07 Step1 从 `nodes.gpkg.has_evd` 按 mainnodeid 归并读取后为
  `4459/4459`，`yes/no=3690/769`，冲突 0；Step2 只在 Step1 yes 范围监督，
  `3690/4459`，`yes/no/fail1/fail2=1759/1919/8/4`，冲突 0。T03、T04、T05
  relation 适用范围分别为 1,531、387、3,624；现有 inference store 未出现任何
  T03/T04/T05 终态字段，Step1 固定只取 64D object 中 11 个 SWSD/DriveZone
  维度，candidate、RCSDIntersection、RCSD Road/Node 通道物理缺席。审计状态为
  `JUNCTION_FIRST_LABEL_AUDIT_GO`。

  新增 15,517,518 参数的分层 Set Transformer：Step1 与 Step2 各自独立编码，
  下游 condition stop-gradient；T03/T04/T05 共享 raw object/candidate/member
  encoder，完整 anchor 同时输出 candidate bundle 和受对象类型、cardinality 约束
  的 Node/Road member set。固定 Fold1、seed=`20261671`、18 epoch、batch 32，
  前 1/3 teacher forcing、中段退火、后 1/3 free-run，不扫描 seed、epoch、weight、
  threshold 或局部 head。初跑误把单点 T03/T04 route 置为 `UNRESOLVED`，其
  `69.6836%` 联合 exact 只保留为标签缺陷诊断，不作为正式结果。

  修正单点 route 为 label-only `T03/T04` 后的正式 canary：T07 Step1/Step2
  accuracy=`0.965714/0.832845`，route=`0.937454`，T03 surface/relation=
  `0.933941/0.838269`，T04 surface/relation=`0.835294/0.717647`，T05
  junctionization/graph/relation=`0.880359/0.957129/0.971087`；完整 anchor
  exact=`879/1145=0.767686`，T07–T05 关键状态联合 exact=
  `872/1359=0.641648`。raw `SUCCESS` 中有 13 条状态型危险、202 条完整对象集
  错误和 32 条 Gold 不完整 Review，另有 41 条真实 SUCCESS 被漏召回。T03 单点
  成功完整锚定仅 `1/12`、T04 为 `0/7`，说明单点 replay 标签与城市完整前序观测
  不能继续直接混入同一 route/head 分布。结论为
  `JUNCTION_FIRST_CANARY_NO_GO`：不恢复 Segment/AdvanceRight/Movement，不做
  同结构调参；下一版只允许把单点监督放入独立 auxiliary/teacher adapter，并把
  主要容量用于完整 Node/Road 对象集，不得恢复旧 T07–T05 推理策略。
  新增数据合同、分层网络、stop-gradient、完整对象集 decoder 与 loss 单测后，
  完整 P05 回归为 `806 passed, 1 warning`。
- [x] T037-R1-JUNCTION-GOLD-DATASET-CLOSURE 按用户正式确认的数据口径重建路口
  Gold 与 split：扫描 `POC_Data/T03`、`T03_Error`、`T04`、`T04_Error` 和
  `POC_QA/T03_Error`，校验 manifest、CRS、声明 checksum 与必需原始图层；按 Case
  ID/输入 hash 去重，将冲突记录隔离为 `LABEL_REVIEW`。对可消费 Case 执行当前正式
  T07/T03/T04/T05 规则重放并形成 label-only Gold，权重 1.0；T10 只提取可明确
  追溯到具体 SWSD 语义路口的 0.7 锚定结果。标签审计后按实际无冲突 Case 分母冻结
  Gold train/validation/test 清单和 T10 Case-group 留出集，证明 feature/label/test
  三重隔离。

  2026-08-04 已完成其中 1.0 Gold 主集闭环：743 个来源记录全部通过 CRS/输入完整性
  与正式规则重放，surface accepted/rejected/runtime_failed=`399/321/23`；24 个
  多版本 Case 中 8 个终态一致、16 个终态冲突隔离。399 个 accepted surface 已完成
  T05 延续：343 个完整成功、19 个正向无 RCSD 证据、37 个仅 action/safety 可监督，
  几何改写与 silent fix 均为 0。冻结 700 个 Case group、708 个输入版本为
  train/validation/test group=`490/105/105`、输入版本=`497/105/106`，有效权重仍为
  `490/105/105`，
  train 覆盖全部现有终态组合，Case/input fingerprint leakage=`0/0`。T10 0.7
  直接路口监督和 feature/label 分离已在后续完整 `JunctionResult` 合同审计中闭环：
  开发集共 4,288 条，其中强 Gold 602、T10 弱标签 3,686；冻结测试保持隔离。
  训练标签、推理证据、候选枚举元数据和终态泄漏已分别登记，未知字段继续按 mask
  处理，不补造成负例或成功标签。
- [x] T037-R1A-COMPLETE-JUNCTION-RESULT-ORACLE 在不训练的前提下完成完整
  `JunctionResult` 合同、标签覆盖矩阵、候选与 Oracle 可表达性审计。虚拟面不再要求
  复现旧规则面或 exact 成员集合，而采用 `REQUIRED / FORBIDDEN / UNKNOWN` 三态：
  1,685 条适用记录中 1,680 条可监督，5 条冲突隔离为 Review；成功锚定记录
  REQUIRED 候选可达 `1,528/1,528=100%`。拓扑 Oracle 可表达
  `1,626/1,685=96.50%`，完整结果 Oracle 可表达
  `1,621/1,685=96.20%`。6 条 `NO_RCSD_EVIDENCE` 的 T04 must-cover Road 仅作
  构面参考并保持 UNKNOWN；76 条质量状态记录不补造成成员集合。结论为
  `CONSTRAINT_ORACLE_GO_WITH_REVIEW`，允许进入新网络结构任务书，但不等于模型精度、
  自动覆盖或安全发布已通过。
- [ ] T037-R2-JUNCTION-AUXILIARY-TEACHER 在不恢复旧策略推理输入的前提下，为单点
  Gold 和 T10 建立方案 A 的 mask-aware 联合训练链：权重 1.0 的强 Gold 与权重
  0.7 的 T10 弱监督允许共享 raw-inference encoder，未知字段保持 mask；来源只作
  cohort audit 与分层指标，不得进入网络输入。联合阶段后必须执行强 Gold
  consolidation，并同时报告两套 validation。先做固定 canary，完整路口 exact、
  对象集合、surface、拓扑、异常安全和最差类统一评价；不扫描同结构
  epoch/threshold/seed，不读取冻结 test。

  2026-08-05 用户明确选择方案 A，取代本任务在 P0 NO_GO 后暂定的“只能使用独立
  auxiliary/teacher adapter”限制。历史 P0 结论继续保留为当时实验事实，不再作为
  当前联合训练的禁止条款。v5/v6 的直接联合训练、v7 的强 Gold consolidation 和
  v10 的 break projection 结果可作为探索基线，但必须补齐来源审计、双 validation
  checkpoint 门禁后才能成为本任务的合规 canary。
- [ ] T037-R3-JUNCTION-FROZEN-TEST-GATE 固定模型方案后执行 Gold 冻结测试、T10
  留出测试、规则链 paired comparison、CRS/几何/拓扑/QGIS 与同输入输出性能审计。
  Gold raw完整路口 exact `>=0.85`、自动覆盖 `>=0.80`、自动接受正确率 `=1.0`、
  危险/未知自动接受 `=0/0`、异常或安全 ABSTAIN recall `=1.0`、T10 weighted exact
  `>=0.75` 才允许路口阶段 GO；否则 Segment/AdvanceRight/Movement 继续关闭。
