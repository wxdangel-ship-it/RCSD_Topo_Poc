# 02 Business Rules

## Step1

对每个 SWSD Segment：

```text
semantic_node_set = unique(pair_nodes + junc_nodes)
```

- `pair_nodes` 必须解析出两个语义路口 ID。
- `junc_nodes` 可以为空。
- Step1 读取节点属性时优先使用 `id` 精确匹配的代表记录；仅在缺少对应 `id` 记录时使用 `mainnodeid` fallback。
- `junc_nodes` 中 `kind_2 in {1,4096,8192}` 的节点从 Step1 eligibility 检查集合中移除，视为通过 `has_evd / is_anchor` 判定。
- `kind_2` 豁免不适用于 `pair_nodes`，也不改变 `junc_nodes / semantic_node_set` 输出。
- eligibility 检查集合内全部语义路口 `has_evd = yes` 时进入 EVD candidates。
- 在 EVD candidates 中，eligibility 检查集合内全部语义路口 `is_anchor in {yes, fail4_fallback}` 时进入 fusion units。
- `fail4_fallback` 必须视为可融合 anchor。

## Step2

- relation mapping 使用 `intersection_match_all.geojson` 的 `target_id -> base_id`。
- 只接受 `status = 0` 且 `base_id > 0`。
- `pair_nodes` 必须映射成功；非豁免 `junc_nodes` 若映射成功则进入 optional junc 审计，映射缺失或无效时进入 `dropped_junc_nodes / junc_attach_loss_reason`，不得默认拒绝 pair-to-pair 主通道。
- `pair_nodes` 必须表示两个不同 SWSD 语义路口；若两端相同，以 `swsd_pair_nodes_not_distinct` 拒绝。
- T05 relation 映射后的 RCSD pair 两端归一到同一个 RCSD 语义路口时，以 `rcsd_pair_nodes_not_distinct` 拒绝。
- `junc_kind2_exempt_nodes` 不参与 Step2 relation 必检集合；若存在有效 relation，可作为 optional allowed 审计节点保留。
- buffer-based RCSDSegment 审查以 SWSD Segment 50m buffer 限定 RCSD 候选；RCSDRoad 使用 `intersects + overlap threshold`，RCSDNode 使用 `covers/within`。
- buffer candidate graph 按 `rcsdnode_out.id/mainnodeid/subnodeid` 归一到 canonical RCSD semantic node id 后再判定连通。
- 全局 RCSD 语义路口组按有效 `mainnodeid` 聚合，组内所有 node 关联 road 均视为该语义路口的进入 / 退出道路；未映射到当前 Segment 的全局 RCSD 语义路口若进入候选图，必须参与 seed pruning，处于 required corridor 内部时作为 `inner_nodes` 保留，旁支节点归入 `out_nodes` 裁剪。
- 构建 buffer 候选连通图前，`formway` bit7/128 的提前右转 road 必须识别并输出审计；若该 road 两端均与非提前右转候选 road 形成二度链接，或属于 required semantic nodes 之间的必要 corridor，则保留参与 Segment 构建，否则排除。
- buffer 审查的 required semantic nodes 只来自 `pair_nodes` relation；非豁免 `junc_nodes` 与 `junc_kind2_exempt_nodes` 的有效 relation 都作为 optional allowed 审计节点。
- buffer 候选连通分量不能直接输出为 RCSDSegment；必须先基于 required semantic nodes 构建最小 corridor 子图，避免闭环与旁支被错误保留。
- 额外 T05 mapped semantic nodes 与 optional junc 必须作为 seed group 执行裁剪：pair required corridor 内部 seed 归为 `inner_nodes` 并可保留审计；触达孤立挂接或 out leaf 且不在 required corridor 内的 seed 归为 `out_nodes` 并从 retained 子图中剔除；retained graph 中仍存在非 inner 的额外 mapped semantic nodes 时，必须以 `unexpected_mapped_semantic_nodes` 拒绝。
- 双向 SWSD 必须在 pruning 阶段保护 pair 两端正反向 directed corridor，避免另一侧 RCSD 主线被误裁剪。
- 若剔除 `out_nodes` 后 required semantic nodes 不再连通，必须拒绝，不得输出为 replaceable。
- retained RCSD graph 的叶子端点只能是 `pair_nodes` 对应的 RCSD semantic nodes；非 pair 叶子端点必须以 `unexpected_retained_endpoint_nodes` 拒绝。
- `swsd_directionality=dual` 的 retained RCSD graph 必须 pair 两端双向可达，否则以 `rcsd_not_bidirectional_for_swsd_dual` 拒绝。
- `swsd_directionality=single` 必须由 SWSDRoad `snodeid / enodeid / direction` 推导 pair source/target，并按该方向构建覆盖 pair required semantic nodes 的 RCSD 有向 corridor，不得把无向 corridor、反向可达或 `pair_nodes / segmentid` 顺序作为兜底；不满足时以 `rcsd_directed_path_missing` 或 `swsd_single_direction_*` 拒绝。
- retained RCSDSegment 的每条 RCSDRoad 必须满足 `min_buffer_road_overlap_ratio` 覆盖审计；若完整 RCSDRoad 最终 retained 但与 SWSD Segment buffer 的覆盖率不足，必须以 `retained_road_buffer_overlap_insufficient` 拒绝；retained RCSD 与 SWSD 的整体 50m buffer 覆盖不一致比例默认不得超过 `10%`，绝对长度默认不得超过 `20m`，任一超限即拒绝。
- `kind_2=64` 环岛路口与 `kind_2=128` 复杂路口执行特殊组门控：按 Step2 输入融合单元中 `pair_nodes + junc_nodes` 包含该语义路口识别关联 Segment；若关联 Segment 未全部进入可替换集合，则该特殊组所有原本可替换 Segment 均移出 `replaceable`，并以 `special_junction_group_not_fully_replaceable` 输出拒绝。
- 特殊组审计必须记录 SWSD 特殊路口映射到 RCSD 后的 `rcsd_junction_id`、RCSD 语义组内 Node，以及端点同归一到该 RCSD 语义组的内部 RCSDRoad，供 Step3 统一替换审计。
- RCSD 网络通过 runner 参数传入，不硬编码路径。
- `junc_nodes` 表示内部通过 + 侧向阻断，不是 hard-stop。
- Step2 失败后必须执行 buffer-only probe：不依赖 T05 relation 绑定，只基于 SWSD Segment buffer 与 RCSDRoad / RCSDNode 图结构输出 `no_corridor / corridor_found / corridor_found_with_topology_issue / corridor_found_with_anchor_mismatch / ambiguous_corridor` 等诊断状态。probe 只用于诊断；pair 锚定疑似错误具备唯一高置信候选，或同一 Segment 端点存在候选 RCSDRoad 内短距离联通 endpoint cluster 时，也只作为人工质检证据。
- 对 pair 锚定 1V多 / 多V1 / 错误锚定，不允许静默覆盖 T05 relation，也不允许仅凭候选 pair 更新 T06 当前 Segment 的构建锚点；必须输出 `t06_rcsd_repair_candidates.*` 与 failure business audit，记录错误 SWSD 端点、原始 RCSD anchor、候选 RCSD anchor、endpoint cluster、bridge road 与长度。多候选或评分接近的场景必须人工复核。
- Step2 不再执行旧 pair-to-pair BFS 路径搜索、主轴 / 粗长度趋势或唯一性筛选；单向方向仅按 SWSDRoad directed graph 推导。
- `t06_rcsd_buffer_segments` 是 buffer 构建成果；`t06_rcsd_segment_candidates` 是 buffer 成功构建的候选；`t06_rcsd_segment_replaceable` 是经过全部硬审计与特殊路口组门控后的最终可替换集合。

## Step2 过滤顺序

1. pair relation hard mapping filter and junc optional relation audit
2. SWSD Segment buffer candidate selection
3. advance-right-turn road classification by `formway & 128 != 0`, with second-degree non-advance-link retention and required-corridor retention
4. canonical RCSD semantic node graph construction
5. pair required semantic node component coverage
6. inner / out node pruning
7. retained pair required semantic node connectivity check
8. retained extra mapped semantic node check
9. retained dual-direction reachability check for `swsd_directionality=dual`
10. retained leaf endpoint check
11. retained RCSDRoad buffer overlap ratio check
12. retained RCSDRoad output and compatibility replaceable output

## Step3

- Step3 只消费 Step2 replaceable RCSDSegment，不处理 rejected Segment。
- 对每个 replaceable Segment，以 `swsd_segment_id` 建立替换单元，记录 SWSD `pair_nodes / junc_nodes / roads` 与 Step2 retained RCSD road / node。
- Step3 不重新判定特殊路口组是否可替换；若 Step2 输出 passed 特殊路口组审计，则将组内 RCSD 语义路口内部 Node/Road 作为组级替换实体统一加入 F-RCSD。
- 所有 replaceable Segment 的 `pair_nodes + junc_nodes` 组成待重建语义路口集合 C。
- 每个 C 必须记录其涉及的 Node，并建立 C 与关联替换单元的关系。
- 被替换 Segment 涉及的 SWSDRoad 必须从 F-RCSD Road 中清除。
- SWSDNode 仅清除被替换 SWSDRoad 的端点 Node，不清除 C 对应 SWSD 语义路口组下的所有 Node。
- Step2 retained RCSDRoad / RCSDNode 必须加入 F-RCSD 输出。
- F-RCSD 输出中 `source=1` 表示 RCSD 数据，`source=2` 表示 SWSD 数据。
- 对每个 C，若原 main node 仍保留，则继续使用原 main node；若原 main node 已删除，则重新选择一个保留 Node 作为 main node。
- C 内其余 Node 的 `mainnodeid` 必须替换为新的 main node id。
- C 内 Node 的 `kind / grade / kind_2 / grade_2 / closed_con` 必须继承原 main node 对应 Node 的属性。
- Step3 必须输出删除 SWSDRoad、删除 SWSDNode、加入 RCSDRoad、加入 RCSDNode、C 重建关系与 main node 选择过程的审计。
