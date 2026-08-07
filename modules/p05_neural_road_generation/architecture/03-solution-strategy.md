# 03 方案策略

## 当前 Target A 策略

以城市数据的一次读取和标准化缓存为外层边界，按动态业务依赖子图执行共享 Graph/Set encoder；先由独立锚定 head 对每个 SWSD 语义路口给出唯一 RCSD 锚定对象和打断位置，不能确定即 `AMBIGUOUS/ABSTAIN`。普通 Segment decoder 始终保留正向 `KEEP_SWSD` 与 `ABSTAIN`；只有 required anchor 全部成功时才启用 `USE_RCSD` 和 T06 明确允许的“主干 RCSD、附属 SWSD”候选。当前 ordinary head 先显式输出 `KEEP_SWSD / USE_RCSD / ABSTAIN`，再在该状态内选择完整 Road 清单，状态内归一化不改变 carrier 必须输出完整 Road/Node 方案的合同。每个 KEEP/USE 候选以逐 Road 成员集合表达来源角色、端点、方向、局部拓扑、相对几何和 OOF 锚定关系；成员证据只参与已选业务状态内部的完整 Road bundle 排序，避免把 Road 数量或集合形态当成 KEEP/USE 的捷径。另以对称的两端 arm 关系表达 SWSD pair_node/Segment 端点到候选 Road 叶端点的距离、方向和 OOF 锚定匹配；两端用 mask-aware mean/max 编码，交换 pair_node 存储顺序不改变表示。arm 关系作为受控跨状态残差参与 KEEP/USE 与 bundle 选择，但不构成锚定成功硬规则。实现允许把 OOF 锚定关系细分为当前端 local 与另一端 foreign；v46 证明该证据会把边界推向 USE，却同时增加危险 `KEEP->USE`，所以只保留为诊断能力，正式结构基线仍采用不区分 local/foreign 的 v45。原始 Road/Node ID 只作关系 join 与结果 sidecar，不进入 embedding。普通 Segment 最终 access 锁定后，`ADVANCE_RIGHT` decoder 才生成完整提右 Road 组合、打断、衔接和挂接方案。Clue/scope head 判断无证据、歧义、现实冲突、影响对象并输出显式 `FallbackDirective`。结构化 decoder 只联合选择模型已给出的方案，所有权约束不具有扩大 fallback 的权力；Segment directive 止于自身，Junction directive 止于明确列出的直接关联 Segment，禁止沿 Segment 传播到另一端 Junction。确定性层只校验冻结 T01 直接关系、物化几何/Node、执行已确定 fallback 和通用合法性检查，不补造或重判业务事实。

当前锚定分支进一步使用原子 Node/Road set 与原始拓扑边：结构 decoder
同时保留当前 SWSD 语义路口的原始推理期 object evidence 和共享 encoder
context，联合解码 RCSD 证据角色、对象类型、数量与完整成员集合。v351
证明只消费共享 embedding 会提高 member exact、却使 relation/type 退化并
把 1633165 错判为附近 Node；因此原始锚定证据不得被共享 context 替代，
ordinary loss 也不得成为改变锚定语义 encoder 的唯一梯度来源。对象类型按
候选集中实际存在的 Node/Road 做 hard mask；训练期的 relation、
acceptable set、cardinality 和 member truth 不进入推理 batch。多解集合以
minimum acceptable-set loss 进入训练。发布时保留独立的 threshold
cardinality 与 expected-floor cardinality；二者不一致只触发 `ABSTAIN`，
后层不得拿其中任一结果重选或扩充成员。

下游条件化采用冻结桥：每个 required anchor 的原始 64D object evidence
与 relation/type/cardinality 六维模型摘要聚合为 70D 条件输入；结构锚定
teacher 在该 forward 中强制 `eval + no_grad`，carrier 梯度只能更新下游
条件化 adapter，不能进入锚定 proposal。v353r3 已证明该结构在总参数
24,929,538 下把 free-plan exact 提升到 `0.881356`，同时保持锚定输出不变。

旧 T07–T06 策略在目标 A 推理期完全退出；终态只作为分层监督和完整策略对照。T01 业务骨架冻结，T10 为编排；模型先完成并独立验收 T07/T03/T04/T05 路口业务，再启动 Segment。第一版不启用 Movement、不接生产，也不修改 T01–T12 正式实现或接口。下述 M0–P13 内容均为历史实验路线与可继承证据，不再定义当前网络边界。

## M0 流程

```text
POC_Data manifests
        |
        v
case inventory -----> anomalies
        |
        +---- explicit canonical baseline summaries
        |                    |
        v                    v
training samples <---- label artifacts
        |
        v
business-ID grouped split
        |
        v
T06 Road/Node evaluator -> Oracle + corruption tests
```

## 关键策略

1. 数据扫描与标签解析分离。Case inventory 不依赖 outputs；标签解析只消费显式 baseline roots。
2. 真值以 lineage 为准。baseline 成功不等于标签可信，必须同时证明 source Case 位于限定根且 handoff artifact 存在。
3. 任务级 masking。缺少某类可追溯 artifact 时只关闭该训练任务，不把整个 Case 静默删除。
4. 业务 ID 分组。不同归档版本、错误集与正常集中的同一对象保持同 fold。
5. 评估 identity-first。先比较 canonical ID 与语义字段，再对模型可能产生的新 ID 使用受门禁几何 fallback。
6. GIS 问题显式失败。CRS、字段、重复 ID、端点和拓扑异常不做自动修复。

## M1 流程

```text
frozen M0 run
      |
      +-- T01/T03/T04/T05/T07 input artifacts
      +-- T06 label-only truth
      v
candidate Road graph -> entity leakage guard
      |
      +-- deterministic / MLP baselines
      v
~10M RoadOperationGraphNet
      v
DROP/KEEP/SPLIT + attributes/endpoints
      v
no-business-rule materializer -> M0 evaluator
```

M1 采用原生 PyTorch 稀疏图聚合，避免稠密 attention 对万级 Road 图的二次复杂度。开发期只使用 train/validation 与开发集 group CV；模型和阈值冻结后才运行固定 test。模型无效输出直接计失败，不调用 T06 规则 fallback。

## M2R 流程

```text
frozen M0 + traceable task targets
              |
              v
SharedSceneGraph -> T03/T04/T05/T06 heads -> optional T07 head
              |
              v
      final RoadGraph logits
          /           \
       free       generic constrained
          \           /
       no-rule materializer -> M0 evaluator + grouped OOF
```

M2R 先完成 task-target readiness audit。单点 Case 缺少可追溯 surface/relation 时，默认只启用能够由 bundle 和人工确认边界证明的任务；仅在用户显式授权时，可对授权范围内的 Case 执行当前正式策略重放，其成功/失败业务终态视为人工确认真值，运行失败仍保持 `Unknown`。本轮授权仅覆盖 `E:\TestData\POC_Data` 的 T03/T04 单点 Case，目标权重 `1.0`、上下文权重 `0.3`。联合训练采用 task mask 和可信权重；free/constrained 使用相同 logits。通用约束只允许 schema、ID、引用、有限非空几何、split 顺序和生成状态合法性，不做业务补路或重连。

## 后续里程碑边界

方案 A Carrier baseline 和 Scheme-A-P1 均已完成。P1 从冻结骨架和登记 strategy replay 构建零 truth Segment/Movement carrier candidates，冻结 manifest/hash 后读取 carrier-only label，训练 object-conditioned GraphSet scorer，并用 precision-first confidence/anomaly threshold 驱动最小闭包 fallback。对象级指标与 RoadGraph 安全通过，但 coverage/anomaly precision 未过门，结论为 `P05_SCHEME_A_P1_MODEL_NO_GO`。若继续，应在现有 scorer 前建立 JunctionUnit 级一致 carrier-set truth/compatibility；禁止以错误替换 SWSD、扩大同一模型或 PTO-A 改写骨架来提高覆盖率。

该后续已作为 Scheme-A-P2-P0 完成：先冻结 Segment Road 与 Junction Node truth-free candidates，再以 label-only truth选择共同 `mainnodeid` 分组和 Node payload，Movement 全程不参与。其联合 exact=`0.546542`、`USE_RCSD retention=0.165753` 描述当时受限 carrier bundle 的组合安全性，不等价于数据或正确 carrier 缺失。

Dataset-P0 重新以模块职责和候选来源分母审计同一冻结数据：T01 只作 SWSD fallback，非 T01 truth-free proposal 对 2,190 个 `USE_RCSD` 目标 Road 全覆盖；23,224 final Road、27,553 final Node 与 8,823 个可用 Segment 的联合 exact 均为 `1.0`。下一阶段若另行授权，可在这套冻结高召回候选上设计 scorer；必须继续保持 candidate/label 物理隔离，并把离线 proposal 召回与在线轻量 proposal 性能分开验收。

P2-P1已完成：先以P1 Segment option和PTO全量FINAL_NODE truth-free payload构建candidate-first联合数据，再以Segment candidate→Road endpoint/source兼容边把Node重组为`T01_NODE / PROPOSAL_NODE / OMIT`。模型独立Node top-1约`0.7558`，通用联合选择后达到`0.9965~0.9985`，说明该分层解决了Node carrier来源问题。正式NO-GO来自高置信Segment错误、Review少数类和anomaly calibration，不来自候选缺失或图合法性；下一轮不得复活完整T06 Node Oracle标签，也不得只增加epoch。

P2-P2-P0进一步证明安全判定必须位于Segment根carrier选择进入Node条件化之前：真正accepted Segment根错误为`2/0/3`，其余对象级错误多数为Node传播或fallback前后口径。单一score/anomaly校准的最佳零错误USE覆盖仅`0.200275`，不得继续靠调阈值；现有feature无精确跨truth碰撞，因此后续可另立独立safety head，用嵌套Case-grouped cross-fit训练并保持Review禁止自动发布。

P2-P2-P1已完成该独立safety head实验并判定`MODEL_NO_GO`。410,786参数模型冻结P2-P1 proposal，只执行accept/abstain；三seed没有一个同时满足零错误和总体/USE 50%覆盖。模型之后的Node条件化闭包与49+2 RoadGraph均通过，因此当前技术瓶颈是Segment安全证据的跨Case泛化。不得用safety top-1改选carrier，也不得在本次held-out上继续调阈值；下一研究方向必须增加truth-free证据或独立预训练表征并重新授权。

P2-P2-P2-P0已对可合法增加的T01/T07、proposal/KEEP有向结构差、compatibility/Junction共享压力和base OOF统计完成审计。203参数线性probe仍放过2个错误；15,105参数浅层MLP全局零错误，但每fold安全门0/5通过，证明仅增加这些手工可解释结构量仍不足。当前停止当前特征路线的模型容量/epoch/阈值搜索；后续必须新增推理时可获得的信息，或另立预训练表征并用新冻结Case验证，不能将T03–T06 label/status/reason作为捷径。

P2-P2-P2-P1以只读归因替代继续调参。40 Review保留T01 access硬门；22个风险对象只由label-only T06/联合真值直接解释，truth-free joint fallback precision不足30%，只记为辅助信号。下一步保持这些对象强制fallback/Review，或另立阶段证明T06之前可独立生成的等价事实；若直接运行T06读取终态，则P05只作为后处理。

P2-P2-P2-P2已证明下一代分层方案可由现有数据监督：Segment carrier scorer选择`KEEP/USE/MIXED`，T03/T04节点证据与T05 relation作辅助目标，独立clue head报告RealityChangeClue，最后用通用Node compatibility/Junction closure保证共享carrier一致。推理期仍只消费T01/T07和truth-free candidate；T03–T06不作规则或直接输入。现有浅层MLP只有2/5 fold通过，不能复用为该分层方案的正式模型结论。

P2-P3-P0按该合同实现candidate listwise/correctness head、共享202维结构编码、独立clue head和7维辅助head。inner validation只冻结carrier/clue阈值，held-out决策再进入通用compatibility/Junction closure；Review永不自动发布，clue或低置信对象回退KEEP。正式结果证明decoder闭包完全合法，但模型选择性不稳定，因此下一轮不能继续在同一held-out上调阈值或只增加epoch。

P2-P3-P1不训练模型，只判断“下一轮是否已有可用新证据”。其证据库存结论保留，
但 stable false-use 与 fold 2 coverage-ceiling 属于旧标签/Case级联口径。
Dataset-P1 已把 T10 Case truth 与 Segment包 target-only truth分开，并把
expected-failure Case终态与对象级 failure group分开。下一轮若授权，必须先以
Dataset-P1 重建训练 dataset和全套指标；T03/T04/T05/T06 final字段继续保持
label-only，不得把本次分母修正解释为模型已经 GO。

P2-P3-P2已按该顺序完成可比重训：网络、202维证据、seed、fold与阈值选择方式
保持不变，只有Dataset-P1 eligible对象进入监督/metric；context-only对象直接
`KEEP_SWSD` fallback。整图安全全部通过，但可靠target false-use与
ADVANCE_RIGHT Review自动接受仍跨seed出现。下一步不得继续清洗同一标签或增加
epoch；应先把Review硬安全资格从carrier评分中解耦，再单独讨论新表征/独立验证。

原 M2 已因 M1 门槛失败关闭，M2R 也已因表示覆盖和 OOF RoadGraph 门槛失败完成 no-go。R2 的 `COPY/UPDATE/SPLIT/CREATE/DROP` edit-set、精确 pointer 和 small-batch 可学习性已通过，但当前全局 scene pooling + ordinal slot-query decoder 在 grouped OOF 上失败。下一轮若启动，应复用 R2 数据与输出合同，改为 object-conditioned graph/set decoder，使每个 edit/pointer query 与输入 Road/Node 建立 cross-attention 或 bipartite matching；不得把继续增加当前架构 epoch 当作主路径。扩大到 `POC_Data` 之外和生产推理集成仍不在当前范围。

PTO-P0 已完成该分解验证：登记策略从 raw/T01 提供的有限 proposal 覆盖全部 truth edit/pointer，Oracle cost 可将 51 Case 全局合法组合求解为 OPTIMAL/gap=0；但全链策略 replay 成本未过门。PTO-P1 先在冻结/缓存候选上把 Oracle cost 换成 object-conditioned learned scorer，同时另行建设轻量或增量 proposal generator。策略 proposal 不拥有最终决定权，求解约束不得编码业务内容。

JSG-PTO-P0 已按独立路径完成：冻结 T01/T05/T06/R2 evidence 生成 canonical Junction—Segment—Movement truth，evaluator 验证业务本体，再由 carrier realization 编译到 R2 edit IR 并复用 materializer。P0 没有生成无 truth 候选，也没有执行 PTO-A/PTO-B；这些已由 JSG-P1 完成。该结果已经把“模型需要预测什么”和“如何合法落成 Road/Node”从评分问题中分离。

JSG-PTO-P1 已完成。candidate builder 先验证 truth-free RoadGraph PTO manifest，从 T01 和登记 proposal lineage 生成 Case-local EvidenceGraph 与有限 enum/neighborhood candidates；冻结后 Oracle solver 才读取 P0 truth。PTO-A 选择业务对象及 Review，PTO-B 复用 RoadGraph group selection 并验证每个已选 Unit 的 carrier/access。正式双跑 51/51 通过，任何后续候选缺失或 infeasible 仍直接 no-go。

JSG-PTO-P3 已完成：context builder 从同组备选、P1 dependency/reverse-dependency 和 T01 相对方向证据生成 ID-free set context，candidate/context 双编码与乘性交互 MLP 以 listwise loss 学习每组选择；outer held-out 只在评分后进入评价，PTO 约束和 compiler 未因 scorer 改变。正式结果证明 object-conditioned scoring 有效，但旧 Connector 与 Review/Unknown 未过门禁，判定 `P3_MODEL_NO_GO`。该结论只作为历史模型证据；随后曾重建 carrier-only 合同，现又由目标 A 联合合同取代。

P2-P3-P3已完成Review硬门重放和残余可分性审计。后续固定顺序为：先提出一个
T06前可生成的新关系/共享上下文表征合同，验证其source role、生成时点、lineage、
成本、防泄漏及对残余对象的跨Case可分性；只有该表征审计通过后，才决定继续使用
逐对象scorer或升级为跨Segment/Junction图模型并申请训练授权。

P2-P3-P4将固定顺序改为
`Dataset-P1 scope -> context KEEP_SWSD -> Node/Junction truth closure -> metric`。
旧P2-P1的candidate/feature/payload/compatibility层按hash复用，只重建真值层。
修正后不再为原残余对象建设新表征；下一阶段若获授权，先在scope-first真值上
重训同一scorer并按原三seed五fold门复验，再由新错误证据决定是否更换表征。

P2-P3-P5 已执行上述策略：标签overlay双跑冻结后，复用P2-P3-P2训练器从头训练
15个fold模型，再重放access硬门并用修正Node/Junction truth物化整图。结果证明
“同一表征重训”可消除旧真值错误，但不能同时提高安全覆盖与clue稳定性；P6又确认
scorer层仍有稳定误选，只是被final RoadGraph阻断。

P2-P3-P6已将失败按fold、Case域、carrier rank、clue calibration和证据邻域分解。
后续固定为双路：先冻结新的T06前truth-free关系/共享上下文表征并做可分性审计；
同时建立与carrier rank解耦的clue/abstention校准合同。两路未获新授权前，不增加
epoch、不挑seed、不调held-out阈值、不训练新模型。

P2-P3-P7已完成两路的训练前审计：现有合法来源增加compatibility邻域与T01相对
几何后仍不可分，recall=1条件下的单调calibration-only也不可行。下一步不得直接
换模型或增加epoch；必须先由用户决定T03/T04推理角色，或授权建设新的确定性T06前
关系生成器。

P2-P3-P8完成T03/T04路线的训练前来源合同审计。carrier关系状态门通过，Clue来源
覆盖门失败。若继续，必须先批准carrier-only字段promotion合同，再以applicability
mask和冻结fallback做增量对照；不得把局部carrier结论扩成完整T03/T04输入或Clue
规则。

P9已按该策略训练。无来源严格不变和Clue隔离均通过，但后置source residual没有改变
任何适用对象分类，稳定错误仍为`USE_RCSD`。本策略正式NO-GO；不得通过继续同构训练
或放宽fallback复用，下一方案需评审joint conditioning或其他source-object交互。

P10使用“冻结输出→对象级裁决overlay→allowed合法性→preferred命中→独立Clue”的
顺序复算P9。609不再是错误，706317按Junction fallback硬约束，706346的保守KEEP
合法但非优选。真值校准GO不等于adapter GO；Treatment相对Control无严格增益时不得
启动同构续训。RCSD缺失对象先安全`KEEP_SWSD`，不得在没有独立冲突证据时生成Clue。

P12R固定顺序为
`普通Segment T06结果 -> 提右两侧source -> RCSD/SWSD carrier组合 ->
通用split/attachment materializer -> topology audit/fallback`。候选上限先用5m
局部RCSD集合审计，结果显示19个正确RCSD未被完整纳入，其中17个有直接lineage但
距离为`5.15–43.55m`。下一策略不得直接调大阈值或读取T06终态，应以Road
endpoint/JunctionUnit和相邻普通Segment carrier为条件扩召回，再按同一双跑门复验。

P12R-R1采用两阶段策略：Phase 1从冻结T01与原始RCSD构造并冻结endpoint/Junction
候选；Phase 2才加载P12R/T06 label-only工件计算Oracle。Treatment不放宽P12R local
Control，而是补充具有完整两侧incident/owner/orientation证据的原始RCSD bundle。
正式结果达到overall/worst-fold `0.979798/0.916667`。后续若获授权，应冻结R1
候选与P12R条件化真值，训练只负责候选排序/拒识的scorer，并继续由确定性fallback
与RoadGraph安全门决定是否发布。

P13-P0按“Local Control先验+神经残差加删候选+独立safety head”执行3 seeds ×
5 folds。candidate/object选择与发布安全分开评价，避免把保守fallback误算成模型
正确。模型相对Control只新增23次pooled exact，却破坏62次Control exact；116个
对象三seed稳定错误。后续不得继续同构训练、挑seed或调held-out阈值；若继续，应
先冻结相邻普通Segment OOF soft carrier输入合同，再判断joint model是否可训练。
