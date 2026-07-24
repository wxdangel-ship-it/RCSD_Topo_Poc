# RCSD_Topo_Poc 项目级需求详细版

## 1. 文档定位

本文档是项目级需求详细版，用于解释 `SPEC.md` 中简版需求的业务背景、范围、模块分工、质量边界和改进路线。根目录 `SPEC.md` 只保留简洁需求入口；跨模块方案如何落地见 `docs/architecture/03-solution-strategy.md`；模块内部需求见 `modules/<module>/SPEC.md`，模块架构设计见 `modules/<module>/architecture/03-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 2. 业务背景

项目要解决的问题是：SWSD 更贴近现场道路语义和通行规则，RCSD 更贴近场景路网承载，两套数据在道路切分、节点归组、方向表达、提前右转、路口内部短连接和局部缺失上存在差异。项目需要把 SWSD 的现场语义能力迁移到 RCSD / F-RCSD 承载网络中，并让每一步都有可追溯的证据和审计。

因此项目采用 relation-first 的融合思路：先建立可信的 SWSD-RCSD 语义路口关系，再沿路口之间的 Segment 做承载替换。路口 relation 是 Segment 替换的前提，但不是替换成功的充分条件；T06 必须继续检查 RCSD 道路、方向、端点、拓扑和 surface 证据，防止错误替换。

## 3. 业务链详细需求

### 3.1 输入准备层

T08 负责把 SWSD / RCSD 原始输入整理成下游可消费的数据。它需要处理格式转换、Road/Node 类型归一、restriction / Laneinfo 显性化、RCSD 清理和质量问题暴露。T08 的输出不直接代表替换成功，但决定 T01、T03、T04、T05、T06、T09 是否能稳定消费同一套输入事实。

### 3.2 Segment 基础层

T01 负责将 SWSD Road/Node 组织成 Segment。Segment 需要保留 pair 节点、junc 节点、road body、方向和等级语义，使 T06 能以“两个语义路口之间的道路连续单元”为替换对象，而不是直接处理零散 Road。

### 3.3 路口关系层

T07、T03、T04、T05 都服务于 SWSD-RCSD 语义路口关系构建，但分工不同：

- T07 处理已有路口面 / RCSDIntersection 能直接说明关系的路口，并保留可选兼容 relation 补锚能力；该补锚来自显式提供的早期或外部 `intersection_match_all` 兼容关系，不是 T05 之后默认重锚。
- T03 处理交叉路口和 T 型路口，通过合法道路面空间、RCSD 关联和负向约束构建虚拟锚定面。
- T04 处理分歧、合流、连续分歧 / 合流和复杂路口，通过事实事件解释、支撑域和最终发布结果形成复杂路口锚定证据。
- T05 将 T07/T03/T04 的 surface 与 relation evidence 汇总为统一的 `intersection_match_all`，并对 RCSDRoad / RCSDNode 做 copy-on-write junctionization。

这一层的业务目标是让每个 SWSD 语义路口在下游拥有唯一、可解释、可审计的 RCSD 关系基点或明确失败原因。

### 3.4 Segment 替换层

T06 的原始目标是基于 T01 Segment 与 T05 relation 将 SWSD Segment 替换为 RCSD Segment。端到端 Case 修复后，T06 的实际职责已经扩展为替换质量承接：

- relation 缺失或疑似错锚时，T06 需要输出 buffer-only probe、repair candidates 和 problem registry，而不是静默替换。
- RCSDRoad 与 SWSD Segment 切分不一致时，T06 需要用 buffer corridor、方向、连通和覆盖审计证明替换范围。
- pair anchor 错误、端点缺失或两端坍缩到同一 RCSD 语义路口时，T06 只能在高置信、方向和几何审计通过的条件下做当前 Segment 内重试，不能回写 T05 relation。
- 提前右转、内部调头口、road-only split 和 detached junc 可能导致主通道可替换但局部 carrier 仍需保留；这类混源必须通过状态和风险标记表达，不能混入正式 RCSD 替换道路清单。
- T03/T04/T05/T07 surface 可以帮助节点语义闭合；对 retained-junction 20m 距离 gate，只能在 surface 1:1 pass 或原始 pair endpoint 映射可解释时降级为人工审计风险，并必须经过 topology 回退。它不能绕过 T04 reject、Patch 冲突、多候选冲突或 Step2 replacement plan。

T06 的核心边界是“先证明可替换，再执行替换”：Step2 发布 replacement plan 和 problem registry，Step3 只执行 plan，并用 source 边界、提前右转后处理、surface topology closure 和 topology connectivity audit 保护最终 F-RCSD。

### 3.5 人工审计层

T11 在 T10 正式工作流中位于 T06 与 T09 之间，读取当前 Case/full run 的 T05/T06/T10 证据，输出 relation repair candidates、人工模板和 summary。T11 是人工审计层：不回写 T05/T06，不改变 T09 输入，也不把候选提升为人工确认或替换白名单。

### 3.6 通行恢复层

T09 在 T06 输出的 F-RCSD 承载关系上恢复 SWSD 现场通行规则。当前 T09 主要依赖 SWSD restriction / Laneinfo，后续需要结合 RCSD Laneinfo 和轨迹通行证据继续增强。

### 3.6A F-RCSD 质量审计层

T12 面向通过 1V1 匹配技术融合生成的原始 F-RCSD，不把它解释为 T06 Segment 替换结果。T12 以“SWSD 与 1V1 F-RCSD 的拓扑通行性应等价”为待验证质量假设，复用 T06 的 ID、方向、canonical node、carrier graph 和局部 portal 证据语义，检查已锚定 Segment 两端在目标承载网是否存在可解释通行路径。`RCSDIntersection` 是 T07/T10 标准输入和人工确定的现实路口证据；T05/T06 只提供交叉解释证据，不替代 T12 对原始目标网的判断。

T12 必须分离 candidate、confirmed、excluded 和 optional review override。candidate 不是正式质量问题；原始 FRCSD Road endpoint 图证明 SWSD 必需方向缺少等价 carrier 后，还必须检查 portal-constrained semantic carrier 和 T07 Road-surface portal carrier。既有 semantic carrier 继续要求物理 Road、方向/长度/走廊、端点 portal 与内部 alias 门禁。Road-surface carrier 只在两端均为正确且唯一的 T07 `RCSDIntersection` 标准面锚定时启用：实际有向 Road 与对应标准面相交，或 Road frontier 可被锚点组一跳物理 Road 明确连接，均可形成 surface access；一跳 support Road 必须从 anchor 向 frontier 有向并与标准面相交或位于 `1m` 拓扑容差内，整条 carrier 至少一端必须存在实际 Road-surface contact，双端仅靠任意一跳邻接不得成立。方向、物理 Road、锚点唯一性和路径长度等价仍是强门禁；Road-surface gap、SWSD portal gap、内部 alias gap 和走廊距离等其它距离指标仅作人工审计风险，不得单独拒绝。两类 carrier 都只能作为高置信误报排除证据，不能单独确认问题。完成两层排除检查并通过锚点可信度门禁后仍缺失的记录，才能自动进入 confirmed 层。canonical 零长度折叠、无物理 Road 路径和任意近邻节点不得补出正式 carrier。外部 review decisions 只作可选 QA 覆盖，不再是 confirmed 的前置条件。排除原因必须可追溯，任何阶段都不得修改输入几何、自动补路或 silent fix。

### 3.7 编排与证据层

T10 负责组织端到端 Case package、Case replay、full pipeline manifest、T06 funnel、可选 T12 quality audit、T11 candidate audit、visual check 和 feedback package。T10 不定义或改写 T01-T09 / T11 / T12 的算法规则，不把 T06 feedback 直接作为 Step3 替换白名单。T10 v1 Case runner 默认在 T06 后、T09 前执行 T11；显式启用并提供原始 1V1 F-RCSD 时在 T11 后、T09 前执行 T12。两者都不改变 T06 到 T09 的业务 handoff。T10 提供固定 `RUN_T08=0 / RUN_T12=1` 的 F-RCSD 质量检查专用流水线；普通 Case runner 不调用 T08，通用内网全量总控仍可把 T08 作为独立前置阶段串入。

### 3.8 神经网络 Road 直出 POC

P05 当前采用 2026-07-22 确认的方案 A。T01 Segment 集合、Junction—Segment 关系和 PhysicalMovement 存在性冻结；神经模型只替换策略中的软判断、carrier 候选评分/排序、Road/Node carrier 选择以及异常概率判断，不新增、删除、合并、拆分 Segment，不改变 Junction 归属，也不以 PTO-A 重选业务结构。正式 Segment 必须至少拥有一条独立 Road，普通提右统一为含 `source_segment_access/target_segment_access` 的 `segment_type=ADVANCE_RIGHT` Segment，可保留真实 `junc_nodes`，不再使用 `SegmentConnector` 作为当前业务类型；access 不唯一时必须失败并形成线索，不得按几何邻近猜测。

如果推理证据与冻结结构冲突，P05 只生成 `RealityChangeClue` 并执行最小依赖闭包 fallback：Junction 冲突使关联全部 Segment 保留 SWSD，Segment 冲突只回退该 Segment且不自动改变或回退相关 PhysicalMovement；Movement 仅因自身问题回退，carrier 确实共享或影响 Junction 内部拓扑时才升级为 Junction fallback，否则只回退该 Movement。fallback 后结果符合统一本体、独立 Road、引用、方向、CRS、拓扑与 lineage hard gate时计 `SUCCESS_WITH_FALLBACK`，否则计 `FAIL`。准确性和安全性优先于自动化率。

Scheme-A-P1 的安全验收要求 51/51 Case 都有确定终态，但不要求把原始 SWSD 非法 Case修成合法图。冻结范围内 `T10:74155468` 缺少端点 Node `953982`、`T10:609214532` 缺少端点 Node `987665`；两者必须稳定输出 `FAIL + RealityChangeClue`，不得发布、补点、吸附或改写骨架。其余 49 Case必须全部通过 RoadGraph hard gate。两个预期失败仍参加51 Case的模型、fallback与异常指标计算，不得当作排除项。

下述 M1/M2R/R2/PTO/JSG-PTO-P0/P1/P2/P3 均为历史实验事实，用于保留模型、候选、编译与资源证据，不再定义当前业务骨架。旧 `SegmentConnector`、PTO-A 结构选择和 Connector/Review 指标必须按方案 A 重新解释。

方案 A baseline 已正式完成。按已确认的 fallback 边界重跑的 Run A/B `p05_scheme_a_baseline_20260722_12/_13` 覆盖 51 Case、8,863 Segment、474 ADVANCE_RIGHT、24,779 PhysicalMovement，骨架变更为零且五类业务 signature 一致。8,823 个 Segment carrier 标签可用，40 个 ADVANCE_RIGHT 因 access 无法唯一证明而 mask/失败；21,328 个 Movement carrier 可用，3,451 个因 Movement 自身/Junction fallback 而 mask，Segment fallback 不再遮蔽 Movement。修正前 `_10/_11` 只保留为历史证据。该完成状态不等于 scorer 已训练或可生产发布。

`P05-Scheme-A-P1` 已于 2026-07-22 完成，正式判定 `P05_SCHEME_A_P1_MODEL_NO_GO`。Gate 0、RoadGraph 安全、确定性和资源均通过，三个 seed 的 Segment macro-F1 为 `1.0000/1.0000/0.9869`、Movement exact 均为 `1.0`；但 accepted coverage 仅 `0.3637/0.3589/0.3533`，seed 29/43 anomaly precision 低于 `0.80`。truth-exact 执行 coverage=`0.36933`，证明当前逐对象 label 在整图 carrier 来源组合上不闭合；不得通过错误替换 SWSD 提高覆盖率。下一阶段如启动，应先建立 JunctionUnit 级一致 carrier-set truth/candidate compatibility，不得直接扩大同一 scorer 或接生产。

`P05-Scheme-A-P2-P0` 已于 2026-07-22 完成并判定 **`P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO`**。P2-P0 未训练模型，Movement candidate/decision/evaluation 均为零；Segment 独立 Road carrier 与 JunctionUnit 共享 Node carrier 已完成 truth-free candidate 和 label-only Oracle 隔离。49 Case `LEGAL`、2 个冻结预期失败精确为 `EXPECTED_FAIL`、新增失败为零；joint truth exact coverage=`0.546542`，但当时受限 carrier bundle 的 `USE_RCSD` truth retention=`0.165753 < 0.50`，故该阶段禁止依靠 KEEP_SWSD 占比进入 P2-P1 训练。该历史指标的数据可达性含义以后续 Dataset-P0 为准。

`P05-Scheme-A-Dataset-P0` 已于 2026-07-22 完成并判定 **`P05_SCHEME_A_DATASET_P0_GO`**。本阶段不新增 Case，而是按正式模块职责重建训练合同：T01 是 SWSD Segment 冻结骨架与 fallback，不是 RCSD 真值或主 proposal；T07 固定 `DRIVEZONE_ONLY`；T03/T04/T05 为 label-only 中间监督；T06 Step3 Road/Node 为最终主目标；T09 仅作下游验证，T11 只有经 T05/T06 重跑形成完整 lineage 后才能成为修正标签，T10 负责数据组织与 split。正式 Run A/B 覆盖 741 sample、520 artifact、11,856 task target、51 Case 和 8,863 Segment；2,190/2,190 `USE_RCSD` Segment 的正确 Road 均由非 T01 truth-free candidate 覆盖，可用 Segment Road、T06 final Road `23,224/23,224`、final Node `27,553/27,553` 与联合 exact 均为 `1.0`，49 `LEGAL` + 2 `EXPECTED_FAIL` 保持不变。由此将历史 P2-P0 的 `0.165753` 重解释为受限 carrier bundle 的联合安全保留能力，而不是现有训练数据或正确 RCSD carrier 缺失；Dataset-P0 只放行离线训练数据与候选可达性，不自动授权 scorer、在线 proposal 或生产接入。

`P05-Scheme-A-P2-P1` 已于2026-07-23完成并判定 **`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`**。本阶段按已批准口径把P1 Segment Road、P1 truth-free T01/proposal Node lineage与PTO全量`FINAL_NODE` payload重组为Road endpoint/JunctionUnit条件化carrier；PTO Oracle不作Node标签，共享冲突执行Junction fallback。正式dataset覆盖51 Case、8,863 Segment、28,240 Node group和77,964条truth-free兼容边，Segment/Node reachability及compatibility Oracle均为100%。三seed的JunctionUnit Node exact=`0.9963/0.9966/0.9981`、ECE均小于`0.002`，且每seed保持49 `LEGAL` + 2 `EXPECTED_FAIL`；但错误自动接受=`17/9/17`，总体coverage=`0.3102/0.3502/0.5150`，`USE_RCSD` coverage=`0.0999/0.0027/0.2658`，anomaly precision=`0.3460/0.2851/0.3936`，seed43 Segment macro-F1=`0.8190`。双跑确定性、GIS/CRS和资源门通过。当前只允许保留离线评分、review和异常研究证据，不允许自动替换SWSD、在线proposal或生产接入。

`P05-Scheme-A-P2-P2-P1` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P2_P1_MODEL_NO_GO`**。独立 Segment safety head 严格冻结 P2-P1 candidate/base scorer，只拥有接受或回退权；3 safety seeds × 5 Case folds 的错误接受/总体 coverage/`USE_RCSD` coverage 为 `5/0.374817/0.431714`、`0/0.069841/0.066911`、`4/0.296288/0.380843`。零错误 seed 只能保留约 7%，较高覆盖 seed 又接受稳定 false-use，故不得自动替换 SWSD。40 Review 自动发布为零；每 seed 的 Node 条件化闭包和 RoadGraph 均保持 49 `LEGAL` + 2 `EXPECTED_FAIL`，effective requirement conflict/mismatch 和新增失败为零。当前只放行离线排序/review研究，后续若继续必须新增 truth-free 业务证据或更强预训练表征，不得在本次 held-out Case 上继续调阈值重报 GO。

`P05-Scheme-A-P2-P2-P2-P0` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`**。本阶段对 51 Case、8,863 Segment 冻结 202 维 truth-free evidence，完整覆盖 9 个一致错误 proposal 与 40 Review；T03/T04/T05/T06 输入、truth/ID/绝对坐标泄漏均为零。线性 probe 仍放过 2 个错误；浅层 MLP 虽在全局达到 accepted wrong=`0`、Review auto=`0`、coverage=`0.548686`、`USE_RCSD` coverage=`0.755729`，但 unsafe recall=`0.994191` 且没有 held-out fold 同时通过全部零错误/recall/coverage 门。两种 probe 的 Node 条件化和整图仍为 49 `LEGAL` + 2 `EXPECTED_FAIL`，冲突、错配和新增失败为零；正式双跑内容一致。当前不得继续用同一证据扩模型、加 epoch 或调阈值重报 GO；自动发布研究只有在新增推理期信息源或独立预训练表征并重新冻结验证集后才能另行启动，任何 label-only 字段提升必须先二次确认。

`P05-Scheme-A-P2-P2-P2-P1` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`**。本阶段未训练模型，对 P2-P2-P2-P0 的 9 个一致错误、浅层 MLP 残留 13 个 unsafe accepted 和 40 Review 形成 62 个无重复审计对象。40 Review 均由现有 T01 `access_valid=false` 硬门直接解释；剩余 22 个对象的直接原因是 16 个 truth-conditioned Junction fallback、5 个 T06 carrier Road 缺失和 1 个 T06 `MIXED_CARRIER`，均只存在于 label-only T06/联合真值层。完全不可观测对象为 0，但新增且已获准的直接推理证据也为 0；truth-free joint fallback 信号 precision 仅约 `20.83%~29.81%`，不得作为 Junction fallback 业务事实。下一阶段必须先决定保持强制 fallback/Review，或另行证明并授权一个在 T06 之前独立生成的等价事实来源。

`P05-Scheme-A-P2-P2-P2-P2` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`**。本阶段不训练、不调阈值，只把旧 unsafe 指标拆为 carrier safety 与 clue visibility：浅层 MLP 全局 carrier wrong accepted=`0`、carrier safety recall=`1.0`、clue miss=`13`、clue recall=`0.994189`；13 个残留对象均为正确保留 SWSD 后漏报异常，不是错误 Road 发布。但 cross-case 仍仅 `2/5` fold 通过，覆盖率不稳定，因此现有模型不得自动发布。22 个重点对象正确候选均存在，形成 `16 Junction一致性依赖 + 5 KEEP/Review候选缺USE + 1 MIXED候选评分错误`；26 个初始 Node payload 冲突与 57 个 Junction fallback Segment 完全确定性复现。允许的下一技术路线是分层 carrier scorer、T03/T04 节点证据辅助目标、独立 clue head 与通用 Junction 一致性闭包；T03/T04/T05/T06 当前仍为 label-only 监督，不得直接作为推理规则。

`P05-Scheme-A-P2-P3-P0` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`**。本阶段按已授权分层路线训练 2.818M 参数模型，使用 carrier candidate/correctness、独立 RealityChangeClue 和 T03/T04/T05 train-only auxiliary heads，再经通用 Node compatibility/Junction consistency decoder 物化整图。三个 seed 的 RoadGraph 均为 49 `LEGAL` + 2 `EXPECTED_FAIL`，Node/Junction conflict、mismatch、额外 repair 与骨架 mutation 均为零，说明整图安全生成方案已经走通；但 carrier 仍出现 `1/1/0` 个错误自动接受，fold 2 三 seed 的总体/USE coverage 稳定低于 `0.30/0.33`，clue recall=`0.9844/0.9852/0.9987` 且 13 clue-only 只捕获 `9/8/12`。seed 317 虽零错误但 clue precision 仅 `0.3502`，自动化率崩塌。T03–T06 终态字段仍未进入推理；当前模型不得自动替换 SWSD、在线接入或生产发布，也不得在已见 held-out 上继续调参后重报 GO。

`P05-Scheme-A-P2-P3-P1` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`**。本阶段没有训练或调阈值，而是对稳定 false-use、fold 2 全量 Segment、13 个 clue-only 对象和 `E:\TestData\POC_Data` 验证库存做可复现审计。稳定 false-use 及 8 个 clue-only 的直接事实是 label-only Junction fallback，另 5 个 clue-only 是 T06 final Road 缺失；现有 T01、T07 Step1/Step2、truth-free proposal、compatibility/Junction closure 和 202 维结构证据均已使用，但没有新增可在 T06 最终结果前独立生成的直接事实。fold 2 有 `1,795/3,037` 个 expected baseline failure，使 frozen overall coverage `>=0.50` 在该分母上数学不可达；eligible-only coverage 虽约 `0.71`，`USE_RCSD` 仍约 `0.32`。现有 51 个端到端 Case 已全部用于 OOF，批准排除 Case 不得复用，其余本地包不具备独立冻结 RoadGraph 真值。该结论表示当前证据和验证条件不足以重启模型，不表示神经网络整体不适用；后续必须先单独确认 coverage 分母口径，并建设新增推理证据或独立冻结验证合同。

`P05-Scheme-A-Dataset-P1` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_DATASET_P1_GO`**。用户确认的正式标签范围为：`T10` 全 Case可靠，`T10-Error/T10-Error-2` 仅 `scope.swsd_segment_id` 对应目标或其可证明后继可靠，其它包内 Segment只能作上下文。45 个启用包全部映射成功：41 个按 direct ID，4 个按冻结 Road 集合的无遗漏、无重复精确分区映射为 3/4/7/13 个当前 T01 Segment；5 个 direct ID 的 Road 清单漂移只作 lineage 审计，不改变同 ID 业务身份。8,863 个当前 Segment被唯一拆成 6,275 个标签对象与 2,588 个纯上下文对象，后者 label/loss/metric leakage=0。两个 `EXPECTED_FAIL` 继续进入 Case 安全、fallback 与 clue 合同，但失败只作用于各自 `failure_group_ids`，不得把全 Case Segment覆盖为拒绝。旧 8,863 标签分母下的 scorer 指标与 P2-P3-P1 stable-wrong/fold2 coverage-ceiling 解释均须重算；旧工件、冻结骨架、candidate 可达性和 49+2 图合法性证据不删除。本阶段未训练模型，下一步只有另行授权后才能在 Dataset-P1 上重建 dataset/scorer。

`P05-Scheme-A-P2-P3-P2` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`**。该阶段不换模型、不增加推理证据，只用 Dataset-P1 的6,275个可靠对象从头重训同一2.818M级分层scorer；2,588个context-only对象监督/阈值/指标均为0，并在整图中固定回退SWSD。三seed accepted wrong=`1/13/0`、Review auto=`0/12/0`、总体safe coverage=`0.3540/0.5495/0.1506`、`USE_RCSD` coverage=`0.6339/0.7037/0.2757`，没有seed满足逐fold零错误和双50%覆盖；clue precision与recall也无法同时稳定过门。错误集中为一个可靠target Segment在两个seed被`KEEP_SWSD→USE_RCSD`，以及seed313对12个`ADVANCE_RIGHT` Review错误自动接受。确定性fallback、通用Node/Junction closure和RoadGraph每seed均保持49 `LEGAL`+2 `EXPECTED_FAIL`，context auto accept、Case非目标级联、冲突、错配、repair和骨架mutation均为0；正式双跑signature一致。由此排除“旧错误上下文标签是唯一原因”，剩余瓶颈属于当前scorer/可用推理表征的跨Case安全泛化；不得挑选seed317的零错误结果、在当前held-out上继续调阈值或进入自动发布。

`P05-Scheme-A-P2-P3-P3` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED`**。40个冻结`ADVANCE_RIGHT access_valid=false`与40个eligible Review精确一一对应，硬门重放后Review auto=`0/0/0`、accepted wrong=`1/1/0`，49 `LEGAL`+2 `EXPECTED_FAIL`及context/局部失败/Node/Junction安全合同不变。剩余false-use对象三个seed均稳定选择`USE_RCSD`，score margin=`13.58/12.87/15.99`；三个held-out训练域的60个最近邻全部为`USE_RCSD`真值，当前202维T01/T07/候选表征未提供支持正确`KEEP_SWSD`泛化的区分结构。下一阶段只能先引入并冻结T06前的新推理表征，再决定是否训练新scorer；不得把T06终态提升为输入、从单Case固化业务规则或继续调当前模型。

`P05-Scheme-A-P2-P3-P4` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_NO_RESIDUAL_REPRESENTATION_REQUIRED`**。本阶段发现旧P2-P1先使用全部8,863个Scheme-A Segment标签计算Node/Junction闭包、之后才应用Dataset-P1范围，导致context-only Segment的carrier来源冲突错误级联到可靠target。正式顺序现固定为Dataset-P1 scope、2,588 context安全`KEEP_SWSD`、Node/Junction闭包；初始冲突/闭包Segment变为`10/21`，最终28,240个Node真值无冲突。旧/新Segment真值变化`436=435 context+1 eligible`，唯一eligible变化就是P2-P3-P3残余对象，由错误`KEEP_SWSD`恢复为`USE_RCSD`。既有三seed决策在修正真值下accepted wrong和Review auto均为0，故“必须为该残余对象建设新表征”失效；历史工件不删除。模型仍因safe coverage与clue门跨seed/fold不稳定而NO-GO，只有另行授权后才能按修正真值重训/复验。

`P05-Scheme-A-P2-P3-P5` 已于 2026-07-23 完成并判定 **`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`**。本阶段复用P4修正后的6,275个eligible Segment与28,240个Node真值，从头重训同一2.818M级分层网络；2,588个context-only对象监督/阈值/指标均为0，40个`ADVANCE_RIGHT access_valid=false`继续由独立硬门回退。经P6双层审计，P5的final publication wrong/Review auto=`0/0`，但scorer decision wrong accepted=`1/1/1`、carrier safety recall=`0.975610/0.975610/0.976744`；final safe coverage=`0.4290/0.5498/0.1374`，scorer safe coverage=`0.6524/0.7952/0.3469`。clue recall/precision/macro-F1分别为`0.9805/0.6614/0.8512`、`0.8831/0.9985/0.9596`、`0.9960/0.3605/0.5751`，没有seed通过完整clue门。每seedRoadGraph均为49 `LEGAL`+2 `EXPECTED_FAIL`且无冲突、错配、repair或骨架mutation。P5 `MODEL_NO_GO`不变，不得自动替换SWSD、挑seed或在当前held-out上调阈值重报GO。

`P05-Scheme-A-P2-P3-P6` 已于 2026-07-24 完成并判定 **`P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED`**。本阶段只读关联P5 decision/evaluation/score/effective与202维evidence，未训练或调阈值。每seed 6,275 eligible全部闭合；safe coverage分母按合同排除40 Review，为6,235。两个`EXPECTED_FAIL` Case在scorer层保持2个局部failure group，在final publication层原子阻断1,954个eligible对象。三seed稳定wrong均为`T10:609214532 / 505101583_506183080`；clue FP/FN=`747/29、2/174、2629/6`，稳定FP/FN=`2/4`。3,587条clue error没有相反标签exact evidence/group-signature collision，但稳定wrong的top-20训练邻域均为`USE_RCSD + clue=false`；fold clue threshold横跨`0.000296–0.998983`。因此下一阶段必须同时建设T06前truth-free表征和独立clue校准合同，不能只调阈值或扩大同一模型。P6 GO仅放行技术归因，不放行模型、训练、生产或T01–T12改造。

`P05-Scheme-A-P2-P3-P7` 已于 2026-07-24 完成并判定
**`P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO`**。本阶段只读组合Movement-free
历史结构证据、Case内compatibility邻域和T01平移/旋转不变相对几何；历史202维
工件不改写，14个实际非零Movement命名维及28个派生邻域维被明确排除，最终表征为
602维。来源、hash、CRS、6,275对象覆盖、inner/outer Case隔离、双跑确定性和资源门
全部通过，但稳定wrong的top-20仍为`20/20 USE_RCSD + clue=false`，三个seed也都
不存在同时满足clue recall=`1.0`、precision`>=0.80`、macro-F1`>=0.85`的单调
阈值。因此当前已授权T01/T07/proposal/compatibility来源不足以支持下一轮训练；
若继续，必须由用户另行决定T03/T04是否提升为推理来源，或授权建设新的确定性
T06前关系生成器。

`P05-Scheme-A-P2-P3-P8` 已于 2026-07-24 完成并判定
**`P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_CARRIER_ONLY_CLUE_SOURCE_BLOCKED`**。
T03/T04正式T05 handoff工件在51个eligible Case中通过hash/CRS/时点审计；6,275个
Segment只按Case-local T01 `junc_nodes`关联，其中504个有适用来源、192个多来源，
无来源仅表达`NOT_APPLICABLE`。稳定carrier wrong具有2个held-out-fold之外的
`KEEP_SWSD + clue=true`同类T04关系状态且无`USE_RCSD`同类证据，故仅carrier字段
promotion值得二次评审；6个稳定Clue错误仅覆盖1个，Clue来源继续阻断。T03/T04当前
`label-only`角色、T01–T12实现、训练和生产边界均未改变。

P9已按批准合同完成并判定
`P05_SCHEME_A_P2_P3_P9_PROMOTION_MODEL_NO_GO`。602维Control和carrier-only
source residual adapter完成3 seeds × 5 Case folds；504个适用对象的pooled
macro-F1/KEEP recall在Control与Treatment均为`0.9986769935/0.99609375`，稳定
错误对象在三seed仍选`USE_RCSD`且各有1个scorer层错误自动接受。5,771个无来源对象
score/decision差异为0，Clue source消费与Clue概率差异为0；每seed RoadGraph仍为
49 `LEGAL`+2 `EXPECTED_FAIL`。正式双跑signature一致且资源通过。历史Dataset-P0/P8
角色与字段白名单不改写，但P9 adapter不得进入自动替换或生产链；后续训练需另行授权。

P10随后按用户逐对象人工裁决对冻结P9输出进行集合真值复算，不重训、不改阈值。
对象级1.0真值覆盖T10 Case级0.7；业务合法结果与优选结果分开验收，未裁决对象仍保持
candidate-exact。五个对象中，两个“RCSD数据缺失但道路结构不冲突”对象明确为
`KEEP_SWSD + RealityChangeClue=false`。复算后504个source-applicable对象的
Control/Treatment合法准确率均为1.0，三seed scorer wrong accepted、Review auto
publish和Junction fallback violation均为0，carrier safety recall均为1.0，故P9
“稳定错误”归因已失效。但两臂优选命中率仍同为`0.9980158730`且无严格增益，P9
promotion继续NO-GO；Clue pooled precision/recall/macro-F1=
`0.583278/0.987197/0.804359`、FP/FN=`3140/57`，三seed稳定Clue漏报已归零，但冻结
coverage门及稳定Clue误报仍未关闭，完整模型继续阻断。正式结论为
`P05_SCHEME_A_P2_P3_P10_TRUTH_REBASELINE_GO_P9_PROMOTION_NO_GAIN`。

P05 以 T06 Step3 F-RCSD Road/Node 为唯一最终目标语义，研究从基础地图证据直接生成 RoadGraph。M0 已建立本地训练真值、标签 lineage、业务 ID grouped split 和统一评估器。R2 已完成三道门禁：Road/Node edit-set、SPLIT 与精确 T05 pointer 在 51 Case 上可表达率均为 `100%`，oracle 逐 Case语义与有向拓扑完全重建；40.19M 条件生成模型也通过 small-batch 可学习性门禁。但 grouped 5-fold OOF 的 Road F1=`0`、Node F1≈`0.0001`、T05 pointer accuracy=`0`，且 51/51 Case 存在拓扑 hard failure，故当前 ordinal slot-query 基础模型正式 **NO-GO**。训练损失继续下降而 held-out 指标未改善，失败归因是模型缺少输出对象与输入 Road/Node 的 object-conditioned matching/cross-attention，不能外推为“神经网络整体不适用”。

P05-PTO-P0 已完成。P0 不训练第二个 decoder，而是复用 R2 edit/pointer：登记 commit 且输入 lineage 完整的 T03/T04/T05/T06 策略从 raw/T01 生成有限高召回候选，但不决定最终结果；登记的历史 T10 replay 可保留 T07 可选辅助 stage，T07 只进入 replay lineage/成本，不形成独立候选或选择规则。51 Case 的 candidate reachability 与 Oracle-cost solve 均通过：冻结 Road/Node/T05 Node/SPLIT/pointer 计数全部可达，51/51 Case OPTIMAL/gap=0 且 Road/Node/属性/有向拓扑精确一致，truth leakage、业务后处理修图、relaxation 和 silent fix 均为零。候选 build+solve 成本满足预算，但含策略 replay 的 P95=`284.809s`、max=`684.902s`，全链性能门失败。因此允许 PTO-P1 先使用冻结/缓存候选执行 object-conditioned learned scoring/grouped 5-fold；当前在线全链和生产接入仍为 NO-GO，必须另行实现轻量或增量 proposal generator 并重过性能门。

`P05-JSG-PTO-P0` 已完成。冻结 51 Case 中实际出现的 Junction、StandardSegment、Junction—Segment relation、PhysicalMovement、SegmentConnector 与 Terminal 均达到 100% 可表达，loop 为真实零实例；51/51 canonical 往返与 Road/Node compiler 精确通过，hard failure=0，两轮 semantic/compiled/provenance signature 一致。7 个多贯穿冲突全部保持 `REVIEW`、自动选择为零，121 个缺失 final carrier 的 StandardSegment 与 26 个 access 不唯一的 Connector 未被补造。P0 不训练模型、不生成推理候选、不接入生产主链、不修改 T01-T09 接口；其 GO 只覆盖本体、label-only Oracle 和 compiler 合同。

用户于 2026-07-22 明确授权并已完成 `P05-JSG-PTO-P1`，M1/M2R/R2/RoadGraph PTO-P0 只保留为历史实验结论。P1 从推理时可用、零 truth 的冻结证据生成 Junction/Segment/Relation/Movement/Connector/Review 与 carrier 候选；候选 manifest/hash 完成后才允许 P0/R2 truth 生成 label-only Oracle cost。正式双跑为 51 Case、417,493 candidates、72,318 groups；PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0，RoadGraph 51/51 精确，hard failure 和事后修复均为零，确定性签名一致。P1 不训练 scorer、不接生产、不修改 T01-T09。

`P05-JSG-PTO-P3` 已于 2026-07-22 完成。正式 51 Case、3 seeds × 5 folds 结果中，object-conditioned scorer 的 JSG Top-1/macro 达 `0.9390~0.9395 / 0.8471~0.8817`，但 Connector 仅 `0.4283~0.5992`，Review/Unknown recall/precision 仅 `0.4389~0.4952 / 0.6886~0.7828`，正式判定 `P3_MODEL_NO_GO`。PTO/compiler/RoadGraph safety gate 仍为 51/51 精确通过。该结论只作为历史模型证据，不能定义当前方案 A 的 carrier 目标、门禁或生产边界。

## 4. 模块责任边界

| 模块 | 详细责任 |
|---|---|
| T00 | 支撑工具集合，历史一次性预处理能力主要已被 T08 吸收，保留追溯入口。 |
| T01 | SWSD Segment 构建，输出 T06 替换和 T09 通行建模基础。 |
| T02 | Retired 历史模块，能力已由 T07 / T03 / T04 / T08 承接。 |
| T03 | 常规交叉 / T 型虚拟锚定，输出 T05 可消费 relation evidence。 |
| T04 | 分歧 / 合流 / 复杂路口虚拟锚定，输出 accepted/rejected、surface、relation evidence 和审计。 |
| T05 | 统一融合 T07/T03/T04 关系，发布 SWSD-RCSD 语义路口主表和 copy-on-write RCSD 输出。 |
| T06 | 在 relation 基础上做 Segment 替换可行性审查、执行和拓扑审计。 |
| T07 | 已有路口面 1:1 锚定与可选兼容 relation 补锚，不处理 Segment，不生成虚拟路口面。 |
| T08 | SWSD / RCSD 预处理、质检和修复前置模块。 |
| T09 | F-RCSD 上的通行规则恢复。 |
| T10 | 端到端编排与 Case 证据组织，不替代 T01-T09 / T11 算法。 |
| T11 | T06 后、T09 前的人工 relation 修复候选审计；不回写业务产物。 |
| T12 | 原始 1V1 F-RCSD 质量审计；验证 SWSD 可达性等价假设，以 raw endpoint topology 为主、portal-constrained semantic carrier 与 T07 Road-surface portal carrier 为误报排除门禁，结合标准路口和锚点可信度自动发布高置信问题与排除证据，人工 review 仅作可选 QA 覆盖，不执行修复。 |
| P01 | 异构路口通行能力 POC，不作为 T09 正式替代契约。 |
| P02 | 武汉局部人工锚定实验编排与证据收口；复用 T08/T01/T05/T06，不替代这些模块的正式业务契约。 |
| P05 | 方案 A 神经网络 F-RCSD Road/Node carrier 决策 POC；冻结 T01 Junction—Segment/PhysicalMovement 骨架，模型只作 carrier 评分/选择和异常线索。Dataset-P0 数据/候选可达性GO；P4已修正scope-first Segment/Node真值；P5同架构重训实现三seed零错误自动接受与49+2整图安全，但safe coverage和RealityChangeClue仍未逐seed/逐fold通过，正式`P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO`。当前无可发布神经模型，不替代T01-T09。 |

## 5. 质量与验收口径

项目级质量要求关注跨模块结果是否可解释、可追溯、可验证：

- CRS 和坐标变换必须明确记录，不允许用隐式默认 CRS 掩盖问题。
- 拓扑一致性不能靠 silent fix，必须输出审计和失败原因。
- 几何结果必须能解释其业务语义，例如路口面、Segment corridor、surface closure 和 carrier 保留边界。
- 每个模块 handoff 必须能定位输入、输出、参数、运行环境、summary 和 audit。
- T06 / T10 等端到端结果不能只证明代码路径可运行，还要能证明具体 run root 的完成态和关键输出存在。

## 6. 非目标

- 项目级需求不展开模块内部完整参数表、字段值域和实现步骤。
- T10 不修复上游算法，不替代 T01-T09 / T11 / T12 的模块契约。
- T06 不用 problem registry 或 surface fallback 绕过 replacement plan。
- P01 不替代 T09 正式通行规则恢复契约。
- P02 不伪造缺失的 T07/T03/T04 道路面锚定成果，不把局部实验结论直接提升为全量口径。
- P05 不把空间接近、规则重跑或单次模型结果提升为人工真值或正式业务规则。
- T02 不继续承接新业务需求。

## 7. 改进路线

1. Relation 质量产品化：T07/T03/T04/T05 继续稳定输出成功、失败、fallback、review-only、blocked 和 upstream-needed 状态，减少 T06 重复解释上游问题。
2. T06 问题回流闭环：problem registry 中可自动消费的问题进入 T10 feedback 和 T05，可疑或超边界问题进入人工复核或上游任务。
3. F-RCSD 自动 QA：T06 Step3 结果继续由 T06 正式审计；原始 1V1 F-RCSD 由 T12 检查 road-node integrity、raw endpoint 方向可达性、受信 portal-constrained semantic carrier、标准路口 portal、局部替代路径和 DriveZone 证据，并自动发布高置信问题；人工 review 仅作可选 QA 覆盖。
4. 通行能力增强：T09 后续引入 RCSD Laneinfo 和轨迹证据；P01 Arm / RoadNextRoad 经验可作为正式化前参考。
5. 文档层级收敛：根目录只保留简洁入口和简版需求，详细需求、架构策略、治理盘点和模块契约下沉到对应目录。
