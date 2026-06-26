# 03 方案策略

本文件是 T06 的架构设计 / 需求具体实现策略说明。它解释 T06 如何从 T01 SWSD Segment 与 T05 SWSD-RCSD relation 构建 RCSDSegment、判定 replaceable，并输出 F-RCSD Road / Node。稳定输入输出、入口和参数以 `INTERFACE_CONTRACT.md` 为准；数据对象、证据、质量和风险分别见 `02-data-and-domain-model.md`、`04-evidence-and-audit.md`、`05-quality-requirements.md` 与 `06-risks-and-technical-debt.md`。

## 1. 总体策略

T06 采用三步链路：

1. Step1 从 T01 `segment.gpkg` 识别具备融合资格的 SWSD Segment。
2. Step2 用 T05 relation 和 copy-on-write RCSD 网络构建 buffer-based RCSDSegment，并输出最终 `replaceable` 集合、统一 `t06_segment_replacement_plan.*` 与 `t06_segment_replacement_problem_registry.*`。
3. Step3 优先消费 Step2 replacement plan，把标准 Segment、特殊路口组内部对象与 path-corridor group replacement 统一执行到 F-RCSD Road / Node；旧 replaceable + group/special audit 只作为兼容 fallback。

模块的核心边界是“只替换已被 Step2 证明并发布到 replacement plan 的对象”。失败 Segment 可以输出诊断、候选修复证据和上游责任归因；pair anchor 锚定错误在满足受限高置信安全门槛时，可在 T06 当前 Segment 内构造 effective relation 并重新执行 Step2 硬审计，但不得静默覆盖或回写 T05 relation。

近期端到端 Case 修复后，T06 的业务定位需要明确为“替换质量承接层”。T05 提供的路口 1:1 relation 是 Segment 替换的前提，但真实 RCSD 数据存在端点缺失、方向不一致、路口内部短连接、提前右转、road-only split 和 surface 证据不完整等问题。T06 因此必须在不扩大 Step3 替换白名单的前提下，通过 Step2 诊断和 Step3 后处理提高可替换率与最终 F-RCSD 可用性。

## 2. Step1：SWSD Segment 融合资格识别

### 2.1 业务目的

从 T01 Segment 中识别哪些 Segment 具备进入 RCSD 匹配和替换预检的基础条件。

### 2.2 输入与前提

- T01 `segment.gpkg`，依赖 `pair_nodes / junc_nodes / roads / sgrade` 等字段。
- T04 downstream `final_swsd_nodes`，用于读取 `has_evd / is_anchor / kind_2`；这是 T06 Step1 漏斗分母的节点状态来源。

### 2.3 落地策略

- 对每个 Segment 解析 `pair_nodes + junc_nodes`，形成语义路口集合。
- `pair_nodes` 必须解析出两个不同的 SWSD 语义路口；同一语义路口内部 self-pair fallback 进入 Step1 rejected 审计，不进入 Step2 final fusion units。
- `junc_nodes.kind_2 in {1,4096,8192}` 不参与 Step1 `has_evd / is_anchor` 判定，但仍保留为后续 optional junc 审计对象。
- eligibility 集合内所有语义路口 `has_evd=yes` 时进入候选集。
- 在候选集中，所有 eligibility 语义路口 `is_anchor in {yes, fail4_fallback}` 时进入 final fusion units。

### 2.4 输出与审计

- `t06_swsd_segment_candidates.*`
- `t06_swsd_segment_final_fusion_units.*`
- `t06_swsd_segment_rejected.*`
- `t06_step1_segment_stats.csv`
- `t06_step1_summary.json`

### 2.5 对错边界

- 对：`fail4_fallback` 视为可融合 anchor，豁免只作用于 junc eligibility 检查；self-pair fallback 只保留 Step1 审计，不参与 RCSD Segment 替换分母。
- 错：把 `junc_nodes` 当作 hard-stop，或把 `pair_nodes` 豁免掉。

## 3. Step2：Relation Mapping

### 3.1 业务目的

把 SWSD Segment 的 pair/junc 语义路口映射到 RCSD 语义路口，为 RCSDSegment 构建提供 required 与 optional 语义边界。

### 3.2 输入与前提

- Step1 final fusion units。
- T05 `intersection_match_all.geojson`。
- T05 `rcsdnode_out.gpkg`。

### 3.3 落地策略

- relation 只接受 `status=0` 且 `base_id>0`。
- `pair_nodes` 是 required semantic nodes，必须全部映射成功。
- 映射后 RCSD pair 两端归一到同一语义路口时，以 `rcsd_pair_nodes_not_distinct` 拒绝。
- `junc_nodes` 是 optional 内部通过 + 侧向阻断；映射成功进入 optional 审计，映射失败进入 dropped / lost attach 审计，不默认拖垮 pair-to-pair 主通道。
- RCSDNode 统一使用 `id / mainnodeid / subnodeid` 归一到 canonical semantic node key。

### 3.4 输出与审计

- relation mapping 审计字段写入 Step2 candidates / rejected / summary。

### 3.5 对错边界

- 对：pair relation 缺失是硬失败，junc relation 缺失是 optional 审计。
- 错：用失败 relation 或 `base_id=0` 建图。

## 4. Step2：Buffer-Based RCSDSegment 构建

### 4.1 业务目的

在 SWSD Segment 的空间范围内构建与 pair required semantic nodes 对应的 RCSD corridor，而不是简单拿 buffer 内全部连通分量。

### 4.2 输入与前提

- SWSD Segment 几何。
- `rcsdroad_out.gpkg / rcsdnode_out.gpkg`。
- pair required RCSD semantic nodes 和 optional junc seeds。

### 4.3 落地策略

- 使用 SWSD Segment 50m buffer 筛选 RCSDRoad / RCSDNode 候选。
- 构建 RCSD canonical semantic graph，避免 subnode 挂接导致同一语义路口被误判为断连。
- 在候选图中先识别 `formway & 128 != 0` 提前右转 road；只有满足二度链接保留或 required corridor 保留条件时才参与构建。
- 候选连通分量不能直接输出为 RCSDSegment，必须基于 pair required semantic nodes 构建最小 corridor 子图。
- 对额外 T05 mapped semantic nodes 与 optional junc 做 seed pruning：required corridor 内部保留为 `inner_nodes`，旁支或孤立挂接归为 `out_nodes` 并裁剪。
- 双向 Segment 需要保护 pair 两端正反向 directed corridor；单向 Segment 必须由 SWSDRoad directed graph 推导 source/target 后构建同向 RCSD corridor。
- 高等级 Segment 的 50m 失败若属于裁剪窗口不足，且 T05 原始 pair relation 完整、全图拓扑证据支持，可在原始 pair 不变的前提下执行受限重审；single 采用 RCSD graph-first 纵向联通并要求经过 50m buffer core，dual 优先采用 adaptive buffer 并要求双向可达；当 buffer-only probe 给出非人工复核高置信候选 pair 集合时，可遍历候选 pair，但只有恰好一个候选通过正式双向硬审计才消费候选 pair，必要时可用 dual graph-first 双向联通，且不得跨越额外 mapped semantic nodes。

### 4.4 输出与审计

- `t06_rcsd_buffer_segments.*`
- `t06_rcsd_buffer_segment_rejected.*`
- `t06_rcsd_segment_candidates.*`
- `t06_rcsd_segment_rejected.*`

### 4.5 对错边界

- 对：retained graph 是 pair required semantic nodes 之间的最小可解释 corridor。
- 错：把 buffer 连通分量、pair 字段顺序或 `segmentid A_B` 顺序当作业务方向。

## 5. Step2：硬审计与 Replaceable 判定

### 5.1 业务目的

将 buffer 成功构建的候选压缩为真正可替换的 RCSDSegment。

### 5.2 落地策略

- retained graph 的叶子端点只能是 pair 对应 RCSD semantic nodes。
- retained graph 中不得存在 pair required corridor 内部解释节点以外的额外 mapped semantic nodes。
- `swsd_directionality=dual` 要求 RCSD pair 两端双向可达。
- `swsd_directionality=single` 要求按推导 source/target 存在同向 RCSD corridor。
- retained RCSDRoad 必须满足逐 road buffer overlap ratio；整体覆盖不一致比例和绝对长度不能超限。
- 宽 50m buffer 覆盖通过后，还必须执行窄通道视觉连续性复核。该复核用于识别“RCSD 在宽 buffer 内，但主线目视连续性断裂或替换结果明显偏离 SWSD 主通道”的场景；失败时不得进入 adaptive buffer 或 graph-first 重审。
- 高等级受限重审通过的 Segment 仍必须通过单向 / 双向可达、叶子端点、额外 mapped semantic node、几何参考覆盖与特殊组门控；single graph-first 不允许只因全图有向 path 存在直接进入 replaceable，必须经过 50m buffer core 并满足纵向门槛。
- `kind_2=64 / 128` 的特殊路口按关联 Segment 组执行全组门控：关联 Segment 必须全部可替换，否则该组全部移出 replaceable。

### 5.3 输出与审计

- `t06_rcsd_segment_replaceable.*`
- `t06_special_junction_group_audit.*`
- `t06_step2_summary.json`
- `t06_segment_replacement_plan.*`
- `t06_segment_replacement_problem_registry.*`

### 5.4 对错边界

- 对：`replaceable` 是经过全部硬审计与特殊组门控后的最终白名单。
- 对：Step2 closeout 必须把普通 replaceable、passed 特殊路口组内部对象和 passed path-corridor group replacement 统一发布到 replacement plan，并把已覆盖、已解决、需上游迭代或已接受不可替换的问题写入 problem registry。
- 错：把 candidates 当 replaceable，或特殊组部分通过就局部替换。

## 6. Step2 失败诊断与修复候选

### 6.1 业务目的

对失败 Segment 提供可解释诊断和人工复核材料，帮助定位上游 relation 或拓扑问题。

### 6.2 落地策略

- Step2 失败后执行 buffer-only probe，不依赖 T05 relation 绑定，只基于 SWSD Segment buffer 与 RCSD 图结构输出诊断。
- `t06_rcsd_repair_candidates.*` 可以记录原始 pair、候选 pair、错误 SWSD 端点、endpoint cluster、bridge road 和长度。
- repair candidate 默认只用于人工质检和问题定位；仅当候选为非 ambiguous、非人工复核的 `high_confidence_pair_anchor_candidate`，且只补缺失 pair 端点、已有端点与候选端点存在短距离 endpoint cluster 证据，或已有端点中一端或两端被诊断为 `candidate_anchor_mismatch` 且候选 pair 通过正式 extractor 时，才可驱动当前 Segment 的一次自动重试。普通缺失端点补全必须保留 T05 已知端点所在 SWSD pair 侧，只补失败侧；buffer-only 候选不包含该已知端点时，不得作为侧保持补全自动通过。高等级 single 若已知端点本身也被 `candidate_anchor_mismatch` 判错，且诊断同时覆盖已知端错误与另一端缺失，可在高置信安全门槛和 Step2 硬审计通过后整体采用候选 pair。probe 低分但 `corridor_found`、连通/方向/shape 证据充分的缺端补全，只有在 Step2 原硬审计全部通过后才能作为 `side_preserving_missing_pair_anchor_completion` 自动进入 replaceable。单向 `multi_anchor_ambiguous` 只允许在高置信 `ambiguous_corridor` 下遍历全部候选 pair 的 as-is / reversed 正式试算，并要求 oriented RCSD pair 与 SWSD Segment 轴向端点侧位一致，且恰好一个 oriented candidate 通过时自动替换；多个候选通过或无候选通过均保持人工复核。
- 高等级 single 受限重审不是 repair candidate 路径，不读取候选 pair 替换已有端点；single 通过后以 `single_graph_first_longitudinal_retry` 写入 failure business audit，并在 candidates / replaceable / buffer segments 中以 `single_graph_first_longitudinal_retry:<原失败原因>` 记录来源。高等级 dual 默认复用 T05 原始 pair 做 `adaptive_high_grade_dual_buffer_retry`；只有 buffer-only probe 已给出非人工复核高置信候选 pair，且候选 pair 重新经过正式双向 extractor / adaptive buffer / dual graph-first 硬审计时，dual 才可在当前 Segment 内消费该候选 pair；若 union path 穿过额外 mapped semantic nodes，必须保持 rejected 并交由上游分组/锚定处理。

### 6.3 输出与审计

- `t06_rcsd_buffer_only_probe.*`
- `t06_rcsd_repair_candidates.*`
- `t06_rcsd_segment_failure_business_audit.*`

### 6.4 对错边界

- 对：诊断材料指向可能的上游问题。
- 错：未满足高置信安全门槛时，用 probe 或 repair candidate 覆盖 T05 relation 并继续生成 replaceable；或把 T06 effective relation 回写为 T05 relation；或把 adaptive buffer 用作绕过硬审计的放行开关。

## 7. Step2 Closeout：Replacement Plan 与 Problem Registry

### 7.1 业务目的

把 Step2 的标准 replaceable、特殊路口组补充实体、path-corridor group replacement 与失败诊断统一收口，形成 Step3 可执行计划和上游回流问题清单。

### 7.2 落地策略

- `t06_segment_replacement_plan.*` 是 Step3 的正式执行边界，`execution_scope` 至少覆盖 `standard_segment / special_junction_group_internal / path_corridor_group`。
- path-corridor group replacement 只有在 group probe 已经证明闭包内 Segment、RCSD path 与特殊组覆盖均满足当前规则时，才能进入 ready plan；Step3 不再重新判断其可替换性。
- `t06_segment_replacement_problem_registry.*` 必须登记 `covered_by_replacement_plan / resolved_in_step2_plan / accepted_non_replaceable / requires_upstream_iteration / requires_upstream_side_group_or_rcsd_directionality_review` 等状态。
- `accepted_non_replaceable` 用于 T06 已确认无法形成可替换 RCSDSegment 但不应回流上游重跑的场景，例如 T05 relation 将 SWSD pair 两端归到同一 RCSD 语义路口。
- `requires_upstream_side_group_or_rcsd_directionality_review` 用于双向 Segment 只能证明单向 RCSD 图通路的情况，先回流评估侧聚合或 RCSD 数据方向性，不由 Step3 兜底替换。

### 7.3 对错边界

- 对：Step2 把替换执行、已解决问题和待上游迭代问题都显式落表，T10/T05 可据此组织反馈。
- 错：让 Step3 读取多个诊断文件自行扩大替换范围，或把 `accepted_non_replaceable` 继续推给上游重跑。

## 8. Step3：Segment Replacement

### 8.1 业务目的

把 Step2 replacement plan 中的 ready action 替换为 RCSD 承载，并输出融合后的 F-RCSD Road / Node。

### 8.2 输入与前提

- Step2 `t06_segment_replacement_plan.*`，优先读取 JSON 以保留无 geometry 的特殊路口组 plan 行。
- Step2 `t06_rcsd_segment_replaceable.*`，仅作为无 replacement plan 的旧结果兼容输入。
- T01 SWSD `segment / roads / nodes`。
- T05 Phase2 `rcsdroad_out / rcsdnode_out`。
- 旧结果兼容路径可读 Step2 `t06_special_junction_group_audit.*` 与 `t06_segment_group_replacement_audit.*` 中 passed 行，但 summary 必须记录 legacy source。

### 8.3 落地策略

- Step3 优先消费 replacement plan，只执行 `plan_status=ready` 的 action，不处理 rejected，也不重新搜索 RCSD Segment。
- 以 `swsd_segment_id` 建立替换单元，记录 SWSD `pair_nodes / junc_nodes / roads` 与 retained RCSD road/node。
- `execution_scope=standard_segment` 执行普通 Segment 替换；`execution_scope=special_junction_group_internal` 引入特殊路口组内部 RCSD Road/Node；`execution_scope=path_corridor_group` 按 Step2 已验证的 group path corridor 合并生成组级原子替换单元。
- `path_corridor_group` 的 source carrier 使用 Step2 group probe / replacement plan 发布的完整 group `rcsd_road_ids`；非 source member 可继续按成员几何做作用域过滤，避免远距离 RCSD Road 误挂到成员 relation。
- Step3 不重新判定 Step2 ready group plan 的可替换性。若后续 topology / coverage 兜底仍发现问题，必须按整组 SWSD corridor 与整组 RCSD road union 聚合审计；失败时整组失败或整组回退，并写明 group 级原因，不能让 source carrier 失败而同组其它 member 成功替换。
- 删除被替换 SWSDRoad；若 Step1/Step2 replaceable 的 final `junc_nodes` 少于 T01 原始 `junc_nodes`，detached junc 触达的原 SWSDRoad 以 `source=2` 保留为局部 restriction carrier，并在 Segment relation 中记录 `replaced+retained_swsd`。
- Segment relation 中的 `frcsd_road_ids` 只表达正式 RCSD 替换道路。保留 SWSD carrier、SWSD 派生 topology supplement 和提前右转挂接补丁必须通过 `relation_status`、`retained_detached_swsd_road_ids`、风险标记和审计层表达，不能混入正式替换道路清单。
- SWSDNode 只删除被替换 SWSDRoad 的端点 Node，不删除整个 SWSD 语义路口组。
- 引入 Step2 retained RCSDRoad / RCSDNode；passed 特殊组内部 RCSDRoad / RCSDNode 作为组级补充加入。
- 所有 replaceable Segment 的 `pair_nodes + junc_nodes` 形成待重建语义路口集合 C。
- 若 C 原 main node 被删除，按原 main node、剩余 SWSD node 最小 id、加入 C 的 RCSD node 最小 id 的优先级重选 main node。
- C 内 Node 继承原 main node 的 `kind / grade / kind_2 / grade_2 / closed_con`。
- 对提前右转，Step3 可在不重判 Segment 可替换性的前提下执行挂接后处理：已选 RCSD 提前右转 corridor 可以吸附到保留 SWSD carrier；仅 SWSD 存在的提前右转 carrier 可在已选 RCSD Road 上复用或生成挂接节点；普通 RCSD road 挂在已选提前右转 road 中部时，可拆分该提前右转 road 并纳入同一 replacement unit。该后处理只补齐已选/已保留 carrier 的道路、节点和几何一致性。
- 调用方提供 T03/T04/T05/T07 surface 或 T04 audit 时，Step3 可执行 surface-assisted closure。该 closure 只在唯一候选、T04 未 reject、Patch 无冲突、距离条件可解释时补写节点 `mainnodeid` 或非 `retained_swsd` relation 的 node map；它不新增正式替换道路，不修改原始道路几何，也不把 rejected Segment 改判为 replaceable。
- 对 `junction_alignment_to_retained_swsd_exceeds_topology_gate` 阻断的 plan 行，Step3 wrapper 可用 surface 1:1 pass 或原始 pair endpoint 映射将该 gate 降级为人工审计风险并重跑替换；候选释放只引入 T05 有效语义路口关系可解释的多源节点分裂时，生成 `semantic_junction_group_id` 并把 topology hard fail 降级为 warn。其它新增 topology hard fail 必须回退对应 plan，相对传入 baseline 的新增 fail 必须在 summary 中暴露。
- T05 `intersection_match_all.geojson` 中 `status=0 / base_id>0` 的关系是 Step3 语义路口组证据；`many_target_to_one_base` 允许形成同一组。分歧、合流等工艺差异导致 SWSD/RCSD 节点距离较远时不设硬阈值，但必须在 F-RCSD node 和 semantic junction group 审计中表达风险。
- 对已满足 Step2 ready plan、锚定、连通、主干无争占和同源正式替换清单的 replacement unit，Step3 coverage 兜底若只发现端点缺口落在当前 unit 的 T05 junction anchor surface 内，应优先替换并追加人工审计风险，而不是把路口面内合理长度差异重新判为不可替换。该释放只扣除对应路口面内的 uncovered geometry，扣除后仍超阈值或出现 topology audit hard fail 时继续失败 / 回退。
- Step3 结束时必须输出拓扑连通审计，覆盖 final road-node integrity、正式替换 source 一致性、Segment 内连通、junction mapping 和挂接质量，确保 T09 消费的是可解释的 F-RCSD carrier。

### 8.4 输出与审计

- `t06_frcsd_road.*`
- `t06_frcsd_node.*`
- `t06_step3_semantic_junction_groups.*`
- `t06_step3_unreplaced_rcsd_roads.*`
- id collision audit、删除 / 引入 / main node 重建审计。
- `t06_step3_swsd_frcsd_segment_relation.*`，用于 T09 和 T10 理解每个 SWSD Segment 的 F-RCSD carrier。
- `t06_step3_topology_connectivity_audit.*`，用于批量检查最终拓扑连通与 source 边界。
- `t06_step3_surface_topology_audit.*` 与 summary，用于解释 surface-assisted closure 的使用和阻断。
- `t06_step3_surface_aware_plan_release_audit.json`，用于解释 retained-junction gate 条件释放、topology 回退和外部 baseline 新增 fail 对照。
- summary 必须记录 `replacement_plan_source`、输入 plan 行数、按 `execution_scope` 的执行计数、path-corridor group 计数、detached junc 保留计数、semantic junction group 计数和 `surface_aware_plan_release` 审计摘要。

### 8.5 对错边界

- 对：F-RCSD Road/Node 使用 `source=1` 表示 RCSD，`source=2` 表示 SWSD。
- 对：detached junc 的 `identity_retained_swsd` node map 只表达局部 SWSD carrier 原样保留，不表达 RCSD 锚定成功。
- 对：Step3 只执行 replacement plan 或 legacy fallback 产物已明确通过的对象，不用诊断文件补造新的替换对象。
- 对：surface、提前右转和 topology supplement 只补齐已选承载的可用性；retained-junction gate 释放只能把已存在 plan 的单一距离 gate 降级为风险项，不能扩大 Step2 可替换范围。
- 对：最终 relation、topology audit 和 surface audit 能解释正式替换道路、保留 SWSD carrier、节点闭合和挂接风险。
- 错：因 SWSD/RCSD 原始 id 冲突而重写 id；应保留原 id 并依赖 `source` 区分。
- 错：把保留 SWSD carrier、surface fallback 或提前右转补丁混入正式 RCSD 替换道路清单。
- 错：surface-aware gate 释放后只看候选 plan 成功，不看最终 topology hard fail 和外部 baseline 新增 fail。
- 错：用 surface evidence 绕过 T04 reject、Patch 冲突、多候选冲突或 Step2 replacement plan。

## 9. 端到端修复后的业务收口

近期端到端 Case 修复表明，T06 提高替换率的关键不是放松审计，而是把不同数据问题分流到正确位置：

- 上游 relation 问题：通过 buffer-only probe、repair candidates、failure business audit 和 problem registry 定位，满足高置信条件时只允许当前 Segment 内重试，不回写 T05 relation。
- RCSD 裁剪窗口问题：通过 high-grade graph-first / adaptive buffer 受限重审处理，仍需通过方向、连通、覆盖和特殊组硬审计。
- 路口组完整性问题：通过 special junction group gate 和 path-corridor group replacement 保证成组替换，不允许复杂路口局部破坏。
- SWSD/RCSD carrier 差异：通过 `replaced+retained_swsd`、topology supplement 和提前右转挂接表达混源边界，使 T09 仍能找到局部 restriction carrier。
- 节点闭合问题：通过 surface-assisted closure 和 selected replacement endpoint fallback 补齐可解释的 relation node map，但不新增替换道路。
- 最终质量问题：通过 topology connectivity audit、source consistency audit 和 T10 visual check summary 暴露给人工和批量 QA。

这一收口方式使 T06 既能提升真实数据替换成功率，又不会把上游锚定错误、RCSD 原始方向问题或 T04 reject 绕过成静默替换。

## 10. 证据包与本地 Case

- 文本证据包用于内外网回传 T06 运行审计结果，不登记为 repo 官方 CLI。
- 输入切片包用于按中心点和范围抽取局部 SWSD / RCSD / relation 数据，形成可复现本地测试用例。
- 解包 manifest 必须记录输入路径、文件大小、SHA256、参数、依赖完整性和 replay 脚本。
