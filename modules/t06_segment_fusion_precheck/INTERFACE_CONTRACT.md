# T06 - INTERFACE_CONTRACT

## 定位

本文件是 `t06_segment_fusion_precheck` 的稳定接口契约。T06 当前覆盖 Segment 融合前置识别、RCSDSegment 构建审查与 Step3 融合输出扩展：

- Step1：识别可参与融合的 SWSD Segment 单元。
- Step2：基于 relation 与 buffer-based 策略构建 RCSDSegment 候选，并在特殊路口组门控后输出最终 `replaceable` 集合；对单 Segment 失败但具备成组替换可能的路径走廊输出 group replacement 审计证据，并统一发布 replacement plan 与 problem registry。
- Step3：优先消费 Step2 replacement plan，执行普通 Segment、特殊路口组内部实体与 path-corridor group replacement 的替换动作，输出融合后的 F-RCSD Road / Node，并重建涉及的语义路口关系。

Step1 / Step2 / Step3 代码均已提供模块内 callable runner；所有阶段均不得原地修改 T01 / T05 / Step2 输入成果。

## 1. 目标与范围

### 1.1 当前正式支持

- 消费 T01 `segment.gpkg` 与 final `nodes.gpkg`。
- 按 `pair_nodes + junc_nodes` 的语义路口 ID 集合判断 Segment 是否具备 EVD 与 anchor/fallback 基础。
- 对 `junc_nodes` 启用 `kind_2 in {1,4096,8192}` 豁免：命中 junc node 不参与 Step1 `has_evd / is_anchor` 判定；Step2 中所有 `junc_nodes` 均不作为 T05 relation 硬必检映射节点，该豁免不适用于 `pair_nodes`。对 `sgrade` 属于 `0-0* / 0-1*` 的高等级 Segment，`has_evd=yes` 且 `is_anchor` 明确非可用的 `pair_nodes.kind_2=2048`、`junc_nodes.kind_2 in {16,2048}` 可进入 Step2 probe 审查；对 `sgrade=0-2双` 且两个 `pair_nodes.kind_2` 均为 `2048` 的虚拟 T 型 pair，也可仅放行 pair 主通道进入 Step2 probe。上述规则不改变 anchor 事实、不回写 T05 relation、不改变 `junc_kind2_exempt_nodes`；`0-2双` 扩展不适用于 `0-2单`、混合 `kind_2` pair 或 junc 脱挂。高等级 Segment 中若非特殊路口 junc-only 节点拖垮 `has_evd / is_anchor`，Step1 可将其从 final fusion unit 的 `junc_nodes / semantic_node_set` 中脱挂，写入 `detached_junc_nodes / detached_junc_reasons` 后交给 Step2 只审 pair-to-pair 主通道；该脱挂不适用于 `pair_nodes`，也不适用于 `kind_2 in {64,128}` 特殊语义路口。
- 将 `is_anchor = fail4_fallback` 视为可融合 anchor。
- 消费 T05 Phase 2 `intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。
- 基于 SWSD Segment 50m buffer、RCSDRoad `intersects + 阈值`、RCSDNode `covers/within` 生成 buffer-based RCSDSegment 审查成果，作为 Step2 唯一正式构建策略。
- 构建 buffer 候选连通图前，使用 `formway` bit7/128 识别提前右转 road；若该 road 两端均与非提前右转候选 road 形成二度链接，或属于 required semantic nodes 之间的必要 corridor，则保留参与 Segment 构建并不计入提前右转排除审计，否则排除。
- `swsd_directionality=dual` 构建最小 corridor 时，极短 required-to-required connector 不得替代完整方向 road；RCSDRoad `formway & 1024 != 0` 的内部调头 road 若两端均属于 retained corridor node，必须保留在 RCSDSegment 中。
- retained RCSDSegment 中的每条 RCSDRoad 必须满足 `min_buffer_road_overlap_ratio` 覆盖阈值；若某条完整 RCSDRoad 仅因端点或极小相交进入候选、但最终 retained 几何大部分落在 SWSD Segment buffer 外，必须以 `retained_road_buffer_overlap_insufficient` 拒绝；retained RCSD 与 SWSD 的双向 50m buffer 覆盖不一致比例默认不得超过 `10%`，绝对长度默认不得超过 `20m`，任一超限即拒绝。50m 覆盖通过后，仍必须执行默认 15m 窄通道视觉连续性复核；若 SWSD 主线未被 retained RCSD 窄 buffer 覆盖或 retained RCSD 已明显脱离 SWSD 窄 buffer，任一 mismatch 比例超过 `10%` 或长度超过 `20m` 即拒绝。
- 不再执行旧 pair-to-pair BFS 路径搜索、主轴 / 粗长度趋势或唯一性筛选；buffer 候选连通分量必须先收缩为覆盖 pair required semantic nodes 的最小 corridor 子图；`swsd_directionality=single` 时，source/target 必须由 SWSDRoad `snodeid / enodeid / direction` 推导，并据此构建一条覆盖 pair required semantic nodes 的 RCSD 有向 corridor；`swsd_directionality=dual` 时执行 RCSD retained graph 双向可达硬审计。
- Step2 失败后输出 buffer-only probe、repair candidates 与 failure business audit；probe 不依赖 T05 relation 绑定，不静默覆盖 T05 relation。对 pair 锚定疑似错误，若 probe 输出非 ambiguous、非人工复核的 `high_confidence_pair_anchor_candidate`，且只补缺失 pair 端点、两端 pair relation 均缺失但 buffer probe 给出高置信 corridor、已有端点与候选端点存在短距离 endpoint cluster 证据，或已有端点中一端或两端被诊断为 `candidate_anchor_mismatch` 且候选 pair 通过正式 extractor，T06 可在当前 Segment 内用候选 pair 构造 effective relation 并执行一次 Step2 buffer/direction 硬审计重试；普通缺失 pair 端点补全必须保留 T05 已知端点对应的 SWSD pair 侧，只补失败侧，若 buffer-only 候选不包含该已知端点则不得作为 `side_preserving_missing_pair_anchor_completion` 自动补全；高等级 single 若缺失端点同时伴随已知端点 `candidate_anchor_mismatch`，必须由诊断明确覆盖两个 SWSD pair 端点、原始错误端包含一个已知 RCSD anchor 与一个缺失端，且候选 pair 满足高置信安全门槛后，才可整体使用候选 pair 重试；两端均缺失时仅允许使用非人工复核、连通与方向评分满分、shape similarity 不低于 `0.95` 的候选 pair，且重试通过后才进入 replaceable；当 probe 因候选组件旁枝导致综合分低于高置信阈值，但状态为 `corridor_found`、连通与方向评分满分、shape similarity 不低于 `0.95`，且侧保持补全后的 effective relation 通过 Step2 全部硬审计时，仍可作为 `side_preserving_missing_pair_anchor_completion` 自动补全；重试通过后才进入 replaceable，原始 pair、候选 pair、错误 SWSD 端点、候选端点、endpoint cluster 与 bridge 证据必须写入 repair candidates 与 failure business audit。其它 pair 锚定候选仍只供人工质检和上游修复。
- 对单向 `multi_anchor_ambiguous`，T06 仅在 relation mapping 失败原因为 `invalid_pair_relation_status / invalid_pair_base_id / missing_pair_relation`，probe 为 `ambiguous_corridor`，候选分数、几何重合、方向、连通与形态相似度均达到高置信门槛，oriented RCSD pair 与 SWSD Segment 轴向端点侧位一致，且所有候选 pair 的 as-is / reversed 正式试算中恰好一个 oriented candidate 通过 Step2 正式硬审计时，才可在当前 Segment 内使用该候选 relation 进入 replaceable；多个候选通过、无候选通过或任一硬审计失败必须保持 rejected / 人工复核，不回写 T05 relation。
- 对单向高等级 Segment，若高置信候选 pair 的正式方向试算已进入 `directionality_mismatch_fixable`，但正式 extractor 仍以 `rcsd_directed_path_missing` 失败，T06 可在不回写 T05 relation、不扩大整体 buffer 的前提下复用 single graph-first 纵向联通硬审计；只有恰好一个 oriented candidate 通过 50m core、长度比、端部外延、几何覆盖、方向与拓扑全部门槛时，才可输出 replaceable。
- 对 `swsd_sgrade` 属于 `0-0* / 0-1*` 的高等级 Segment，若 T05 原始 pair relation 已完整且 50m buffer 失败可由全图拓扑诊断解释为裁剪窗口不足，Step2 可在不回写 pair anchor 的前提下执行受限重审：单向 Segment 不再整体放大候选 buffer，而是按 SWSDRoad 推导出的 RCSD pair 方向在全 RCSDRoad 有向图中联通两个 pair 路口；该 path 必须经过 50m SWSD Segment buffer 内的 RCSD core，且 path / SWSD 长度比例、首尾离开 50m core 的纵向长度、75m/100m 几何参考覆盖均通过安全门槛，才可作为 `single_graph_first_longitudinal_retry` 进入 replaceable。双向 Segment 仍要求全图 required nodes 连通且全图双向可达；若 50m buffer-only probe 给出非人工复核的高置信候选 pair 集合，且失败主因为 `directionality_mismatch_fixable + rcsd_not_bidirectional_for_swsd_dual`，Step2 可遍历候选 pair 并在当前 Segment 内构造 effective relation 后执行 `75m / 100m / 125m` adaptive buffer 重审，仍失败时可执行 `dual_graph_first_bidirectional_retry`：只有恰好一个候选 pair 通过正式双向硬审计时才可替换；正反两个 RCSD 有向 path 均必须存在、均经过 50m core、均满足 path / SWSD 长度比例，且 union path 不得穿过额外 mapped semantic nodes；否则仅复用 T05 原始 pair relation 做几何覆盖失败、`required_semantic_nodes_not_connected_in_buffer` 或 `rcsd_not_bidirectional_for_swsd_dual` 的受限重审。重审通过仍必须满足方向、叶子端点、额外 mapped semantic node 与特殊组硬审计；通过后在 candidates / replaceable / failure business audit 中记录 `adaptive_buffer_status / adaptive_buffer_distance_m / adaptive_buffer_source_reason`。
- 对 final `nodes.gpkg.kind_2=64` 的环岛路口与 `kind_2=128` 的复杂路口执行特殊组门控：按 `pair_nodes + junc_nodes` 包含该语义路口识别关联 Segment；只有组内全部关联 Segment 均通过可替换判定时，组内 Segment 才允许进入 Step2 replaceable；否则组内所有原本可替换 Segment 均移出 replaceable，并以 `special_junction_group_not_fully_replaceable` 记录拒绝。
- Step3 优先消费 Step2 replacement plan，删除被替换 SWSDRoad 及其端点 SWSDNode，引入 plan 中发布的 retained RCSDRoad / RCSDNode、特殊路口组内部 Node/Road 与 path-corridor group RCSDRoad；输出 `source=1` 的 RCSD 数据与 `source=2` 的 SWSD 数据，并按 `pair_nodes + junc_nodes` 聚合重建语义路口 C。若旧运行缺少 replacement plan，Step3 可回退读取同目录特殊路口组审计和 group replacement 审计，且必须在 summary 中记录 legacy source。
- Step3 若发现 replaceable Segment 的 `swsd_junc_nodes` 少于 T01 原始 `junc_nodes`，说明上游已对部分 junc-only 节点执行主通道脱挂；detached junc 触达的原 SWSDRoad 必须以 `source=2` 保留为局部通行限制 carrier，并在 Segment relation 中输出 `relation_status=replaced+retained_swsd`、`detached_junc_nodes`、`retained_detached_swsd_road_ids` 与 detached junc identity node map。该规则不回写 T05 relation，也不宣称 detached junc 已完成 RCSD 锚定。

### 1.2 当前非目标

- 不修改 T01 主链、T05 主链或任何输入成果。
- 不对 Step2 rejected Segment 执行 pair anchor 自动替换或补救构建。
- 不新增 repo CLI、`tools`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- 除 `scripts/t06_run_innernet_precheck.py` 这个内网运行包装外，不新增其它 repo 级脚本入口。
- 不使用精细几何拟合指标作为核心硬门槛。

## 2. Inputs

### 2.1 Step1 Runner

```python
run_t06_step1_identify_fusion_units(
    *,
    swsd_segment_path,
    swsd_nodes_path,
    out_root,
    run_id=None,
    progress=False,
)
```

必选输入：

- `swsd_segment_path`：T01 `segment.gpkg`，依赖字段 `id / sgrade / pair_nodes / junc_nodes / roads / geometry`。
- `swsd_nodes_path`：T04 downstream `final_swsd_nodes`，依赖字段 `id / mainnodeid / has_evd / is_anchor / kind_2`。Step1 基于这里的 `is_anchor` 形成可进入 Step2 的漏斗分母；T05 `intersection_match_all` 只在 Step2 relation mapping 中消费。
- `out_root`：输出根目录。

### 2.2 Step2 Runner

```python
run_t06_step2_extract_rcsd_segments(
    *,
    swsd_fusion_units_path,
    swsd_segment_path,
    swsd_roads_path,
    swsd_nodes_path,
    intersection_match_path,
    rcsdroad_path,
    rcsdnode_path,
    out_root,
    run_id=None,
    max_main_axis_angle_diff_deg=60.0,
    min_coarse_length_ratio=0.4,
    max_coarse_length_ratio=2.5,
    buffer_distance_m=50.0,
    min_buffer_road_overlap_ratio=0.2,
    min_buffer_road_overlap_length_m=1.0,
    advance_right_formway_bit=128,
    progress=False,
)
```

必选输入：

- `swsd_fusion_units_path`：Step1 输出 `t06_swsd_segment_final_fusion_units.gpkg`。
- `swsd_segment_path`：T01 `segment.gpkg`。
- `swsd_roads_path`：SWSD road body；Step2 读取 `id / snodeid / enodeid / direction`，用于 `swsd_directionality=single` 的真实 source/target 推导。
- `swsd_nodes_path`：final `nodes.gpkg`；Step2 读取 `id / mainnodeid / subnodeid / kind_2`，用于把 SWSDRoad raw endpoint 投影到 Segment 两端语义节点。单向 Segment 的方向证据仍来自 Segment 内 SWSDRoad 的物理端点与 `direction`，不得把 `mainnodeid` 折叠结果当成唯一方向事实。
- `intersection_match_path`：T05 Phase 2 `intersection_match_all.geojson`。
- `rcsdroad_path`：T05 Phase 2 `rcsdroad_out.gpkg`。
- `rcsdnode_path`：T05 Phase 2 `rcsdnode_out.gpkg`，依赖字段 `id / mainnodeid / subnodeid` 用于把 RCSDRoad raw endpoint 归一到 RCSD 语义主节点。
- `out_root`：输出根目录。

### 2.3 关键输入语义

- `pair_nodes + junc_nodes` 按语义路口 ID 判定，不按物理 node 展开作为主判断。
- T06 替换单元要求 `pair_nodes` 表示两个不同 SWSD 语义路口；Step1 若发现 SWSD pair 两端相同，必须以 `swsd_pair_nodes_not_distinct` 写入 `t06_swsd_segment_rejected.*`，不得进入 final fusion units 和 Step2 替换分母；若外部直接把此类非法 fusion unit 传入 Step2，Step2 仍必须以同一 reason 防御性拒绝。
- Step1 解析 final `nodes.gpkg` 时，语义节点属性优先使用 `id` 精确匹配记录；只有不存在对应 `id` 记录时，才使用 `mainnodeid` 命中的组内记录作为 fallback。
- `kind_2 in {1,4096,8192}` 只对 `junc_nodes` 的 Step1 eligibility 生效：命中 junc node 从 Step1 `has_evd / is_anchor` 检查集合中移除，但仍保留在 `junc_nodes / semantic_node_set` 输出中；`pair_nodes` 命中这些 `kind_2` 也不豁免。对 `sgrade` 属于 `0-0* / 0-1*` 的高等级 Segment，`pair_nodes.kind_2=2048` 与 `junc_nodes.kind_2 in {16,2048}` 在 `has_evd=yes` 且 `is_anchor` 明确不可用时可作为 Step2 probe 放行节点；对 `sgrade=0-2双` 且两个 `pair_nodes.kind_2` 均为 `2048` 的虚拟 T 型 pair，仅 pair 主通道可同样进入 Step2 probe。该放行仍不是 anchor 豁免，Step2 中 `junc_nodes` 统一按 optional junc 审计处理，pair relation 缺失必须经 buffer-only probe 和正式硬审计重试证明后才可替换。
- `intersection_match_all.geojson` 中只有 `status = 0` 且 `base_id > 0` 的 relation 可用。
- `base_id` 必须是 RCSD 语义路口主 node id。
- Step2 构建 buffer candidate graph 时，必须先按 `rcsdnode_path` 的 `mainnodeid / subnodeid` 做语义节点归一化：`id` 若有有效 `mainnodeid` 则归一到 `mainnodeid`，`subnodeid` 列表中的物理节点也归一到所属 `mainnodeid`；pair required nodes、optional junc nodes 与 RCSDRoad `snodeid / enodeid` 必须使用同一 canonical key 判定连通与裁剪。
- T05 relation 映射后的 RCSD pair 两端归一到同一个 RCSD 语义路口时，不能构成可替换 RCSDSegment，必须以 `rcsd_pair_nodes_not_distinct` 拒绝。
- 全局 RCSD 语义路口组按有效 `mainnodeid` 聚合，组内所有 node 关联 road 都视为该语义路口的进入 / 退出道路；未映射到当前 Segment 的全局 RCSD 语义路口若进入候选图，必须参与 seed pruning，处于 required corridor 内部时作为 `inner_nodes` 保留审计，旁支节点归入 `out_nodes` 裁剪，不能当普通通过节点。
- SWSDRoad `direction` 用于 `swsd_directionality=single` 的 source/target 推导：`direction in {0,1,2}` 允许 `snodeid -> enodeid`，`direction in {0,1,3}` 允许 `enodeid -> snodeid`；若 pair 两端正反向都可达或都不可达，Step2 必须拒绝，不能用 `pair_nodes` 顺序或 `segmentid A_B` 顺序兜底。若单向 Segment 的物理端点位于 `kind_2 in {64,128}` 特殊语义路口的 subnode，初始 RCSD 有向 corridor 因方向不可追溯失败时，Step2 不得翻转 Segment 方向；仅当原方向本地 corridor 存在、且不满足 RCSDRoad 有向可达的局部边全部是 `formway & 128 != 0` 的短 connector / 提前右转 Road 时，才可作为 `semantic_endpoint_local_undirected_corridor_release` 受限释放，并记录人工审计来源。
- RCSDRoad `direction` 用于 retained graph 有向可达硬审计：`swsd_directionality=dual` 时 pair 两端必须正反向均可达；`swsd_directionality=single` 时必须存在一条按 SWSDRoad 推导方向、覆盖 pair required semantic nodes 的 pair 有向 corridor；component coverage、seed pruning、最小 corridor 子图与 leaf endpoint 仍按 canonical 无向图执行。
- `junc_nodes` 在 RCSD 抽取中是 optional 内部通过 + 侧向阻断，不是 hard-stop；retained RCSD graph 的叶子端点只能是 `pair_nodes` 对应的 RCSD semantic nodes。
- buffer-based RCSDSegment 审查中，required semantic nodes 只来自 `pair_nodes` relation；非豁免 `junc_nodes` 与 `junc_kind2_exempt_nodes` 若有有效 relation，作为 optional allowed semantic nodes 审计保留。junc relation 缺失、无效或被孤立剪除时必须输出 `optional_junc_nodes / dropped_junc_nodes / dropped_junc_relation_nodes / lost_attach_road_ids / promoted_attach_road_ids / blocked_attach_road_ids / attach_promotion_status / attach_promotion_reason / isolated_attach_loss_count / junc_attach_loss_reason`。
- 孤立 optional junc 被剪除后，Step2 可在 final replaceable 集合内执行全局无冲突 promotion：`lost_attach_road_ids` 中的 RCSDRoad 若未被其它 replaceable Segment 的主通道 `rcsd_road_ids` 占用，且未被多个 replaceable Segment 同时申请，可追加到当前 Segment 的最终 `rcsd_road_ids`；主通道审计字段 `retained_rcsd_road_ids` 不随 promotion 改写。
- 额外 T05 mapped semantic nodes 与 optional junc 必须按 seed-based pruning 判定为 `inner_nodes / out_nodes`；处于 pair required corridor 内部的 mapped semantic node 可作为 `inner_nodes` 保留审计；孤立 optional junc 可剪除并写入 dropped / lost attach 审计；若 retained graph 中仍存在非 inner 的额外 mapped semantic node，必须以 `unexpected_mapped_semantic_nodes` 拒绝。
- `formway` 为 bit mask；提前右转必须按 `formway & 128 != 0` 判断，不得写成 `formway == 128`。提前右转 road 在两端均与非提前右转候选 road 存在二度链接关系，或属于 required semantic nodes 之间的必要 corridor 时，保留参与构建。
- `formway & 1024 != 0` 表示 RCSD 调头口；该字段在 T06 中只用于双向 retained corridor 内部调头 road 保留，前提是该 road 两端均已属于 retained corridor node。
- Step2 路径权重不得只按 road 几何长度选择 pair required semantic node 之间的最短直连 edge；当 required-to-required edge 明显短于 SWSD Segment 时，必须加惩罚，避免把路口内短连接误当作完整反向 road。
- Step2 retained RCSDRoad 覆盖审计复用 `min_buffer_road_overlap_ratio`：候选选择可保留 `intersects + overlap length / endpoint` 的宽松入口，但最终 retained Road 若覆盖率低于该比例，不能进入 replaceable。retained RCSD 与 SWSD 的整体 50m buffer 覆盖审计使用比例 + 绝对长度双阈值，默认 `10% / 20m`，任一阈值超限即拒绝；50m 通过后还要使用默认 15m 窄通道复核 Segment 级几何连续性，阈值同为 `10% / 20m`。
- 窄通道连续性复核必须输出独立审计 issue：`swsd_visual_continuity_not_covered_by_retained_rcsd` 或 `retained_geometry_outside_swsd_visual_consistency_scope`。其中 `retained_geometry_outside_swsd_visual_consistency_scope` 仍表示 retained RCSD 几何明显脱离 SWSD 目视走廊，必须拒绝；`swsd_visual_continuity_not_covered_by_retained_rcsd` 只作为后期人工审计参考，不作为 Step2 正式拒绝门槛。该类 issue 不进入 high-grade adaptive buffer / graph-first retry。
- Step2 特殊组门控只使用已正式定义的 `kind_2=64/128`：`64` 表示环岛路口，`128` 表示复杂路口。关联 Segment 范围为 Step2 输入融合单元中 `pair_nodes + junc_nodes` 包含该语义路口的所有 Segment；切片证据包按切片内可见 Step2 输入执行并通过 `t06_special_junction_group_audit.*` 暴露组完整性。
- 特殊组门控的“组内已覆盖 Segment”由 Step2 当前轮正式可执行结果构成：普通 `replaceable` Segment 与已通过 `group_probe_status=passed`、`group_probe_repair_owner=T06_path_corridor_group_replacement` 的 path-corridor group 覆盖 Segment 都可满足组完整性；但 path-corridor group 覆盖 Segment 不进入普通 `replaceable` 白名单，仍必须由 Step2 replacement plan 以 `execution_scope=path_corridor_group` 发布后供 Step3 执行。
- 特殊组门控通过时，`t06_special_junction_group_audit.*` 必须输出该 SWSD 特殊路口映射到 RCSD 后的 `rcsd_junction_id`、RCSD 语义组内 Node，以及端点同归一到该 RCSD 语义组的内部 RCSDRoad，用于 Step3 统一替换审计。
- Step3 的基础替换输入必须来自 Step2 replacement plan；Step3 不重新搜索 RCSD Segment，也不把 rejected Segment 重新判定为可替换。对于 Step2 rejected 但已通过正式 group probe 的 Segment，只有被 Step2 发布为 `execution_scope=path_corridor_group` 且 `plan_status=ready` 的 plan action 才能驱动 Step3 成组替换。
- Step3 不重新判定特殊路口组或 path-corridor group 是否可替换；Step3 只执行 Step2 replacement plan 中 `execution_scope=special_junction_group_internal` 与 `execution_scope=path_corridor_group` 的 ready action，并将 `path_corridor_group` 作为组级原子替换 action 加入 F-RCSD。旧运行缺少 replacement plan 时，可兼容读取同目录 `t06_special_junction_group_audit.*` 与 `t06_segment_group_replacement_audit.*`，但 summary 必须记录 `replacement_plan_source=legacy_step2_artifacts`。
- Step3 对 `path_corridor_group` 的 source carrier 不得再按单 Segment 局部几何裁剪掉 Step2 group probe 已证明可用的 group RCSD corridor；source carrier 使用完整 group `rcsd_road_ids`，非 source member 可继续做 member-scope 过滤以避免远距离道路误挂。
- Step3 若保留 topology / coverage 兜底校验，必须按 `group_replacement_segment_ids` 聚合整组 SWSD corridor 与整组 RCSD road union 判断；不得用单个 source carrier 的局部 formal coverage 直接 hard fail。group 级 coverage 失败时，必须整组失败或整组回退，并通过 `unit_reason=group_formal_replacement_corridor_coverage_unavailable` 暴露审计原因，禁止出现 source carrier 失败、其它 group member 成功的部分替换。
- Step3 formal replacement corridor coverage / retained SWSD carrier coverage 只作为执行兜底，不得把已满足 Step2 replacement plan、端点锚定、方向连通、主干无争占、同 Segment 无多源混合的替换单元，仅因端点 coverage gap 位于当前 Segment 已锚定 T05 junction anchor surface 内而 hard fail。此类 gap 可从 hard coverage 缺口中扣除，并在 relation / unit 风险中追加 `formal_corridor_gap_inside_anchored_junction_surface`、`junction_surface_coverage_release`、`manual_review_required`；若扣除路口面后仍超阈值，仍按原 coverage gate 失败。
- Step3 清除 SWSDNode 的范围只限于被替换 SWSDRoad 的端点 Node，不清除 `pair_nodes / junc_nodes` 所在 SWSD 语义路口组的全部 Node。
- Step3 relation 中的 `frcsd_road_ids` 是正式 Segment 替换道路清单，必须保持同源 RCSD 数据；`retained_swsd` carrier、SWSD 派生 topology supplement 与提前右转挂接补丁只能作为保留/补拓扑材料或审计材料输出，不得混入正式替换道路清单。若 Segment 需要保留 SWSD carrier，必须通过 `relation_status=replaced+retained_swsd`、`retained_detached_swsd_road_ids` 与风险标记暴露，但 `frcsd_road_source_values / source_mix` 仍只描述正式替换清单。
- Step3 可在不重判 Segment 可替换性的前提下执行提前右转后处理：已选 RCSD 提右 corridor 若一端接已替换 RCSD、另一端贴近保留 SWSD carrier，应保留 RCSD 提右并将 RCSD 端点吸附到对应 SWSD 几何位置；仅 SWSD 存在提右 carrier 时，应按 T05 road-only split 语义在已选 RCSD Road 上复用或生成 RCSD 挂接节点；提右与其它挂接 road 共用 SWSD 主路节点时必须复用同一挂接位置；普通 RCSD road 挂接在已选 RCSD 提右 road 中点时，应拆分该提右 road 并把挂接 road 加入同一 replacement unit。该后处理只补齐已选/已保留 carrier 的道路、节点与几何一致性，不把 rejected Segment 改判为 replaceable。
- Step3 待重建语义路口 C 来自所有 replaceable Segment 的 `pair_nodes + junc_nodes`；C 内 Node 的 `kind / grade / kind_2 / grade_2 / closed_con` 继承原 main node 对应 Node 的属性。

## 3. Outputs

### 3.1 Step1 输出

目录：

```text
<out_root>/<run_id>/step1_identify_fusion_units/
```

文件：

- `t06_swsd_segment_candidates.gpkg/csv/json`
- `t06_swsd_segment_final_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_segment_stats.csv`
- `t06_step1_summary.json`

`t06_swsd_segment_candidates` 为通过 EVD 基础检查后的 SWSD Segment 候选集；`t06_swsd_segment_final_fusion_units` 为通过 anchor / fallback 检查后的 SWSD Segment 最终可融合集合。Step1 不再物理输出旧命名 `t06_swsd_segment_evd_candidates` 与 `t06_swsd_segment_fusion_units`，避免同一业务成果重复落盘。

`candidates / final_fusion_units` 稳定字段：

- `swsd_segment_id`
- `sgrade`
- `pair_nodes`
- `junc_nodes`
- `semantic_node_set`
- `roads`
- `pair_node_count`
- `junc_node_count`
- `junc_kind2_exempt_nodes`
- `detached_junc_nodes`
- `detached_junc_reasons`
- `has_fail4_fallback`
- `geometry`

`t06_step1_segment_stats.csv` 稳定字段：

- `sgrade`
- `total_segment_count`
- `evd_candidate_count`
- `final_fusion_unit_count`

其中首行为 `sgrade=__TOTAL__` 的总体统计，其余行按输入 Segment 中 `sgrade` 首次出现顺序输出分组统计。

`rejected` 稳定字段：

- `swsd_segment_id`
- `reject_stage`
- `reject_reason`
- `failed_node_ids`
- `failed_node_attrs`
- `junc_kind2_exempt_nodes`
- `pair_nodes`
- `junc_nodes`
- `sgrade`
- `geometry`

### 3.2 Step2 输出

目录：

```text
<out_root>/<run_id>/step2_extract_rcsd_segments/
```

文件：

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_segments.gpkg/csv/json`
- `t06_rcsd_buffer_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_only_probe.gpkg/csv/json`
- `t06_rcsd_repair_candidates.gpkg/csv/json`
- `t06_rcsd_segment_failure_business_audit.gpkg/csv/json`
- `t06_special_junction_group_audit.gpkg/csv/json`
- `t06_segment_group_replacement_audit.gpkg/csv/json`
- `t06_segment_replacement_plan.gpkg/csv/json`
- `t06_segment_replacement_problem_registry.gpkg/csv/json`
- `t06_step2_summary.json`

Rejected 的 `directionality_mismatch_fixable` 不得被解释为自动可修复结论。若 candidate pair 的 formal retry、adaptive buffer 或 graph-first 硬审计仍失败，`t06_rcsd_segment_failure_business_audit` 必须输出 `manual_review_required=True`、`repair_recommendation=upstream_anchor_or_segment_grouping_required`、`upstream_issue_owner=T03/T04/T05_or_T06_group_replacement`，表示需要上游锚定/虚拟路口归并复核，或后续 T06 multi-SWSD Segment group replacement，而不是当前单 Segment 静默替换。

`t06_segment_group_replacement_audit` 是 rejected Segment 的 group replacement 准入审计，不是 Step2 replaceable 白名单。它仅对疑似跨越外部 accepted SWSD anchor 的失败 Segment 重建 RCSD 图 path，输出外部 mapped SWSD target、关联 SWSD Segment 闭包，以及闭包内已 replaceable / rejected / outside Step1 的 carrier 状态；若存在 rejected 或 outside Step1 carrier，Step2 必须保持当前 Segment rejected。若 path-corridor group union 通过正式 extractor probe，必须输出 `group_probe_status=passed`、`group_probe_rcsd_road_ids`、`group_probe_buffer_distance_m`、`group_probe_repair_owner=T06_path_corridor_group_replacement` 与 `repair_recommendation=t06_group_replacement_candidate`，并由 Step2 replacement plan 发布为成组替换 action 后供 Step3 执行。若 group probe 失败且原因为 `rcsd_not_bidirectional_for_swsd_dual` 或 `rcsd_directed_path_missing`，`repair_recommendation` 必须输出 `upstream_anchor_or_rcsd_directionality_required`，表示需要继续复核上游锚定归并或 RCSD 原始方向性/连通性数据，不得由 Step3 兜底替换。

特殊路口组 gate 可读取同一轮 pre-gate `t06_segment_group_replacement_audit` 中已通过的 path-corridor group 覆盖 Segment 作为组完整性证据；该证据只防止特殊组误删已经由组级 action 覆盖的关联 Segment，不改变 `t06_rcsd_segment_replaceable` 的普通 Segment 边界。

`t06_segment_replacement_plan` 是 Step2 到 Step3 的正式执行边界。它把普通 replaceable Segment、特殊路口组内部 RCSD 实体、path-corridor group replacement 统一表达为 `plan_status=ready` 的 action；Step3 只能执行 plan 中的 RCSDRoad / RCSDNode / Segment group，不得重新补充 RCSD path 或重判可替换性。

`t06_segment_replacement_problem_registry` 是 Step2 到前置模块迭代的正式问题登记。它按 Segment 记录 `root_cause_category / upstream_issue_owner / recommended_module / feedback_action / replan_trigger / evidence_artifacts`，用于把当前无法替换的问题路由给 T01/T03/T04/T05/T07 后续迭代；已由 replacement plan 覆盖、Step2 内已解决、或已审计为合理不可替换的问题也必须登记为相应 `problem_status`，便于防回退审计。

`t06_rcsd_buffer_only_probe` 是 relation-independent 诊断输出；`t06_rcsd_repair_candidates` 输出候选 pair、候选评分和 pair 锚定错误位置。满足受限高置信安全门槛的 pair anchor 候选可驱动 T06 当前 Segment 的一次 effective relation 重试，包括缺失 pair 补全、两端 pair relation 均缺失但 buffer probe 高置信、endpoint cluster 解释的复合路口，以及通过正式 extractor 复核的 `candidate_anchor_mismatch`；但不得回写或静默修改 T05 relation。其它 repair candidate 不驱动 Step2 替换。高等级 single graph-first 受限重审只复用 T05 原始 pair；高等级 dual 若已由 buffer-only probe 给出非人工复核高置信候选 pair 集合，T06 可遍历这些候选 pair 并逐一执行正式双向 extractor / adaptive buffer / `dual_graph_first_bidirectional_retry` 硬审计；只有恰好一个候选 pair 通过时可消费该候选 pair，否则 dual 受限重审仍只复用 T05 原始 pair 或保持 rejected / 人工复核。`t06_rcsd_segment_failure_business_audit` 输出场景 A / 场景 B、B 类细分、自动提升、人工复核、pair anchor 错误定位、重审距离与上游责任归因。

`t06_step2_summary.json` 必须包含 RCSD 视角覆盖统计和业务归因统计：

- `rcsd_road_total_count`：输入 `rcsdroad_path` 中去重后的全量 RCSDRoad 数量。
- `rcsd_road_total_length_m`：输入 `rcsdroad_path` 中去重后 RCSDRoad 几何总长度，单位米。
- `replaceable_rcsd_road_unique_count`：最终可替换 Segment 引用的去重 RCSDRoad 数量。
- `replaceable_rcsd_road_unique_length_m`：最终可替换 Segment 引用的去重 RCSDRoad 几何总长度，单位米。
- `replaceable_rcsd_road_reference_count` / `replaceable_rcsd_road_reference_length_m`：按 Segment 引用次数累计的 RCSDRoad 数量 / 长度，用于审计同一 RCSDRoad 被多个可替换 Segment 共享的情况。
- `replaceable_rcsd_road_missing_count`：replaceable 输出中引用但未能在输入 `rcsdroad_path` 找到的 RCSDRoad 数量。
- `scenario_a_count / scenario_b_auto_lift_count / scenario_b_manual_review_count`：场景 A、场景 B 已由自动策略提升与人工复核数量；未通过 Step2 硬审计的 pair anchor 候选不计入自动替换。
- `pair_anchor_suspected_error_count / pair_anchor_error_located_count / junc_required_blocked_count / rcsdroad_quality_issue_count`：pair 锚定疑似错误、已定位 pair 锚定错误位置、junc required 拖垮与 RCSDRoad 质量问题数量。
- Failure business audit 的主因归类必须以 `reject_reason` 优先；当 `reject_reason = rcsd_not_bidirectional_for_swsd_dual` 时，归类为 `directionality_mismatch_fixable`，`dropped_junc_nodes` / `junc_attach_loss_reason` 仍作为附属审计字段保留，但不得覆盖双向方向性主因。单向 `rcsd_directed_path_missing` 若 buffer-only probe 已给出 `ambiguous_corridor` 或 `corridor_found_with_anchor_mismatch`，必须优先归类为 `multi_anchor_ambiguous` 或 `pair_anchor_mismatch`，回流 T03/T04/T05 锚定和虚拟路口聚合复核；只有 probe 未指向锚定/多候选问题时，才归类为 `directionality_mismatch_fixable`。
- `adaptive_high_grade_buffer_retry_count`：高等级 Segment 在不回写 T05 pair relation 的前提下，通过受限重审进入 replaceable 的总数；single 采用 graph-first 纵向联通，dual 优先采用 adaptive buffer，必要时采用 `dual_graph_first_bidirectional_retry`。
- `adaptive_high_grade_single_buffer_retry_count / adaptive_high_grade_dual_buffer_retry_count`：上述总数按 single / dual 的分组计数；single 计数保留历史字段名，实际 recommendation 为 `single_graph_first_longitudinal_retry`。
- `automatic_lift_estimated_replaceable_rate / manual_repair_theoretical_replaceable_upper_bound_rate`：自动提升后预计替换率与人工修复后理论上限。
- `replacement_plan_count / replacement_plan_ready_count / replacement_plan_scope_counts`：Step2 发布给 Step3 的替换计划总量、ready 计划总量与按 `execution_scope` 分组统计。
- `problem_registry_count / problem_registry_status_counts`：Step2 问题登记总量与按 `problem_status` 分组统计。
- `business_audit_stats`：按发生次数、去重 `swsd_segment_id`、唯一 SWSD semantic node 与唯一 RCSD semantic node 统计。

### 3.3 Step3 输出

Step3 输出目录：

```text
<out_root>/<run_id>/step3_segment_replacement/
```

文件：

- `t06_frcsd_road.gpkg/csv/json`
- `t06_frcsd_node.gpkg/csv/json`
- `t06_step3_replacement_units.gpkg/csv/json`
- `t06_step3_junction_rebuild_audit.gpkg/csv/json`
- `t06_step3_removed_swsd_roads.csv/json`
- `t06_step3_removed_swsd_nodes.csv/json`
- `t06_step3_added_rcsd_roads.csv/json`
- `t06_step3_added_rcsd_nodes.csv/json`
- `t06_step3_unreplaced_rcsd_roads.gpkg/csv/json`
- `t06_step3_id_collision_audit.gpkg/csv/json`
- `t06_step3_swsd_frcsd_segment_relation.gpkg/csv/json`
- `t06_step3_topology_connectivity_audit.gpkg/csv/json`
- `t06_step3_surface_topology_audit.gpkg/csv/json`（仅调用方提供 T03/T04/T05/T07 surface 或 T04 audit 时输出）
- `t06_step3_surface_topology_summary.json`（仅调用方提供 T03/T04/T05/T07 surface 或 T04 audit 时输出）
- `t06_step3_surface_aware_plan_release_audit.json`（仅调用方提供 T03/T04/T05/T07 surface 或 T04 audit 且存在 retained-junction gate 释放候选时输出）
- `t06_step3_summary.json`

F-RCSD Road / Node 必须包含 `source` 字段：RCSD 来源为 `1`，SWSD 来源为 `2`。
F-RCSD Road 中由 T06 替换发布的 RCSD Road 必须包含 `t06_swsd_segment_ids` 多值字段，记录该最终 Road 承载的 SWSD Segment id 集合；`path_corridor_group` 等组级替换允许一条 RCSD Road 同时承载多个 SWSD Segment，因此不得用单值 `segmentid` 覆盖该多值归属。
SWSD 与 RCSD 原始 `id` 冲突时保留原 id，依赖 `source` 区分，并写入 `t06_step3_id_collision_audit.*`。
`t06_step3_unreplaced_rcsd_roads` 是 RCSD 视角审计输出，保留原始 RCSDRoad 几何与属性，并增加 `replacement_status / audit_reason / source / length_m` 等字段，用于定位未进入最终替换结果的 RCSDRoad。
Step3 默认从 Step2 replaceable 同目录优先读取 `t06_segment_replacement_plan.json`，再兼容读取 `geojson/gpkg`；JSON 是完整执行计划主载体，必须保留无 geometry 的特殊路口组内部 plan 行。调用方也可以通过独立脚本参数显式指定特殊路口组审计文件或 group replacement 审计文件作为旧结果兼容输入。summary 必须记录 `step2_replacement_plan_path / input_replacement_plan_count / input_standard_replacement_plan_count / replacement_plan_source / special_junction_group_consumed_count / special_junction_added_rcsd_road_count / special_junction_added_rcsd_node_count`，以及 `group_replacement_audit_input_row_count / group_replacement_passed_row_count / group_replacement_plan_count / group_replacement_assignment_segment_count / group_replacement_created_unit_count / group_replacement_skipped_row_count`。当 surface-aware retained-junction gate 释放被触发时，summary 还必须记录 `surface_aware_plan_release`，包括释放数、回退数、内部 topology 新增 fail 数、外部 baseline 对照路径和相对外部 baseline 的新增 fail keys。
`t06_step3_swsd_frcsd_segment_relation` 是下游稳定关系索引，覆盖所有输入 SWSD Segment：

- `relation_status=replaced`：该 Segment 被 Step3 替换，`frcsd_road_ids` 指向 `source=1` 的 FRCSD Road。
- `relation_status=replaced+retained_swsd`：该 Segment 主通道被 Step3 替换，同时 detached junc 触达的局部 SWSDRoad 以 `source=2` 保留为 T09 通行限制 carrier。
- `relation_status=retained_swsd`：该 Segment 未被替换，`frcsd_road_ids` 指向 FRCSD 中保留的 `source=2` SWSD Road。
- `relation_status=failed`：该 Segment 关系解析失败或缺少必要承载，必须写明 `relation_reason`。

稳定字段至少包含：`swsd_segment_id / relation_status / relation_reason / swsd_pair_nodes / swsd_junc_nodes / junc_kind2_exempt_nodes / detached_junc_nodes / swsd_road_ids / removed_swsd_road_ids / retained_detached_swsd_road_ids / frcsd_road_ids / frcsd_road_source_values / rcsd_pair_nodes / rcsd_junc_nodes / junction_c_ids / group_replacement_plan_ids / group_replacement_source_segment_ids / group_replacement_segment_ids / swsd_to_frcsd_node_map / source_mix / risk_flags`。

### 3.4 文本证据包 helper 输出

T06 文本证据包 helper 不是新的业务阶段，也不登记为 repo 官方 CLI；它用于内外网结果回传、轻量审计取证与可复跑信息归档。

默认打包文件：

- `<run_root>/t06_segment_fusion_precheck_evidence_bundle.txt`
- `<run_root>/t06_segment_fusion_precheck_evidence_bundle_size_report.json`

文本证据包默认按 T01 输入证据包模式自动分片，单个 `.txt` 分片不得超过 `250KB`；可通过 `--max-text-size-bytes` 覆盖。第一片使用默认输出名或用户指定的 `--out-txt`，第二片起按 `<stem>.part_0002_of_000N.txt` 命名。解包 helper 接受任意一个分片路径，必须自动读取同目录其它分片并校验完整 payload SHA256。

包内稳定结构：

- `t06_evidence_manifest.json`
  - 记录 bundle 版本、source run root、输入清单、Step1 / Step2 summary、输出文件审计、checksum 与编码信息。
- `t06_evidence_size_report.json`
  - 记录 bundle 文本体量、压缩 payload 体量、逐文件 raw / compressed size、缺失的可选输出文件、`limit_bytes / within_limit / split_bundle` 分片审计信息。
- `audit/t06_input_manifest.json`
  - 记录与 `scripts/t06_run_innernet_precheck.py` 同形的输入参数、解析后的六个输入文件路径、运行参数、文件大小、SHA256 与 mtime。
- `audit/replay_t06_run_innernet_precheck.sh`
  - 记录使用同一输入参数复跑 T06 的命令。
- `run/<step_dir>/...`
  - 默认包含 Step1 / Step2 summary、JSON / CSV 审计输出。
  - 显式传入 `--include-output-vectors` 时额外包含 Step1 / Step2 GPKG 输出。
- `inputs/...`
  - 仅显式传入 `--include-input-files` 时写入六个原始输入文件副本。

输入切片包使用同一文本容器，但 selection 为 `t06-input-centered-spatial-slice`。稳定结构：

- `slice/swsd/segment.geojson`
- `slice/swsd/roads.geojson`
- `slice/swsd/nodes.geojson`
- `slice/t05_phase2/intersection_match_all.geojson`
- `slice/t05_phase2/rcsdroad_out.geojson`
- `slice/t05_phase2/rcsdnode_out.geojson`
- `slice/t06_input_slice_summary.json`

输入切片选择参数：

- `center_x / center_y`：EPSG:3857 中心点坐标。
- `profile_id`：默认 `XS`，支持 `XXXS / XXS / XS / S / M`。
- `size_m`：可选；显式提供时表示中心点正方形窗口边长。
- `radius_m`：可选；显式提供时覆盖 profile 半径；与 `size_m` 同时提供时 `radius_m` 优先。

默认 profile 半径：

- `XXXS = 250m`
- `XXS = 500m`
- `XS = 1000m`
- `S = 2000m`
- `M = 5000m`

切片依赖补齐规则：

- 选中与窗口相交的 SWSD Segment，并按 Segment 的 `roads / pair_nodes / junc_nodes` 补齐 SWSDRoad / SWSDNode。
- 对所有已选 SWSDRoad，补齐 `snodeid / enodeid` 端点 Node。
- 保留相关 T05 relation，并按成功 relation 的 `base_id` 补齐 mapped RCSD semantic nodes。
- 保留窗口内 RCSDRoad / RCSDNode，以及连接已选 RCSDNode 的 RCSDRoad。
- 对所有已选 RCSDRoad，补齐 `snodeid / enodeid` 端点 RCSDNode，避免切片包内 road endpoint 引用缺失。

输入切片选择规则：

- 用中心点与半径构建 EPSG:3857 方形窗口。
- 选中与窗口相交的 SWSD Segment。
- 根据选中 Segment 的 `roads / pair_nodes / junc_nodes` 补齐必要 SWSD roads / nodes。
- 同时保留窗口内上下文 SWSD roads / nodes。
- 保留选中语义节点相关 T05 relation，并按有效 relation 补齐 mapped RCSD semantic nodes。
- 保留窗口内 RCSDRoad / RCSDNode，以及连接 selected RCSD node 的 RCSDRoad。

`candidates` 稳定字段：

- `swsd_segment_id`
- `rcsd_candidate_id`
- `candidate_strategy`
- `candidate_status`
- `candidate_reason`
- `adaptive_buffer_status`
- `adaptive_buffer_distance_m`
- `adaptive_buffer_source_reason`
- `swsd_sgrade`
- `swsd_directionality`
- `swsd_pair_nodes`
- `directed_swsd_pair_nodes`
- `original_rcsd_pair_nodes`
- `rcsd_pair_nodes`
- `directed_rcsd_pair_nodes`
- `special_junction_group_ids`
- `special_junction_group_types`
- `special_junction_gate_status`
- `special_junction_blocking_group_ids`
- `swsd_junc_nodes`
- `junc_kind2_exempt_nodes`
- `rcsd_junc_nodes`
- `optional_junc_nodes`
- `optional_junc_rcsd_nodes`
- `dropped_junc_nodes`
- `dropped_junc_relation_nodes`
- `lost_attach_road_ids`
- `promoted_attach_road_ids`
- `blocked_attach_road_ids`
- `attach_promotion_status`
- `attach_promotion_reason`
- `isolated_attach_loss_count`
- `junc_attach_loss_reason`
- `required_rcsd_nodes`
- `optional_allowed_rcsd_nodes`
- `candidate_rcsd_road_ids`
- `candidate_rcsd_node_ids`
- `retained_rcsd_road_ids`
- `retained_node_ids`
- `inner_node_ids`
- `out_node_ids`
- `unexpected_endpoint_node_ids`
- `unexpected_mapped_semantic_node_ids`
- `excluded_advance_right_turn_road_ids`
- `selected_component_id`
- `candidate_road_count`
- `retained_road_count`
- `candidate_node_count`
- `retained_node_count`
- `geometry`

`candidates` 为 buffer 成功构建的 RCSDSegment 候选；`replaceable` 为经过全部硬审计与特殊路口组门控后的最终可替换集合。非特殊组场景下 `replaceable.rcsd_road_ids` 等于 buffer 构建出的最小 corridor `retained_rcsd_road_ids`；特殊组未全部可替换时，原本成功的候选仍可保留在 `candidates` 中，但必须从 `replaceable` 移除。`rejected` 输出保留 `swsd_sgrade / swsd_directionality / failed_pair_nodes / failed_junc_nodes / junc_kind2_exempt_nodes`，用于定位高等级、单向 Segment 的 pair relation 硬失败、optional junc relation 失败与豁免集合，同时记录 buffer 构建失败或特殊组门控失败 reason。

`t06_rcsd_buffer_segments` 稳定字段：

- `swsd_segment_id`
- `buffer_candidate_id`
- `buffer_status`
- `buffer_reason`
- `adaptive_buffer_status`
- `adaptive_buffer_distance_m`
- `adaptive_buffer_source_reason`
- `required_rcsd_nodes`
- `optional_allowed_rcsd_nodes`
- `directed_rcsd_pair_nodes`
- `retained_rcsd_road_ids`
- `candidate_rcsd_road_ids`
- `candidate_rcsd_node_ids`
- `excluded_advance_right_turn_road_ids`
- `retained_node_ids`
- `inner_node_ids`
- `out_node_ids`
- `unexpected_endpoint_node_ids`
- `unexpected_mapped_semantic_node_ids`
- `selected_component_id`
- `candidate_road_count`
- `retained_road_count`
- `candidate_node_count`
- `retained_node_count`
- `geometry`

`t06_rcsd_buffer_segment_rejected` 稳定字段：

- `swsd_segment_id`
- `reject_stage`
- `reject_reason`
- `required_rcsd_nodes`
- `optional_allowed_rcsd_nodes`
- `directed_rcsd_pair_nodes`
- `missing_required_node_ids`
- `retained_rcsd_road_ids`
- `candidate_rcsd_road_ids`
- `candidate_rcsd_node_ids`
- `excluded_advance_right_turn_road_ids`
- `retained_node_ids`
- `inner_node_ids`
- `out_node_ids`
- `unexpected_endpoint_node_ids`
- `unexpected_mapped_semantic_node_ids`
- `selected_component_id`
- `candidate_road_count`
- `retained_road_count`
- `candidate_node_count`
- `retained_node_count`

`t06_special_junction_group_audit` 稳定字段：

- `special_junction_id`
- `special_junction_type`
- `gate_status`
- `relation_status`
- `rcsd_junction_id`
- `associated_segment_ids`
- `associated_segment_count`
- `replaceable_segment_ids`
- `replaceable_segment_count`
- `missing_replaceable_segment_ids`
- `removed_replaceable_segment_ids`
- `rcsd_junction_node_ids`
- `rcsd_junction_road_ids`
- `notes`

`t06_segment_group_replacement_audit` 稳定字段：

- `swsd_segment_id`
- `audit_status`
- `corridor_audit_status`
- `source_reject_reason`
- `failure_business_category`
- `swsd_sgrade`
- `swsd_directionality`
- `swsd_pair_nodes`
- `swsd_junc_nodes`
- `rcsd_pair_nodes`
- `path_direction_count`
- `path_rcsd_road_ids`
- `path_rcsd_node_ids`
- `unexpected_mapped_rcsd_node_ids`
- `unexpected_mapped_swsd_target_ids`
- `unexpected_mapped_swsd_target_count`
- `group_segment_ids`
- `group_segment_count`
- `replaceable_group_segment_ids`
- `rejected_group_segment_ids`
- `outside_step1_group_segment_ids`
- `blocked_group_segment_ids`
- `blocker_reasons`
- `path_corridor_group_segment_ids`
- `path_corridor_group_segment_count`
- `path_corridor_blocked_segment_ids`
- `path_corridor_blocker_reasons`
- `side_incident_group_segment_ids`
- `repair_recommendation`
- `notes`

其中 `audit_status` 保持 incident-closure 口径，覆盖外部 accepted anchor 的所有关联 SWSD Segment；`corridor_audit_status` 仅统计与 RCSD path 几何走廊重叠的 carrier，用于区分主线 corridor blocker 与旁支 incident blocker。两个状态均为审计证据，不得直接解释为 `t06_rcsd_segment_replaceable` 白名单。

`t06_segment_replacement_plan` 稳定字段：

- `replacement_plan_id`
- `swsd_segment_id`
- `plan_status`
- `execution_action`
- `execution_scope`
- `plan_owner`
- `upstream_owner`
- `source_artifact`
- `source_reason`
- `replacement_strategy`
- `special_junction_id`
- `special_junction_type`
- `swsd_sgrade`
- `swsd_directionality`
- `swsd_pair_nodes`
- `swsd_junc_nodes`
- `junc_kind2_exempt_nodes`
- `detached_junc_nodes`
- `rcsd_pair_nodes`
- `rcsd_junc_nodes`
- `rcsd_road_ids`
- `retained_node_ids`
- `group_segment_ids`
- `source_segment_ids`
- `buffer_distances_m`
- `risk_flags`
- `notes`

`execution_scope` 当前稳定取值包括 `standard_segment / special_junction_group_internal / path_corridor_group`。`standard_segment` 必须来自 Step2 replaceable，`execution_action=replace`；`special_junction_group_internal` 必须来自 passed 特殊路口组，`execution_action=include_context`；`path_corridor_group` 必须来自 passed group replacement probe，`execution_action=replace`。未在 plan 中发布为 `plan_status=ready` 的审计证据不得被 Step3 执行为替换。

`t06_segment_replacement_problem_registry` 稳定字段：

- `problem_id`
- `swsd_segment_id`
- `problem_status`
- `root_cause_category`
- `failure_business_category`
- `reject_reason`
- `upstream_issue_owner`
- `recommended_module`
- `feedback_action`
- `replan_trigger`
- `swsd_pair_nodes`
- `swsd_junc_nodes`
- `rcsd_pair_nodes`
- `candidate_rcsd_pair_node_sets`
- `pair_anchor_error_swsd_nodes`
- `pair_anchor_error_original_rcsd_nodes`
- `pair_anchor_error_candidate_rcsd_nodes`
- `pair_anchor_endpoint_cluster_nodes`
- `pair_anchor_bridge_road_ids`
- `pair_anchor_bridge_length_m`
- `pair_anchor_diagnostic_source`
- `pair_anchor_diagnostic_reason`
- `evidence_artifacts`
- `manual_review_required`
- `notes`

`pair_anchor_endpoint_cluster_nodes` 来源于 T06 pair-anchor diagnostic，表达按 SWSD Segment 端点组织的 RCSDNode 诊断簇；它不同于 `candidate_rcsd_pair_node_sets`，后者是候选 corridor pair 集合，不保证可按 endpoint index 拆分给 T05 直接消费。该字段只用于 T03/T04/T05 前置迭代审计和后续显式规则设计，不允许 Step3 直接作为替换白名单。

`problem_status` 当前稳定取值包括 `covered_by_replacement_plan / resolved_in_step2_plan / accepted_non_replaceable / requires_upstream_iteration / requires_upstream_side_group_or_rcsd_directionality_review`。`accepted_non_replaceable` 表示已由 T06 审计确认无法形成可替换 RCSD Segment，例如 T05 正式 relation 将 SWSD pair 两端归并到同一个 RCSD 语义路口；该状态不进入 T10 上游迭代反馈，也不允许 Step3 兜底替换。`requires_upstream_iteration` 不允许 Step3 兜底替换，必须进入前置模块迭代队列或人工审计。`requires_upstream_side_group_or_rcsd_directionality_review` 专用于双向 Segment 的 `rcsd_not_bidirectional_for_swsd_dual + full_rcsd_graph_one_direction_only`：T06 已确认不能通过当前单 Segment fallback 安全替换，应先评估 T03/T04/T05 是否可形成双幅端点侧聚合；若前置聚合不能成立，再归入 RCSD 方向性或源资料复核。

## 4. EntryPoints

T06 当前不新增 repo CLI。稳定执行面包括模块内 callable runner 与一个已登记的内网运行包装脚本。

```python
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (
    run_t06_step1_identify_fusion_units,
    run_t06_step2_extract_rcsd_segments,
    run_t06_step3_segment_replacement,
)
```

Step3 提供独立脚本，优先消费 Step2 replacement plan，不改变 `scripts/t06_run_innernet_precheck.py` 的默认行为：

```bash
.venv/bin/python scripts/t06_run_step3_segment_replacement.py \
  --t06-run-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet
```

默认读取 Step2 同目录 `t06_segment_replacement_plan.json`，再兼容读取 `geojson/gpkg`；旧结果缺少 replacement plan 时才回退读取 `t06_special_junction_group_audit.json` 与 `t06_segment_group_replacement_audit.gpkg`。需要指定其它审计文件时可使用 `--step2-special-junction-group-audit` 或 `--step2-group-replacement-audit`。
调用方可通过 `--t07-surface / --t03-surface / --t04-surface / --t04-audit / --t05-surface` 传入路口面和 T04 reject 审计，触发 Step3 surface topology 后处理；该后处理不新增正式替换道路、不改写原始道路几何，且 T04 reject 与 Patch 冲突均为硬阻断。若 T07 surface 提供 `final_state=accepted` 且目标 SWSD node 匹配的唯一 `base_id_candidate / source_rcsdintersection_id`，可作为节点 1:1 fallback 同步补写非 `retained_swsd` relation 的 `swsd_to_frcsd_node_map`；RCSD candidate 具备有效非 0 `mainnodeid` 时使用该 RCSD `mainnodeid` 闭合；若 RCSD candidate 为单节点默认 `mainnodeid=0`，但当前融合边界存在唯一 source=2 SWSD node 且其原始默认 `mainnodeid` 有效，则使用该 SWSD 默认 `mainnodeid` 作为融合后两节点共同 mainnode。任何情况下都不得把 RCSD `mainnodeid=0` 退化改写为 RCSD node `id`。若 T07 候选是 semantic mainnode 而不是最终 F-RCSD node `id`，可通过同源 `mainnodeid` 唯一反查实际 F-RCSD node。该 fallback 不适用于 T04 reject、多 RCSD 候选或缺少唯一 RCSD candidate 的路口。

若 T04 virtual surface / audit 提供 `final_state=accepted`、`anchor_id / case_id / mainnodeid` 唯一匹配当前 SWSD node，且 T04 `patch_id` 与该 SWSD node incident road 的 Patch 集合无冲突，也可作为节点 1:1 surface 证据补写 `mainnodeid`；该 T04 patch 证据只闭合节点语义，不补写 relation node map，不得用于 T04 rejected、多 patch 冲突、错层重叠或多 RCSD 候选场景。若 Step2 `t06_rcsd_segment_failure_business_audit` 已记录当前 Segment 的 `optional_junc_nodes -> optional_junc_rcsd_nodes` 唯一映射，且该 RCSD node 已进入 Step3 F-RCSD、当前节点有 T03/T05/T07/T04 surface 命中、T04 未 reject，则 Step3 surface 后处理可补写对应非 `retained_swsd` relation 的 `swsd_to_frcsd_node_map`；RCSD candidate 具备有效非 0 `mainnodeid` 时使用该 RCSD `mainnodeid` 闭合，若 RCSD candidate 为单节点默认 `mainnodeid=0` 且唯一 source=2 SWSD node 具备有效原始默认 `mainnodeid`，则使用该 SWSD 默认值闭合。该规则只消费 Step2 已审计的 optional junc 1:1 证据，不绕过 T04 reject，不新增道路或几何，不得把 `0` 改写为 RCSD node `id`。

独立重跑 Step3 时，`step3_segment_replacement` 目录旁可能不存在同级 `step2_extract_rcsd_segments`；surface 后处理读取 Step2 optional / dropped junc 证据时，必须可从 `t06_step3_summary.json` 的 `input_paths.step2_replaceable_path` 回溯真实 Step2 输出目录，确保 dropped-junc retained SWSD node map 与完整 T06 root 下执行一致。

若最终 F-RCSD 中同一 SWSD node 已同时存在唯一 source=1 与唯一 source=2 节点、两者距离不超过 20m、且当前节点有 surface 命中、T04 未 reject，也可闭合 replaced/retained 边界；闭合 mainnode 的选择顺序为：source=1 节点有效非 0 `mainnodeid` 优先，否则使用唯一 source=2 SWSD 节点的原始默认 `mainnodeid`，不得把 RCSD `mainnodeid=0` 改写为 RCSD node `id`。该 existing cross-source 1:1 规则不补写 relation node map、不处理多 RCSD 候选。多 RCSD 候选只允许在以下受限场景自动处理：当前 SWSD node 命中 T03/T05 surface，候选 source=1 节点中仅有一个具备有效 `mainnodeid` 且距 source=2 节点不超过 5m，其他 source=1 候选至少再远 10m，T04 未 reject 且无 Patch 冲突；此时仅把非 `retained_swsd` relation 中该 SWSD node 的既有 source=1 映射改写为近端候选，标记 `mapping_status=surface_nearest_multi_candidate_fallback` 与 `risk_flags=surface_nearest_multi_candidate_node_map`，并只闭合 source=2 节点与近端 source=1 节点的 `mainnodeid`，不得强行合并远端 RCSD 节点。

当 replaced/retained 边界缺少 source=1 relation node map，但非 `retained_swsd` relation 的正式 `frcsd_road_ids` 中存在唯一近端 source=1 road endpoint，也可作为 selected replacement endpoint fallback：候选 endpoint 必须属于该 Segment 已选 replacement road，距离 source=2 节点不超过 5m，且 10m 内不存在其他有效 RCSD semantic mainnode 或其他近端 RCSD endpoint；若候选 endpoint 为 `mainnodeid=0`，必须存在唯一 source=2 SWSD 节点的有效原始默认 `mainnodeid`，并使用该 SWSD 默认值闭合，不得把 `0` 改写为 RCSD endpoint `id`。T04 reject、Patch 冲突、多候选或仅来源于未选中 RCSD road 的 endpoint 均不得使用该规则。该规则只补写非 `retained_swsd` relation 的 `swsd_to_frcsd_node_map`，标记 `mapping_status=selected_replacement_endpoint_fallback` 与 `risk_flags=selected_replacement_endpoint_fallback_node_map`，并只闭合 source=2 节点与被选 endpoint 的 `mainnodeid`，不新增道路、不修改原始道路几何。`--no-surface-topology-closure` 可关闭自动闭环，仅输出审计。

当 Step3 调用方提供 surface 输入时，脚本可在不改变调用参数的前提下对 `source_reason=junction_alignment_to_retained_swsd_exceeds_topology_gate` 的 Step2 replacement plan 行执行 surface-aware 条件释放。释放条件只接受两类证据：触发超距节点在 surface topology audit 中为 pass，且 reason 属于 `auto_closed / auto_closed_surface_1v1 / auto_closed_t04_patch_1v1 / auto_closed_step2_junc_1v1 / auto_closed_relation_mapped_boundary_1v1 / auto_closed_selected_replacement_endpoint`；或触发超距节点是 plan 的 `swsd_pair_nodes -> original_rcsd_pair_nodes` 原始端点映射。T04 reject、Patch 冲突、多候选、缺少可解释 endpoint、以及非该 gate 的 blocked plan 都不能被释放。释放后的 plan 必须重跑 Step3 与 topology audit；若候选释放引入新增 hard fail，相关 plan 回退为 `plan_status=blocked / execution_action=hold`，并记录 `source_reason=junction_alignment_surface_release_failed_topology_gate`。若相对传入 `--t06-run-root` 下已有 Step3 baseline 仍存在新增 fail，必须写入 `external_final_added_fail_count / external_final_added_fail_keys`，不得把内部 release 回退通过误表述为外部 baseline 零新增。

当 Step3 调用方提供 `--t05-surface` 时，正式 replacement unit 的 coverage 兜底可使用当前 unit 的 `pair_nodes / junc_nodes` 命中的 T05 junction anchor surface 解释端点路口面内长度差异。释放只扣除落在对应 surface 内的 uncovered geometry，不改变原始 CRS 与道路几何，不新增替换道路，不释放 Step2 rejected plan，也不绕过 topology connectivity audit；释放证据必须通过风险标记和 summary 保持可追溯。

内网脚本入口：

```bash
.venv/bin/python scripts/t06_run_innernet_precheck.py \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck
```

脚本默认从 `--t05-phase2-root` 自动发现 `intersection_match_all.geojson`、`rcsdroad_out.gpkg` 与 `rcsdnode_out.gpkg`；三者也可以通过显式参数覆盖。

文本证据包 helper 仅作为模块内非官方 helper 调用，不新增 repo CLI / scripts 入口。打包参数保持与内网端到端脚本一致：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_export_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_active_road_fix_2/t05_phase2_full \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck \
  --run-id t06_innernet_precheck
```

输入切片包：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_export_input_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_active_road_fix_2/t05_phase2_full \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck \
  --run-id t06_innernet_precheck \
  --center-x <EPSG3857_X> \
  --center-y <EPSG3857_Y> \
  --profile-id XS
```

输入切片包是面向本地可复现测试用例的包。解包后必须包含下列本地输入文件：

- `slice/swsd/segment.geojson`
- `slice/swsd/roads.geojson`
- `slice/swsd/nodes.geojson`
- `slice/t05_phase2/intersection_match_all.geojson`
- `slice/t05_phase2/rcsdroad_out.geojson`
- `slice/t05_phase2/rcsdnode_out.geojson`

同时必须包含：

- `README_t06_local_case.md`
- `audit/t06_local_case_manifest.json`
- `audit/replay_t06_decoded_precheck.sh`
- `audit/replay_t06_decoded_step3_segment_replacement.sh`

`audit/replay_t06_decoded_precheck.sh` 必须只引用解包后的 `slice/` 输入，`audit/replay_t06_decoded_step3_segment_replacement.sh` 必须消费同一解包目录中 Step1 + Step2 复跑产生的 Step2 replaceable 成果。`t06_local_case_manifest.json` 与 `slice/t06_input_slice_summary.json` 必须记录依赖完整性审计，覆盖 SWSD Segment 引用 Road、SWSD 语义节点、Road 端点 Node、T05 relation 映射出的 RCSD 语义节点，以及已选 RCSDRoad 端点 Node。

解包：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_decode_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck/t06_segment_fusion_precheck_evidence_bundle.txt \
  --out-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck_decoded_bundle
```

## 5. Params

- `run_id`：可选运行 ID；为空时自动生成。
- `progress`：是否打印稀疏进度。
- `max_main_axis_angle_diff_deg`：兼容保留参数；buffer-based Step2 主链不再使用主轴趋势硬筛。
- `min_coarse_length_ratio`：兼容保留参数；buffer-based Step2 主链不再使用粗长度趋势硬筛。
- `max_coarse_length_ratio`：兼容保留参数；buffer-based Step2 主链不再使用粗长度趋势硬筛。
- `buffer_distance_m`：buffer-based RCSDSegment 审查基准缓冲距离，默认 `50.0`；高等级 single graph-first 纵向联通与 dual graph-first 双向联通仍以该 50m buffer 作为 core 约束，dual adaptive buffer 不改变该全局参数，只在输出审计中记录实际重审距离。
- `min_buffer_road_overlap_ratio`：RCSDRoad 与 buffer 相交长度占比阈值，默认 `0.2`。
- `min_buffer_road_overlap_length_m`：RCSDRoad 与 buffer 相交长度下限，默认 `1.0`。
- `visual_consistency_buffer_distance_m`：50m 正式 buffer 覆盖通过后的窄通道连续性复核距离，默认 `15.0`；用于记录 RCSD 虽在宽 buffer 内但替换后可能造成目视主线断裂的审计风险。
- `max_visual_consistency_mismatch_ratio / min_visual_consistency_mismatch_length_m`：窄通道连续性 mismatch 的比例 / 绝对长度阈值，默认 `0.1 / 20.0`，任一超限必须写入几何审计字段；`swsd_visual_continuity_not_covered_by_retained_rcsd` 不作为正式拒绝门槛。
- `advance_right_formway_bit`：提前右转 bit mask，默认 `128`；命中该 bit 的 road 在两端均与非提前右转候选 road 存在二度链接关系，或属于 required semantic nodes 之间的必要 corridor 时保留。
- `max_text_size_bytes`：文本证据包单个 `.txt` 分片体量上限，默认 `250KB`；仅作用于文本包 helper，不影响 Step1 / Step2 业务运行。
- `rcsd_semantic_node_alias_count`：Step2 summary 审计字段，记录参与 `subnodeid/id -> mainnodeid` 归一化的非恒等 alias 数量。
- `rcsd_semantic_node_group_count`：Step2 summary 审计字段，记录从 `rcsdnode_path` 识别出的全局 RCSD 语义路口组数量。
- `rcsd_road_total_count / rcsd_road_total_length_m / replaceable_rcsd_road_unique_count / replaceable_rcsd_road_unique_length_m`：Step2 summary 的 RCSDRoad 覆盖统计字段，长度基于处理 CRS 下的几何长度计算。
- Step3 参数：`source_field_name="source"`、`rcsd_source_value=1`、`swsd_source_value=2`；`id_collision_policy="keep_original_ids_and_audit_with_source_field"`；新 main node 选择优先级为 `original_mainnode_if_retained -> remaining_swsd_node_min_id -> added_rcsd_node_min_id`。

## 5.1 2026-06-14 补充规则：高等级 pair fail1 多 RCSD 关系消费

- Step1 不把所有 `fail1` 视为 anchor eligible。
- 仅当 Segment 为高等级口径（`sgrade` 以 `0-0` 或 `0-1` 开头）、失败节点属于 `pair_nodes`、该节点 `has_evd = yes`、`is_anchor = fail1` 且 `kind_2 = 4` 时，Step1 允许该 Segment 进入 Step2 probe。
- Step2 仍必须通过 T05 `intersection_match_all.geojson` 找到 `status = 0 / base_id != 0` 的关系；缺失或失败 relation 仍按既有 `missing_pair_relation / invalid_pair_relation_status` 等原因拒绝。
- 该规则只负责消费 T07/T05 已正式表达的 SWSD 1:N RCSD 语义路口关系，不放宽 50m buffer、方向性、连通性、retained Road 覆盖率或特殊路口组门控。

## 6. Acceptance

1. Step1 runner 可独立运行并输出 SWSD Segment 候选集、最终可融合集合、rejected、summary 与按 `sgrade` 分组的统计 CSV，且不重复输出相同业务成果。
2. Step2 runner 可独立运行并输出 buffer-based RCSDSegment 候选、最终 replaceable、rejected、buffer rejected、特殊路口组审计、replacement plan、problem registry 与 summary。
3. `fail4_fallback` 能进入 Step1 final fusion units，但 Step2 对 pair relation 硬必检集合仍必须校验 T05 relation。
4. `junc_nodes.kind_2 in {1,4096,8192}` 的节点不参与 Step1 `has_evd / is_anchor` 判定；Step2 中所有 `junc_nodes` 均按 optional junc 审计处理。同值 `pair_nodes` 仍按原规则判定并映射。高等级 Segment 中 `pair_nodes.kind_2=2048`、`junc_nodes.kind_2 in {16,2048}` 只能作为 Step2 probe 放行，不得被视作 Step1 anchor 豁免或 T05 relation 成功。高等级 Segment 的非特殊 junc-only 节点若因 `has_evd / is_anchor` 失败拖垮主通道，Step1 可输出 `detached_junc_nodes / detached_junc_reasons` 并从 final `junc_nodes / semantic_node_set` 中移除；`pair_nodes` 与 `kind_2 in {64,128}` 特殊路口不得脱挂。
5. Step2 不执行旧 pair-to-pair BFS 路径搜索、主轴 / 粗长度趋势或唯一性筛选；buffer 候选连通分量必须先收缩为覆盖 pair required semantic nodes 的最小 corridor 子图；`swsd_directionality=single` 时必须由 SWSDRoad `snodeid / enodeid / direction` 推导 pair source/target，并按该方向构建覆盖 pair required semantic nodes 的 RCSD corridor，否则以 `rcsd_directed_path_missing` 或 `swsd_single_direction_*` 拒绝；特殊语义路口 subnode 端点导致初始有向 corridor 失败时，只允许保持原方向执行本地 corridor 受限释放，不允许翻转 Segment 方向、改写字段语义或回写 T05 relation；`swsd_directionality=dual` 时 retained RCSD graph 必须 pair 两端双向可达，否则以 `rcsd_not_bidirectional_for_swsd_dual` 拒绝；pair anchor 自动补全缺失端点时不得使用 buffer-only 候选顺序覆盖 SWSD pair 侧，必须按 relation 失败侧重排候选。
6. SWSD pair 两端相同或映射后 RCSD pair 坍缩到同一个语义路口时，Step2 必须拒绝并输出 `swsd_pair_nodes_not_distinct` 或 `rcsd_pair_nodes_not_distinct`。
7. `junc_nodes` 执行 optional 内部通过 + 侧向阻断；孤立 optional junc 可被剪除并输出 dropped / lost attach 审计，retained graph 中出现非 pair leaf endpoint 时必须拒绝并输出 `unexpected_endpoint_node_ids`。
8. retained graph 中不得存在 pair required corridor 内部解释节点以外的额外 T05 mapped semantic nodes；出现时必须拒绝并输出 `unexpected_mapped_semantic_node_ids`。
9. 所有解析、映射、buffer 构建失败都有明确 reason。
10. 输入文件不被原地修改。
11. buffer-based RCSDSegment 审查必须按 `formway` bit7/128 识别提前右转 road；二度链接保留、required corridor 保留和排除结果必须在 summary / 输出中可审计。
12. `swsd_directionality=dual` 不能因短 required-to-required connector 通过双向审计；retained corridor 内部 `formway & 1024 != 0` 调头 road 必须保留。
13. Step2 retained RCSDRoad 必须满足 `min_buffer_road_overlap_ratio` 覆盖审计；不满足时以 `retained_road_buffer_overlap_insufficient` 拒绝，并在 `failed_metric_value` 中记录低覆盖 Road ID 与最小覆盖率。
14. 高等级受限重审默认保留 T05 原始 pair relation；single 必须以 RCSD 有向图联通 pair 路口并经过 50m buffer core，不得消费 repair candidate；dual 只有在 buffer-only probe 给出非人工复核高置信候选 pair 集合，且候选 pair 遍历试算后恰好一个通过正式双向 extractor / adaptive buffer / dual graph-first 硬审计时，才允许在当前 Segment 内使用该候选 pair。dual graph-first 的 union path 不得穿过额外 mapped semantic nodes。重审通过时必须输出审计距离、方向分组与来源失败原因。
15. Step3 必须优先消费 Step2 replacement plan，只执行 `plan_status=ready` 的普通 Segment replace、特殊路口组内部 include_context 与 path-corridor group replace action；删除被替换 SWSDRoad 与其端点 SWSDNode，保留未替换 SWSD 数据并写 `source=2`，引入 retained RCSD 数据、plan 发布的特殊路口组内部 RCSD 数据与 path-corridor group RCSD 数据并写 `source=1`。若 replaceable 的 junc 集合相对 T01 原始 Segment 发生 detached junc 缩减，detached junc 触达的原 SWSDRoad 必须保留为 `source=2` 局部 carrier，Segment relation 必须标记 `replaced+retained_swsd` 并输出 identity node map，避免 T09 显式 restriction 因局部未锚定而丢失。
16. Step3 必须按 C 聚合重建语义路口关系；若原 main node 被删除，必须重新选择 main node，并让 C 内 Node 继承原 main node 的 `kind / grade / kind_2 / grade_2 / closed_con`。
