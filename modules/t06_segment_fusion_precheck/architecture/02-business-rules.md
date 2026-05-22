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
- RCSD 网络通过 runner 参数传入，不硬编码路径。
- `junc_nodes` 表示内部通过 + 侧向阻断，不是 hard-stop。
- SWSD 单向方向必须从 `swsd_roads_path` 的 road body 推导。
- SWSD 单向 + RCSD 双向 rejected。

## 趋势硬筛顺序

1. relation mapping filter
2. SWSD direction inference
3. RCSD candidate connectivity extraction
4. directionality trend
5. oneway direction trend
6. junc internal pass + side blocking
7. semantic junc order trend
8. main axis trend
9. coarse length trend
10. uniqueness filter
