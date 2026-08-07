# 06 风险与技术债

| 风险 | 影响 | M0 控制 |
|---|---|---|
| 锚定候选序号不能还原为 RCSD 业务对象 | 模型指标可计算，但无法输出可执行、可审计的 Junction/Road/打断决定 | 推理 store 必须保留与候选特征同序的对象 ID sidecar；ID 只用于输出映射和审计，不进入模型特征，且候选顺序/hash 必须复核 |
| 下游 Road 分数反向替锚定消歧 | 绕过“锚定成功才可替换”的业务硬门 | 锚定 head 独立输出唯一结果；`AMBIGUOUS/ABSTAIN` 直接回退，下游 decoder 不得修改锚定 |
| 普通 Segment 与提右被独立评分 | 提右看不到两侧最终 access 来源，重复 P13 表征缺陷 | 先锁定普通 Segment 完整方案和 access，再条件化生成 `ADVANCE_RIGHT` 完整方案 |
| 普通 Segment 将 KEEP/USE 的所有 Road plan 平铺评分 | 某一业务状态可能因候选 bundle 数量更多而天然占优，状态错误掩盖 bundle 完整性错误 | 先显式输出 KEEP/USE/ABSTAIN，再在状态内归一化并选择完整 Road 清单；不得把最终 carrier 降级成状态标签 |
| 普通 Segment 跨 Case 泛化不稳定 | v45 以逐 Road 成员 + 对称 arm 匹配同时超过 v41/v44 的总体、KEEP、USE 和最差 fold，六个主要 Case 相对 v41 均净改善或持平；但单 seed 仍有 267 个自动完整 plan 错误。v46 的端点 local/foreign 锚定关系只净改善 1 个样本，却把危险 `KEEP->USE` 从 98 增至 110 | v45 作为结构基线，v46 只作边界诊断，v41/v44 保留 paired 对照；停止 class/Case 权重、后置 residual 和简单集合池化搜索。下一轮优先审计并隔离 `KEEP->USE` 安全错误，再处理 `USE->KEEP` 的可辨识监督与关系缺口；未满足零危险和多 seed 前不启动下游自动发布 |
| Clue/scope 监督不足 | 全量 8,863 条 plan 标签仅 5 条含 Clue/scope；普通 Segment 训练范围仅 4 条。v47 segment-local safety 接受 189 个 USE 仍有 9 个危险；v48 加入全量 truth-free Junction 邻接统计后接受 217 个但危险增至 14 | 不把 KEEP 终态反推为无证据/现实冲突，也不把 post-hoc 阈值当 Clue 模型。v47/v48 只作 NO_GO 诊断；后续联合 Junction 状态与 scope head 前，必须取得明确、可审计且覆盖不同原因/作用域的监督，或将未辨识对象全部 ABSTAIN |
| Case-balanced loss 放大单样本 Case | v42 个别训练分区权重最高约 175 倍，虽改善最差 fold却损害 USE_RCSD | v42 只作诊断，不作为训练默认值；原始标签置信权重继续保留 |
| 城市级数据反复读取 | 数十万至百万 Node 场景 I/O 成为主耗时并造成重复解析 | 城市级一次读取、标准化列式/图缓存和对象索引；forward 只取动态业务依赖子图，空间切片只加速查询 |
| 本地 Case 含少量噪音 | 模型学习错误模式 | 权重分级、异常清单、可请求重新人工评估 |
| T03/T04 缺少直接 RoadGraph 标签 | 多任务覆盖不足 | task mask，不伪造规则输出 |
| baseline 来自不同历史 commit | 标签工艺不完全一致 | 记录 repo head、run summary 与 artifact hash |
| 相同业务对象多版本 | train/test 泄漏 | stable business-ID grouped split |
| 模型输出可能改变 ID | 仅 ID 指标低估质量 | 受门禁确定性几何 fallback，分层报告 |
| 几何相似但方向/拓扑错误 | 指标虚高 | 属性、端点和有向图 hard gates |
| 训练框架和显存规划过早固化 | 返工 | M0 不引入 PyTorch，M1 根据有效样本覆盖率选型 |
| 不同局部 Case 空间重叠 | 相同 Road 跨 split 导致指标虚高 | M1 entity guard 按 test、validation、train 唯一归属并移除低优先级一跳邻域 |
| 固定 test 只有 5 个 Segment Case | 无法代表标准 T10 或生产分布 | 开发集 group CV、标准 T10 shadow holdout 和固定 test 分层报告 |
| 将 P2 `retention` 当成数据可达性 | 错误要求 T01 生成 RCSD，或误判现有 Case 不够 | Dataset-P0 将 T01 SWSD fallback 与非 T01 proposal 分开统计；历史 P2 只保留受限 bundle 安全指标 |
| P2-P1 Node候选只读单一replay | 正确Node存在于PTO候选但不进入模型，重现不可选择问题 | 读取PTO-P0全量FINAL_NODE多来源payload，按endpoint/JunctionUnit冻结option后再接条件化标签 |
| 完整T06 Node Oracle直接与方案A混合Road真值组合 | `KEEP_SWSD` Road所需T01 Node缺失，Oracle本身无法生成合法整图 | Node标签由Segment Road来源选择T01/proposal/OMIT，共享payload冲突执行Junction fallback；PTO Oracle仅作候选可达性证据 |
| 条件化Node把错误Segment传播为合法Node组合 | 图合法不等于carrier业务正确，高置信Segment误选可连带多个Node并被自动接受 | P2-P2-P0已将17/9/17分解为accepted Segment根错误2/0/3及Node传播；单一校准最多保留20.03%零错误USE，后续在Node条件化前训练独立class-aware/cross-fitted safety head，不用T06规则修正输出 |
| 独立Segment safety head不能跨Case稳定泛化 | P2-P2-P1中零错误seed覆盖仅约7%，较高覆盖seed仍放过4~5个错误；在同一held-out上继续调参会造成选择泄漏 | 当前head正式MODEL_NO_GO并降级为review研究；后续只允许在新授权阶段增加truth-free证据/预训练表征并重新做Case-grouped验证，不直接扩模型、加epoch或调现有阈值 |
| 可解释结构证据的增量仍不足 | P2-P2-P2-P0浅层MLP全局零错误，但0/5 held-out fold通过完整recall/coverage门；平均值不能证明未知Case安全 | 当前evidence正式NO-GO，停止同一202维特征上的调参。只有新增推理期信息或独立预训练表征并更换冻结验证证据才可重启；label-only字段提升必须二次确认 |
| 22个直接原因仅存在于label-only源事实 | 16个truth-conditioned Junction fallback、5个T06 carrier Road缺失和1个T06 MIXED_CARRIER在现有推理合同中不可见；直接读取会产生truth泄漏或退化为T06后处理 | 当前全部保持fallback/Review。只有T06之前独立生成、业务语义明确且lineage完整的等价事实可另行审计；相关joint fallback信号不得作为硬门 |
| 旧unsafe指标混合carrier错误与clue漏报 | 正确KEEP但漏报异常会被误称为错误Road，掩盖真实的cross-case coverage不稳定 | 固定carrier safety/clue visibility双指标；P2-P2-P2-P2虽carrier全局通过，但2/5 fold coverage通过，仍NO-GO |
| 单层模型不能同时表达carrier、MIXED与Junction共享依赖 | 候选虽可达，独立Segment判断组合后仍可能产生共享Node来源冲突 | 后续若授权采用分层carrier+clue+通用Junction closure；T03–T06仅作辅助监督，禁止作为推理捷径 |
| 分层模型仍存在cross-case selective calibration风险 | P2-P3-P0整图合法，但同一Segment在seed 311/313稳定错误USE，seed 317靠大量clue/fallback换取零错误；fold 2三seed覆盖均低 | 冻结MODEL NO-GO和双跑signature；禁止在已见held-out上调阈值/挑seed，后续必须使用新推理期表征或新冻结验证证据 |
| 直接证据与独立验证库存为空 | P2-P3-P1确认稳定错误/clue直接事实只在label-only层，且现有51 Case已全部用于OOF | 保持EVIDENCE_NO_GO；不把label-only字段或已见Case伪装为新证据，后续另行授权表征/验证建设 |
| Case expected failure级联污染对象指标 | 旧P2-P3把609214532的1,795段和74155468的159段全部改为fallback，混淆Case不可发布与对象评分 | Dataset-P1固定Case terminal/object failure双层合同；只对failure group局部失败，corrected cascade mask=0 |
| Review/anomaly少数安全类不稳定 | seed43仅12/40 Review正确，异常precision低于0.40 | 将Review与RealityChangeClue从共享early-stop指标中独立建模/校准；未经新阶段授权不得在本次held-out结果上调阈值重报GO |
| SPLIT/生成 Road 为少数类 | 平均 F1 掩盖几何生成失败 | 单列 operation macro-F1、split recall、uncovered truth 和完整 RoadGraph 指标 |
| 训练环境与仓库 Python 不一致 | checkpoint 难复现 | PyTorch 独立 optional dependency和隔离环境；完整记录 Python/CUDA/GPU |
| 单点 Case 只有输入 bundle | 把人工确认对象误当完整 surface/relation 真值 | M2R task-target readiness audit，缺失任务保持 Unknown |
| 多任务标签粒度不同 | 大样本任务掩盖小样本 Head | task mask、可信权重、逐 Head loss/梯度/指标审计 |
| Segment包上下文被当成0.3弱标签 | 非目标Segment污染carrier/clue训练和指标，stable-wrong可能只是context误判 | Dataset-P1将0.3限定为context input；只有target ID或精确Road partition后继可用0.7标签，旧8,863指标历史化 |
| Dataset-P1同模型重训仍不安全 | 可靠target false-use在两个seed复现，seed313自动接受12个ADVANCE_RIGHT Review；零错误seed覆盖仅0.1506 | 保持P2-P3-P2 MODEL_NO_GO；先把Review/ADVANCE_RIGHT硬安全资格与carrier scorer解耦，剩余false-use需新T06前表征/独立验证，禁止挑seed |
| 通用约束夹带业务规则 | 虚假证明模型生成能力 | 合同白名单、intervention audit、事后内容修复必须为零 |
| M1 test 已访问 | 重复调参导致指标偏乐观 | M2R 以 grouped OOF 为主，历史 test 只作回归 |
| M2R 表示不完备 | 模型无法生成约 `13.21%` truth | R2 先用含 CREATE 的 Road/Node edit-set通过 oracle 重建门禁 |
| oracle truth 泄漏 | 表示门禁被误当模型能力 | oracle payload 强制 label-only，input role 白名单和泄漏测试 |
| CREATE/SPLIT 稀有 | 平均指标掩盖少数动作失败 | 分 action macro-F1/recall、拓扑保持 crop 和现有 truth 重采样 |
| ordinal slot-query 缺少对象匹配 | 模型能拟合 small batch，却把 fold 内 slot/layout 先验当成图生成规律 | 当前架构停止增加 epoch；下一轮使用 object-conditioned cross-attention/bipartite matching graph/set decoder |
| PTO strategy proposal 泄漏或冒充模型 | 重放结果可能与 truth 相同，掩盖 learned scorer 尚未训练 | candidate/label manifest 物理隔离、truth 输入计数为零；P0 只声明 candidate reachability，P1 OOF 才声明学习能力 |
| PTO 候选规模或 replay 成本过高 | P0 候选/求解满足预算，但全链策略重放已实测超过在线预算 | P1 先使用冻结/缓存候选；并行实现轻量或增量 proposal generator，完整记录 replay CPU/RAM 并重过端到端性能门 |
| JSG 自动字段映射固化错误语义 | 51 Case 局部字段不足以支持通用业务规则 | 只使用已声明字段语义；保留 raw evidence，冲突进入 REVIEW/anomaly，不反推上游强规则 |
| JSG Oracle carrier 被误称推理能力 | R2 truth 可使编译精确，但不证明候选或模型泛化 | carrier/edit IR 强制 label-only；P0 只声明本体与 compiler，JSG-P1 才验证无 truth 候选 |
| JSG 零实例类型被虚假计满 | loop 等类型可能没有真实正例 | observed/expressed/review/unexpressed 分列，零实例只验证 schema/合成测试 |
| JSG-P1 candidate 读取 truth | Oracle reachability 会退化为复制答案 | candidate API 不接受 truth 路径，先冻结 manifest/hash，再允许 solve API 加载 P0/R2 truth |
| JSG-P1 PTO-B 复用策略 proposal 被误称模型能力 | truth-free proposal 仍来自历史规则 replay | source_kind/commit/hash 全保留；P1 只声明候选/Oracle，历史 replay 性能与模型泛化均不升级 |
| JSG-P2 线性模型记忆 ID | 高维 candidate/object/Case ID 可使 grouped OOF 失真 | ID 只用于 join/audit；feature vocabulary forbidden-token audit 为零，fold model 不含 held-out Case |
| JSG-P2 强制降低 Review | 总体 accuracy 可能以错误发布换取 | Review/Unknown recall 独立门禁；121/26/411 Review 边界继续保留 |
| 旧 SegmentConnector/PTO-A 污染当前本体 | 模型指标可能建立在可改写骨架的错误目标上 | 当前只允许 T01 FrozenSegment 业务骨架；目标 A 学习完整锚定/Road/Clue/scope 决策，旧 carrier-only、Connector 和 P0–P13 只作历史证据 |
| fallback 伪成功 | SWSD Road/Node 本身不合法却仍被计作成功 | fallback 后重新验证独立 Road、端点、CRS、方向和拓扑；失败生成 clue |
| expected failure 稀释正式分母 | 为满足51/51合法而排除或修复基础 SWSD 非法 Case | 固定两 Case manifest；保留在51 Case分母，只允许 `EXPECTED_FAIL + clue + no publish` |
| evidence conflict 被模型消解 | 模型可能通过增删 Segment、吸附重连或传递扩大 fallback 隐藏现实变化 | skeleton mutation hard fail；只输出 RealityChangeClue 和显式有限 `FallbackDirective`，Segment/Junction 边界不可跨越 |

当前技术债包括：T03/T04 单点 bundle 多数没有历史 surface/relation 目标；T05/T06 完整真值主要集中在 51 个 T10 RoadGraph Case；固定 test 已访问且不含标准 T10；CREATE/SPLIT 稀有类不足。R2 已证明输出表示完备，但当前 ordinal slot-query 模型无法跨 Case 保证对象匹配、端点与有向拓扑闭合。RoadGraph PTO-P0 又证明候选/formulation 语义可行，但全链策略 replay 不适合作为在线 proposal generator。JSG-PTO-P0 已证明本体字段映射、Review 边界与 compiler；后续仍不能靠放宽指标、继续增加当前模型 epoch 或把 label-only carrier 当成推理能力推进。

已完成的 JSG-PTO-P1 仍依赖冻结的历史 truth-free strategy proposal 作为 PTO-B 基础设施，因此候选/Oracle 门通过只构成离线语义 GO；轻量/增量在线 proposal generator 仍是独立技术债。

JSG-PTO-P3 已完成并判定 `P3_MODEL_NO_GO`。当前方案 A baseline 与 Scheme-A-P1 也已完成；P1 对象级 scorer 和 RoadGraph safety 很强，但逐对象 truth 的整图 carrier 来源不一致使 accepted coverage 仅 `0.3533~0.3637`，正式判定 `P05_SCHEME_A_P1_MODEL_NO_GO`。后续技术债是 JunctionUnit 级一致 carrier-set truth/candidate compatibility 与 anomaly calibration；不得直接复用旧 Connector/PTO-A 目标、扩大同一模型或进入生产。

Dataset-P0 已证明当前51 Case的离线高召回 candidate 数据充足，因而“补更多 Case/让 T01 产 RCSD”不再是当前阻塞项。剩余技术债转为两条独立线路：一是冻结候选上的 scorer 泛化、整图兼容性与异常 calibration；二是历史 strategy replay 约 `5751s` 的在线性能，必须通过轻量/增量 proposal generator 单独解决。Dataset-P0 GO 不消除这两项风险。

P2-P3-P3已消除`ADVANCE_RIGHT access_valid=false`的Review自动接受风险，但残余
KEEP对象在现有特征空间中被三个seed稳定视为USE，60/60 held-out近邻均为USE。
后续必须先补充并冻结T06前关系/共享上下文表征，再选择逐对象或跨
Segment/Junction图模型；同一表征继续训练不是主路径。

P2-P3-P4已关闭“残余KEEP对象证明新表征不足”的解释：该对象的旧KEEP真值来自
context-only先参与Junction闭包的顺序缺陷，修正后是USE且既有三seed选择均正确。
因此不得继续引用60/60近邻作为新表征启动理由。仍未关闭的技术债是模型在修正真值
下的safe coverage与clue precision/recall跨seed/fold不稳定；下一步先重训复验，
只有新错误仍显示当前证据不可分时才重新讨论表征。

P2-P3-P5已完成重训复验，P2-P3-P6随后关闭了“零错误自动接受”的错误解释：
零错误只成立于final publication，scorer层三seed各有1个稳定误选。当前技术债
明确为两条：clue threshold跨`0.000296–0.998983`导致不同Case域过报/漏报；稳定
wrong的top-20训练邻域全部为`USE_RCSD + clue=false`，现有202维表征缺少正确区分。
两条必须同时解决；不得直接扩大同一模型、挑seed、调当前阈值或把label-only T06
事实提升为推理输入。

P2-P3-P7进一步证明Case内compatibility聚合和T01相对几何仍未提供决定性关系事实，
排除Movement后结论不变；calibration-only也不可行。技术债现收敛为合法推理来源
缺口，而不是样本数量缺口。T03/T04是否可从label-only提升为推理来源，或是否建设
新的确定性T06前关系生成器，必须由用户明确决策。

P2-P3-P8证明T03/T04来源只能局部关闭carrier证据债：504/6,275对象适用，但稳定
Clue错误只覆盖1/6。后续最大风险是把局部部分GO误读为整体模型GO。必须保留
applicability mask和无来源fallback，carrier与Clue分别验收；字段promotion未经
用户批准前不得实施。

P9训练已完成：无来源和Clue污染风险被证伪，但promotion有效性失败。当前主要风险是
把“安全隔离成功”误读成“模型有效”；正式事实相反，adapter未改变适用对象分类，
稳定错误仍存在。后续若研究joint conditioning或logit门控，必须以P9 Control作为
冻结比较基线，并重新获得训练授权。

P10证明旧稳定错误是T10 Case级0.7标签被误当Segment硬真值。当前用对象级1.0裁决、
allowed/preferred分层和Clue独立指标治理；但事后裁决不得回流训练后重报同一held-out
结果。P9技术债现收敛为“adapter无增益”和“Clue跨seed不稳定”，不再包含609 carrier
不安全归因。RCSD数据缺失只触发安全`KEEP_SWSD`，不能单独构成
`RealityChangeClue`；剩余Clue风险主要表现为保守误报。

P12R关闭了“提右应由T05锚定”和“当前提右真值不足”的错误解释。当前技术债是
候选发现：5m局部空间窗漏掉19个`RCSD_ONLY`对象需要的至少一个Road，其中17个
存在原始RCSD直接lineage，2个还需要补全可消费lineage。风险是为了过门直接扩大
距离阈值，从而引入跨路口错误候选；下一轮应使用Road endpoint/JunctionUnit与
相邻普通Segment carrier条件化扩召回，并继续由通用拓扑约束安全fallback。

P12R-R1已关闭上述候选规模内可达性技术债：新增180条候选带来11个Oracle净增且
无损失，最差fold过0.90，候选规模仍为P95/max `4/12`。剩余8个eligible漏候选不再
阻断R1 GO，但必须继续保留在拒识/fallback审计中。下一主要风险是把candidate GO
误读为model GO，或把endpoint距离阈值固化成业务锚定；任何训练阶段仍需证明
held-out排序、安全拒识、fallback和RoadGraph终态，而不能仅报告Oracle上限。

P13-P0证明candidate GO不能直接推出model GO。当前主要技术债是提右Road选择缺少
“相邻普通Segment替换后实际采用RCSD还是SWSD”的推理期条件；现有50维候选级
关系/几何不能稳定替代该条件。直接读取T06终态会变成后处理泄漏，继续扩大当前
网络也没有依据。下一轮若获授权，应只审计普通Segment OOF soft状态的生成时点、
held-out独立性、误差传播和fallback边界；审计未通过前不启动P13-P1训练。

v235r2–v241r1 已关闭上述“提右看不到相邻 ordinary 最终状态”技术债中的
SWSD-only 路径：两 seed 交集自动 414/474、完整方案 exact=1、危险为 0，
且 414/414 可物化。但当前相邻侧没有自动 RCSD，因此不能据此关闭
RCSD_ONLY/MIXED_SPLICE 风险。剩余核心技术债已经前移到普通 Segment：

- v231/v233 总体完整 Road set exact 约 0.71，但 10+ Road exact 仅
  0.18～0.22，预测平均集合明显小于真值，继续增加 cardinality head 或 epoch
  容易固化提前 STOP；
- 首次 v234 曾让 26 个 USE 绕过锚定前置门，说明“执行前还能 fallback”
  不能替代模型发布门正确；v234r1 已修正并把 USE 自动数降为 0；
- 两 seed 在 530 个完整 Road set 上分歧，完整业务门零危险自动覆盖只有
  3.58%，且全部为 KEEP；平均 exact 不能代替跨 seed 稳定性；
- 普通 USE 当前没有任何对象同时通过锚定、完整 Road set、ownership/角色
  一致性；access/Node/打断/几何 recipe 仍无可发布自动覆盖；
- `INTERNAL_CONNECTOR`、`ATTACHED_SWSD` 的强监督极少，直接把名称当稳定
  多分类目标会产生虚假高总体 accuracy；应分解为来源、所有权、连接与附属
  属性，并对未验证组合保持 fallback。

下一轮风险控制是冻结 v240r1/v241r1，不再以局部 AdvanceRight scorer 调参；只在
普通 Segment 上训练 access/主干 seed 条件化的拓扑结构扩展，使用完整候选同批、
大集合 hard-example replay、渐退 teacher forcing 和严格 Case-OOF。任何提高
Road F1 但未同时改善完整集合、10+ Road、执行 recipe 与零危险门的结果均不得
解释为收敛。

v243r2–v247 进一步收敛了 ordinary 技术债：

- STOP bias 扫描不改变 outer 结果，不能再把长集合失败归因于单一阈值；
- 三动作 decoder 将 overall exact 提高到 `0.701754`，但 10+ Road 降为
  `2/16`，低估和过估同时存在；
- truth-free beam oracle@16 达到 `0.897661`，但可学习 reranker 未提高 raw
  exact，说明候选可达与稳定选择之间仍有明显差距；
- 直接加入 672D graph/Road embedding 使 fold2 exact 降到 `0.611111`，
  证实高维绝对表征存在跨 Case 过拟合风险；
- 当前不应继续扫 STOP、增大 beam、扩大 embedding 或完整 OOF。下一步必须
  使用跨 Case 可比较的关系量表达完整方案，并同时验证 raw exact、10+ Road
  exact、零危险覆盖以及逐 Road ownership/角色完整性。

v248–v255 暴露了两个新的口径与架构风险：

- case-invariant Road–Road 关系可以跨 Case 泛化，v253 outer pair F1 达到
  `0.654739`；但独立 same-plan pair 分类不能保证完整 Road 清单正确，不能
  作为 decoder 的替代目标；
- 把“beam 不可达时正确 ABSTAIN”合并进 raw exact 会高估 carrier 能力。
  后续必须分别报告 reachable-plan exact、unreachable safe-abstain、
  自动接受覆盖和 fallback 后最终 exact；
- v250 多视图方案可达 `311/342`，与当前锚定 hard gate 相交仅
  `214/342=0.625731`。现有串行锚定输出已成为 Target A 80% 覆盖目标的
  理论上限，继续优化 decoder 无法跨越；
- 所谓“联合模型”不能只把冻结 OOF 锚定条件拼入 ordinary batch。必须在
  Case 级 combined batch 中让具体锚定候选与 carrier 方案共享证据 encoder；
  同时保持业务硬约束：锚定头独立确定唯一对象，carrier loss 和整图 decoder
  均不得替锚定头选择或绕过结果。

v256–v264 已把上述 combined batch 落地并暴露新的收敛风险：

- 城市/Case 传递闭包最大达到 3,117 个对象，既不符合 Segment/Junction
  阻断边界，也会造成显存和 I/O 放大；正式 forward 必须保持 focal Segment +
  required anchors + 一跳直接锚定依赖，空间切片不得截断该依赖；
- v257r3 的 shared encoder 能同时接受 anchor candidate 与 carrier plan
  梯度，且 anchor prediction inconsistency 为 0；但 concrete anchor exact
  只有 `0.758123`，说明共享 forward 本身不等于锚定对象已收敛；
- 直接或辅助 anchor-plan compatibility 均降低完整 plan exact。风险是再次
  让 carrier 证据间接替锚定头选对象；该路线已停止；
- 只按 `P(NO_EVIDENCE)` 校准会在 held-out Case 把已知 SUCCESS 误放为无证据。
  当前必须同时要求 unique-anchor gate 拒绝，并继续由 inner-only 阈值校准；
  该修正消除了 v260r1 的 1 个危险项，但自动覆盖仅 `0.83%`；
- fold2 的 500 个唯一 required anchors 中，198 个缺少 status 或 concrete
  candidate 真值，影响 356 个普通 Segment。56 个未知对象已经进入模型
  release 候选，导致全局安全阈值被迫抬高。风险不是泛称“Case 数不足”，而是
  缺少这些 SWSD semantic anchor 的四值人工监督：唯一对象、已证明无证据、
  歧义或候选缺失；
- `relation_record_absent` 不得用于扩充分母或自动释放。Phase 1 只允许通过
  v264 的 EPSG:3857 可视证据裁决 30 个锚定对象；v265 已证明这些对象没有
  可按同一输入与同一局部对象严格继承的 T03/T04/T11 跨样本真值，不能用
  空间近邻、模型预测或 ID 重名缩减人工范围；回填管线必须校验冻结列、
  candidate 完整身份和证据说明，并保持 inference feature 字节一致。任一
  required anchor 已明确失败即可阻断当前 Segment，未裁决对象继续局部
  fallback。
