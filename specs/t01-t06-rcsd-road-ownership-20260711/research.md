# T01/T06 RCSD Road 归属升级现状研究

## 1. 研究目标

本研究用于回答三个问题：

1. 当前六个正式 T10 Case 中，RCSD Road 是否已经完整进入最终使用或未替换集合；
2. 当前 T06 的 Segment replacement、path-corridor group 与二度连通补充是否符合新的归属口径；
3. 在不降低 Step2 可替换成果的前提下，T01 提右 Segment 与 T06 RCSD ownership 应从哪里升级。

研究先完成、方案后形成，未在研究阶段修改 T01/T06 正式代码。

## 2. 证据根

- 正式六 Case 基线：`outputs/baselines/t10_full_96b0ea5_20260710_060735`
- 基线 repo head：`96b0ea518ba486db6d72afef79e637a0fad84e93`
- 六个 Case：`1885118 / 605415675 / 609214532 / 706247 / 74155468 / 991176`
- 本轮临时工作树：`E:\Work\RCSD_Topo_Poc__wt_t06_rcsd_ownership_20260711`
- 本轮分析工件：`outputs/_work/t06_rcsd_ownership_20260711/`

正式结论优先使用 GPKG/CSV 实际行与集合；compact summary 只作为辅助索引，因为基线中存在 summary 晚于或早于后处理落盘的数量差异。

## 3. Step2 不回退冻结基线

| Case | Step2 可替换 Segment | Step2 可替换 RCSD Road | Step2 可替换 RCSD 里程(m) | Step2 可替换但最终未替换 | Step2 外最终替换成功 |
|---|---:|---:|---:|---:|---:|
| 1885118 | 979 | 4,969 | 508,043.207 | 42 | 28 |
| 605415675 | 265 | 1,352 | 131,493.934 | 14 | 6 |
| 609214532 | 686 | 3,500 | 351,971.830 | 23 | 19 |
| 706247 | 324 | 1,214 | 101,355.069 | 18 | 10 |
| 74155468 | 92 | 316 | 26,141.794 | 3 | 2 |
| 991176 | 138 | 447 | 39,217.028 | 5 | 2 |
| 合计 | 2,484 | 11,798 | 1,158,222.862 | 105 | 67 |

`2,484` 个 Segment 的 id 明细已经冻结在分析工件 `six_case_step2_no_regression_segments.csv`。后续任何 T01/T06 改动都必须证明该集合未减少；如 Segment id 因 T01 提右新增而变化，普通 Segment 的旧集合仍必须逐 id 保留或提供一对一迁移证明。

## 4. RCSD Road 覆盖与归属现状

六 Case 原始 RCSD Road 合计 `16,347` 条：

- 最终 F-RCSD 中可回溯到原始 RCSD Road：`12,450`；
- 未替换 RCSD Road：`3,897`；
- 两者遗漏：`0`；
- 两者交叉：`0`。

因此当前主要问题不是 RCSD Road 丢失，而是 ownership 不唯一或证据不足：

- 未替换 RCSD 中同时匹配多个 Segment：`3,101 / 3,897`；
- 未替换 RCSD 中无候选 Segment：`175`；
- 未替换归因 `exact`：`396`；
- 未替换归因 `approximate`：`3,231`；
- 未替换归因 `low`：`270`；
- 最终 replaced relation 中被多个 Segment 同时引用的 RCSD Road：`4,369`。

当前六类未替换归因分布：

| 当前 final class | Road 数 | 里程(m) | 主要问题 |
|---|---:|---:|---|
| `1_outside_swsd_segment_scope` | 504 | 66,963.660 | 仅 `175` 条零候选，不能把全部 504 条直接视为现实变更 |
| `2_swsd_scope_no_t06_evidence` | 1,433 | 191,981.870 | `1,265` 条同时匹配多个 Segment |
| `3_evidence_scope_relation_incomplete` | 603 | 63,141.050 | 锚定/关系不完整，但仍需收敛到 owner |
| `4_relation_scope_not_replaceable` | 830 | 75,296.170 | 只有 `377` 条 exact，其余仍依赖几何主 Segment |
| `5_replaceable_scope_unreplaced` | 57 | 3,506.040 | 19 条 exact，38 条 approximate |
| `6_unattributed_manual_audit_without_dominant_class` | 470 | 21,801.350 | 不能继续作为 unresolved 垃圾桶 |

## 5. Step2 外最终替换成功的 67 个 Segment

根因分布：

- `rcsd_not_bidirectional_for_swsd_dual`：`54`；
- `missing_junc_relation / invalid_junc_relation_status`：`8`；
- `required_semantic_nodes_not_connected_in_buffer`：`5`。

旧 group audit 状态：

- `blocked_group_closure_incomplete`：`52`；
- `not_group_required_no_external_anchor`：`5`；
- `candidate_group_closure_ready`：`10`。

当前实现只要 `group_probe_status=passed` 就可发布 ready `path_corridor_group` plan。该条件覆盖了 source Segment 是否进入 Step2 replaceable、Junc 是否完整锚定、required topology 是否闭合以及 group closure 是否仍有 blocker。

新业务下初步结论：

- 8 个 Junc relation 缺失/无效 Segment 不得继续计为 Segment 替换；
- 5 个 required topology 不连通 Segment 不得在问题未解决时计为 Segment 替换；
- 54 个方向性失败 Segment 需要区分：真正的多 Segment 连通补充、RCSD 方向性质量问题、group closure 不完整以及旧 plan 过度吸收；
- 52 个已标记 `blocked_group_closure_incomplete` 的对象不能继续仅凭 group probe 作为 ready Segment replacement；
- 10 个 candidate group ready 也必须改为独立多 Segment connectivity 语义后再决定 RCSD Road 是否可进入 F-RCSD，不能直接增加 Segment 替换数。

Case `1885118_1915013` 是明确反例：Junc `1898198` 在 T05 中为 `status=1 / base_id=0`，Step2 以 `invalid_junc_relation_status` 拒绝，但 path-corridor plan 仍替换成功。按新业务必须保留 SWSD Segment，不得作为 Segment 替换。

## 6. 二度连通补充与 path-corridor 的边界

六 Case 当前二度连通 fallback：

- 新增 RCSD Road：`56`；
- 连通组：`36`；
- 关联 Segment：`53`。

这 56 条 Road 是“多 Segment 连通归属”的直接原型。当前实现把同一 bridge Road追加到多个 Segment unit/relation，导致归属重复；新模型应让该 Road 只属于一个 connectivity group，并通过 `related_segment_ids` 关联多个 Segment。

path-corridor 的多 Segment引用规模为 `4,369` 条 Road，远大于二度连通补充。它当前承担了“修复 rejected Segment”与“共享组级 corridor”两种职责，不能整体视为多 Segment connectivity。必须拆开：

- 单 Segment 正式替换仍以 Step2 replaceable 为边界；
- 真实桥接/调头/平行路连接形成独立 connectivity group；
- rejected Segment 不因组级 union 可连通而自动升级为 Segment replaced。

## 7. T01 提右 Segment 前置缺口

六 Case T01 SWSD Road：

- `formway & 128 != 0` 的提右 Road：`500`；
- 已有 `segmentid`：`0`；
- 未构 Segment：`500`；
- 纯提右 Segment：`0`。

当前 T01 源事实明确排除 `formway=128`，与本轮业务目标冲突。T01 必须新增只包含提右 Road 的 Segment 类型；该类型不产生普通 Segment 的 Pair/Junc 锚定要求，并由 T06 Step3 现有提右业务链路消费。

六 Case RCSD 提右 Road 共 `1,191` 条，其中 `961` 已进入最终 RCSD、`230` 未替换。其规模大于 SWSD 提右，验证了 RCSD 工艺范围更宽；不能用 RCSD `formway=128` 直接决定 owner。

## 8. GIS、拓扑与审计结论

- 六 Case 的 T01 Segment、T05 RCSD Road、Step3 F-RCSD Road、未替换归因图层均为 `EPSG:3857`；
- 上述图层空几何为 `0`、无效几何为 `0`；
- 当前问题不是 CRS 或几何损坏；
- 归属不能只依赖 20m/50m 几何主 Segment，因为大量 Road 同时命中多个 Segment；
- 任何 ownership 冲突、关系缺失、group closure blocker 都必须显式审计，禁止 silent fix；
- compact summary 与最终 GPKG/CSV 有数量差异，后续 summary 必须从最终落盘对象回算或校验。

## 9. 研究结论

正式方案必须建立四类归属：

1. `single_segment`；
2. `multi_segment_connectivity`；
3. `reality_change`；
4. 严格受控的 `unresolved_exception`。

其中提右是 `single_segment` 的独立 Segment 类型；多 Segment connectivity 可计入 RCSD Road 替换率，但不计入 Segment 替换率。Step2 可替换集合是单 Segment 替换的不回退底座，不能被新 ownership 设计削弱。
