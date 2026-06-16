# 04 Algorithm Strategy

## 分层

- `parsing.py`：字段解析与 ID 规范化。
- `io.py`：vector/table 读写、run root 与三格式输出。
- `schemas.py`：稳定字段、失败原因与 artifacts dataclass。
- `step1_identify_fusion_units.py`：Step1 eligibility。
- `relation_mapping.py`：T05 relation loader 与 pair/junc mapping 校验。
- `graph_builders.py`：RCSD semantic node canonicalizer 与 buffer graph edge dataclass。
- `buffer_only_probe.py`：Step2 失败后的 relation-independent RCSD corridor 诊断、候选 pair 打分与人工质检建议生成。
- `pair_anchor_auto_retry.py`：Step2 高置信 pair-anchor 自动重试准入与 effective relation 构造；只承接受限 pair anchor 兜底，不回写 T05 relation。
- `pair_anchor_formal_retry.py`：候选 pair 的 as-is / reversed 正式试算与唯一 outcome 判定；支持单候选 pair anchor mismatch、单向 `multi_anchor_ambiguous` 的受限消歧，以及双向高等级方向性失败时遍历 probe 候选 pair 但仅接受唯一正式成功。
- `pair_anchor_relation_retry.py`：relation mapping 失败与 buffer extraction 失败后的 formal retry 编排；统一调用正式试算、junc audit 与输出行 helper，不承接候选打分。
- `adaptive_buffer_retry.py`：高等级 single / dual Segment 的受限重审准入；single 只判断原始 pair relation 不变时是否允许进入 graph-first 重审，dual 可服务于原始 pair relation，或服务于已通过 buffer-only probe 高置信门槛并重新进入 formal retry 的候选 pair。
- `single_graph_connectivity_retry.py`：高等级单向 Segment 的 RCSD graph-first 纵向联通 helper，并承载高等级双向候选 pair 的 `dual_graph_first_bidirectional_retry`；single 只在全图有向 path 经过 50m buffer core 且长度/首尾/几何参考门槛通过时产出 RCSDSegment，dual 要求正反 path 均存在、均经过 50m core、均满足长度比，且 union path 不穿过额外 mapped semantic nodes。
- `step2_extract_rcsd_segments.py`：Step2 orchestration。
- `group_replacement_audit.py`：Step2 rejected Segment 的 group replacement 准入审计；重建 RCSD graph path、外部 accepted anchor 与 SWSD Segment 闭包状态，并对 path-corridor group union 执行正式 extractor probe；不直接写 replaceable。
- `replacement_plan.py`：Step2 closeout 统一发布 Step3 执行计划与问题回流注册表；把标准 replaceable、passed 特殊路口组、passed path-corridor group replacement 收敛为一个 plan。
- `step2_special_junctions.py`：Step2 特殊路口组门控、RCSD semantic/internal road coverage 与 graph edge 准备 helper。
- `buffer_segment_extraction.py`：Step2 buffer-based RCSDSegment 候选子图、提前右转二度链接保留 / required corridor 保留 / 排除、连通分量覆盖、最小 corridor 子图构建、裁剪与硬审计。
- `step3_group_replacement.py`：Step3 path-corridor group replacement 消费 helper；优先读取 replacement plan，合并重叠 group component，并生成 Segment assignment；旧 group audit 仅作为兼容 fallback。
- `step3_segment_replacement.py`：Step3 替换单元解析、SWSD road/node 删除集、detached junc 局部 SWSD carrier 保留、RCSD road/node 引入集、junction C 重建与 F-RCSD 输出。
- `runner.py`：组合 runner。
- `text_bundle.py`：非官方文本证据包压缩 / 解压 helper，复用内网运行脚本的输入参数形状，记录输入文件大小 / SHA256、运行参数、summary 与可复跑命令；同时支持中心点 + profile/radius 的输入切片包。

## 策略

- Step1 先解析 `pair_nodes / junc_nodes / roads`，排除 `pair_nodes` 两端相同的 self-pair fallback，再做 node eligibility。
- Step2 先 relation mapping，再使用 buffer-based 策略构建唯一 RCSD Segment 审查成果。
- buffer candidate graph 使用 RCSD semantic canonical key，避免 RCSDRoad 挂在 subnode 上时把同一语义路口误判为断连。
- seed pruning 的语义节点集合来自 T05 relation base nodes 与 `rcsdnode_out` 全局语义路口组，不只依赖当前 Segment 的 mapped nodes。
- pruning 先保护 pair required-to-required 必要通道；双向 SWSD 额外保护 pair 两端正反向 directed corridor；必要通道上的额外语义节点和 optional junc 输出为 `inner_nodes`，旁支语义节点和孤立 optional junc 输出为 `out_nodes` 并裁剪。
- pair required semantic nodes 必须落在同一候选连通分量内；不满足时输出 buffer rejected。
- 候选连通分量不直接作为正式 RCSDSegment；裁剪后必须基于 pair required semantic nodes 构建最小 corridor 子图，避免闭环与旁支被错误保留。
- 双向最小 corridor 的路径权重会惩罚明显短于 SWSD Segment 的 required-to-required connector，避免用路口内短连接替代完整方向 road。
- 双向 retained corridor 内部若存在 `formway & 1024 != 0` 的调头 road，且两端 node 均已在 retained corridor 内，则保留该调头 road。
- 裁剪后的 retained graph 必须只以 pair 对应 RCSD semantic nodes 为叶子端点；未被剪除的 junc 或其它节点成为叶子端点时输出 buffer rejected，已剪除的 optional junc 必须进入 dropped / lost attach 审计。
- 裁剪后的 retained RCSDRoad 逐条复核与 SWSD Segment buffer 的 overlap ratio；低于 `min_buffer_road_overlap_ratio` 的完整 Road 不允许进入 replaceable，以避免端点命中或极小相交把长 Road 错带入 Segment；retained RCSD 与 SWSD 的整体 50m buffer 覆盖不一致比例默认不得超过 `10%`，绝对长度默认不得超过 `20m`，任一超限即拒绝。
- 高等级 Segment 若 T05 原始 pair relation 已完整，且 50m 失败可被全图拓扑解释为裁剪窗口不足，允许受限重审。single 不消费 repair candidate、不整体放大候选 buffer，而是在全 RCSDRoad 有向图中联通两个 pair 路口，要求 path 经过 50m buffer core，并通过 path / SWSD 长度比例、首尾离开 50m core 的纵向长度与 75m/100m 几何参考覆盖门槛；dual 要求全图双向可达，buffer-only probe 非人工复核高置信时可遍历候选 pair 先尝试 `75m / 100m / 125m`，仍失败时可在正反 path 均经过 50m core、长度比通过且 union path 不穿过额外 mapped semantic nodes 时执行 dual graph-first；只有恰好一个候选 pair 通过正式硬审计时才消费该候选 pair；通过后记录 adaptive buffer / graph-first 审计字段。
- `t06_rcsd_segment_candidates` 是 buffer 成功构建的候选，`t06_rcsd_segment_replaceable` 是经过全部硬审计与特殊路口组门控后的最终可替换集合；不再执行旧 pair-to-pair BFS、主轴 / 粗长度趋势或唯一性筛选；`swsd_directionality=single` 先按 SWSDRoad `snodeid / enodeid / direction` 推导 pair source/target，再构建覆盖 pair required semantic nodes 的同向 RCSD corridor；`swsd_directionality=dual` 的 retained graph 需通过 RCSD direction 双向可达审计；`kind_2=64/128` 特殊路口按关联 Segment 全组通过后才允许进入 replaceable。
- `t06_rcsd_buffer_only_probe / t06_rcsd_repair_candidates / t06_rcsd_segment_failure_business_audit` 由 Step2 orchestration 在失败或 optional junc 自动提升时生成；probe 默认只做诊断和候选建议。pair 锚定疑似错误若满足非 ambiguous、非人工复核的高置信候选，且只补缺失 pair 端点、候选端点可被短距离联通 endpoint cluster 解释为同一复合路口，或已有端点中一端或两端被诊断为 `candidate_anchor_mismatch` 且候选 pair 通过正式 extractor，Step2 可在 T06 当前 Segment 内用候选 pair 构造 effective relation 并重新执行 buffer/direction 硬审计；普通缺失端点补全必须按 SWSD pair 失败侧重排候选，保留 T05 已知端点所在侧；当已知端点也被 `candidate_anchor_mismatch` 判错且诊断同时覆盖另一端缺失时，可在高置信安全门槛下整体采用候选 pair；若 probe 因候选组件旁枝低分，但 `corridor_found`、connectivity / directionality 满分、shape similarity 不低于 `0.95`，且重试通过全部硬审计，也可作为侧保持缺端补全进入 replaceable；通过后必须把原始 pair、候选 pair、错误 SWSD 端点、cluster nodes、bridge roads 与长度写入审计。
- `t06_segment_group_replacement_audit` 由 Step2 orchestration 在 replaceable/rejected 稳定后生成；它只消费当前 Step2 输入与 relation/RCSD 图，输出 group closure 与 formal probe 证据，不参与本轮 replaceable 决策。`group_probe_status=passed` 表示 path-corridor group union 已通过正式 extractor，随后由 `t06_segment_replacement_plan` 统一发布给 Step3；`group_probe_status=failed` 仍保留为上游锚定或 RCSD 数据问题。
- `t06_segment_replacement_plan` 是 Step2 -> Step3 的正式执行边界。Step3 不再直接把 group/special audit 解释为新增替换范围；存在 plan 时只按 plan 执行，旧 audit 消费保留为历史产物兼容。
- `t06_segment_replacement_problem_registry` 是 T06 向前置模块回流的诊断入口。它不改变本轮输出，只记录哪些 Segment 已被当前 plan 覆盖、哪些由 Step2 标准计划解决、哪些仍需 T01/T03/T04/T05/T08/T06 或数据裁剪审计继续迭代。
- 单向 `multi_anchor_ambiguous` 不直接采用 probe 候选；只有在 probe 为 `ambiguous_corridor` 且候选评分、几何重合、方向、连通、shape similarity 均达到高置信门槛后，才遍历全部 candidate pair 的 as-is / reversed 方向执行正式试算；oriented RCSD pair 必须与 SWSD Segment 轴向端点侧位一致，恰好一个 oriented candidate 通过正式硬审计才进入 replaceable。
- Step3 以 Step2 replacement plan 为基础替换白名单，不重新做 RCSD Segment 搜索或特殊组 / group probe 放行判定；存在 plan 时从 plan 中读取标准 Segment、path-corridor group 与特殊路口组内部对象，再按 Segment 聚合删除 / 引入集合。若标准 replaceable final `junc_nodes` 相对 T01 原始 `junc_nodes` 存在 detached junc，则保留其触达的原 SWSDRoad 作为 `source=2` 局部 carrier；最后按语义路口 C 聚合重建 mainnodeid 与继承属性，避免逐 Segment 覆盖同一 C 造成不一致。
- Step3 原始 id 冲突不重写、不拒绝，统一依赖 `source` 字段区分，并输出 id collision audit；新 main node 选择顺序为原 main node、剩余 SWSD node 最小 id、加入 C 的 RCSD node 最小 id。
