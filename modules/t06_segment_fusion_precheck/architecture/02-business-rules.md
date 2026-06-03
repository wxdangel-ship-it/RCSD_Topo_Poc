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
- `pair_nodes` 和非豁免 `junc_nodes` 都必须映射成功。
- `junc_kind2_exempt_nodes` 不参与 Step2 relation 必检集合，也不参与后续 mapped junc 覆盖、内部通过与语义顺序检查。
- buffer-based RCSDSegment 审查以 SWSD Segment 50m buffer 限定 RCSD 候选；RCSDRoad 使用 `intersects + overlap threshold`，RCSDNode 使用 `covers/within`。
- buffer candidate graph 按 `rcsdnode_out.id/mainnodeid/subnodeid` 归一到 canonical RCSD semantic node id 后再判定连通。
- 全局 RCSD 语义路口组按有效 `mainnodeid` 聚合，组内所有 node 关联 road 均视为该语义路口的进入 / 退出道路；未映射到当前 Segment 的全局 RCSD 语义路口若进入候选图，必须参与 seed pruning，处于 required corridor 内部时作为 `inner_nodes` 保留，旁支节点归入 `out_nodes` 裁剪。
- 构建 buffer 候选连通图前，`formway` bit7/128 的提前右转 road 必须识别并输出审计；若该 road 两端均与非提前右转候选 road 形成二度链接，或属于 required semantic nodes 之间的必要 corridor，则保留参与 Segment 构建，否则排除。
- buffer 审查的 required semantic nodes 为 `pair_nodes` relation 与非豁免 `junc_nodes` relation；`junc_kind2_exempt_nodes` 只作为 optional allowed 审计节点。
- buffer 候选连通分量不能直接输出为 RCSDSegment；必须先基于 required semantic nodes 构建最小 corridor 子图，避免闭环与旁支被错误保留。
- 额外 T05 mapped semantic nodes 必须作为 seed group 执行裁剪：required corridor 内部 seed 归为 `inner_nodes` 并可保留审计；触达孤立挂接或 out leaf 且不在 required corridor 内的 seed 归为 `out_nodes` 并从 retained 子图中剔除；retained graph 中仍存在非 inner 的额外 mapped semantic nodes 时，必须以 `unexpected_mapped_semantic_nodes` 拒绝。
- 双向 SWSD 必须在 pruning 阶段保护 pair 两端正反向 directed corridor，避免另一侧 RCSD 主线被误裁剪。
- 若剔除 `out_nodes` 后 required semantic nodes 不再连通，必须拒绝，不得输出为 replaceable。
- retained RCSD graph 的叶子端点只能是 `pair_nodes` 对应的 RCSD semantic nodes；非 pair 叶子端点必须以 `unexpected_retained_endpoint_nodes` 拒绝。
- `swsd_directionality=dual` 的 retained RCSD graph 必须 pair 两端双向可达，否则以 `rcsd_not_bidirectional_for_swsd_dual` 拒绝。
- `swsd_directionality=single` 必须构建一条覆盖全部 required semantic nodes 的 pair 端到另一端有向 corridor，不得把无向 corridor 与有向 pair path 做并集；不满足时以 `rcsd_directed_path_missing` 拒绝。
- RCSD 网络通过 runner 参数传入，不硬编码路径。
- `junc_nodes` 表示内部通过 + 侧向阻断，不是 hard-stop。
- Step2 不再执行旧 pair-to-pair BFS 路径搜索、SWSD 单向方向推导、主轴 / 粗长度趋势或唯一性筛选。
- `t06_rcsd_buffer_segments` 是正式主成果；`t06_rcsd_segment_candidates / replaceable` 仅作为兼容输出，由 buffer 成功结果派生。

## Step2 过滤顺序

1. relation mapping filter
2. SWSD Segment buffer candidate selection
3. advance-right-turn road classification by `formway & 128 != 0`, with second-degree non-advance-link retention and required-corridor retention
4. canonical RCSD semantic node graph construction
5. required semantic node component coverage
6. inner / out node pruning
7. retained required semantic node connectivity check
8. retained extra mapped semantic node check
9. retained dual-direction reachability check for `swsd_directionality=dual`
10. retained leaf endpoint check
11. retained RCSDRoad output and compatibility replaceable output

## Step3

- Step3 只消费 Step2 replaceable RCSDSegment，不处理 rejected Segment。
- 对每个 replaceable Segment，以 `swsd_segment_id` 建立替换单元，记录 SWSD `pair_nodes / junc_nodes / roads` 与 Step2 retained RCSD road / node。
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
