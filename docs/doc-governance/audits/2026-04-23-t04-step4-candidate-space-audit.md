# T04 Step4 候选空间选择逻辑审计（2026-04-23）

> 审计输入：用户原始诉求 4 条
> 审计对象：
> - docs：`modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md §3.4 / §3.5`、`architecture/04-solution-strategy.md §3`、`architecture/06-step34-repair-design.md §4`
> - code：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/{event_interpretation_branch_variants.py,_event_interpretation_core.py,_runtime_step4_geometry_core.py,_runtime_step4_geometry_reference.py,variant_ranking.py}`

## 0. 用户原始诉求复述

1. unit 的两个分支从 node 出发，分支之间构成候选空间。
2. 分支可以延续到「非当前路口」的 node，可以穿越「同路口」的 sibling node 继续追溯分支。
3. 分支最长不超过 200m。
4. 分支之间如果距离太远也具备结束条件，当前用户尚未给出明确阈值。

---

## 1. 候选空间是「基于分支」还是「沿用旧扫描」？

结论：**混合形态——分支语义在前、扫描机制在后。**

- 「分支语义在前」体现在：
  - `event_interpretation_branch_variants._build_complex_executable_branch_variants` 先按种子边 + `_enumerate_complex_branch_paths` 枚举有序 pair `(L, R)`，并结合 `_pick_branch_continuation` / `_same_case_internal_member_node` 决定 sibling node 是否可桥接。
  - 输出 `_ExecutableBranchSet`（含 `boundary_branch_ids / event_branch_ids / branch_road_memberships / branch_bridge_node_ids`），后续 `_materialize_prepared_unit_inputs` 取这两条边界 branch 作为 `boundary_branch_a / boundary_branch_b`，并各自合并 road geometry 得到 `branch_a_centerline / branch_b_centerline`。
- 「扫描机制在后」体现在：
  - 真正物化候选空间的是 `_event_interpretation_core._materialize_prepared_unit_inputs` 中的 `_collect_pair_slice` 循环：以 `axis_origin_point + scan_axis_unit_vector` 沿轴扫描，每个 step 用 `_build_event_crossline + _build_between_branches_segment` 在两条 branch centerline 之间切一个 slice，buffer 后并集得到 `pair_local_middle_geometry`。
  - 然后 `pair_local_middle.buffer(2.5m) → pair_local_structure_face`、`structure_face.buffer(4m) → pair_local_region`，并都与 `patch_drivezone_union` 取交。
- 因此候选空间的「外形」由 `(L, R)` centerline 决定（每个 slice 端点压在 A/B 上），但「填充方式」是沿轴扫描而不是「分支线 Minkowski / 走廊并集」。这与你设想的「分支之间直接构成候选空间」语义大体一致，但实现路径仍依赖 forward 扫描器 + 横切器。

---

## 2. 仓库需求现状 vs 你的理解

| 你的诉求 | 仓库源事实 | 一致性 |
|---|---|---|
| (1) 两条分支构成候选空间 | `INTERFACE_CONTRACT §3.4 L140-L153`、`§3.5`「候选空间必须由当前 unit 的两条边界 branch (L, R) 及其合法 continuation 物化」；`architecture/04 §3` 重述 | 一致 |
| (2) 可跨同路口 sibling node 追溯分支 | `INTERFACE_CONTRACT §3.4 L147`「以当前 representative node 为锚点起算，但允许沿当前 unit 的同一 pair-middle 关系跨 same-case sibling internal node 延伸」；`architecture/06 §3.4(A)` | 一致 |
| (3) 分支最长不超过 200m | 仓库 Step2 §3.2 / Step3 §3.3 chain augmentation 都明确 200m；Step4 §3.4 仅写「扫描长度沿用原 Step4 硬上限」未写出具体米数 | **不一致**：Step4 文档未把 200m 显式列入候选空间硬上限 |
| (4) 分支距离太远的结束条件 | 仓库未写出「分支间距上限」类阈值；只在 §3.4 L148-L153 提到「L'/R' 之间不能夹入其他 road / pair-middle 关系失效就停」 | 与你「尚无明确阈值」的判断一致；但仓库的停机条件是「拓扑/角度」语义，不是「米距」语义 |

补充：

- `INTERFACE_CONTRACT §3.4`（约 180 行单段）与 `architecture/04 §3`（约 100 行）已经被 `2026-04-22-t04-divmerge-virtual-polygon-deep-audit.md` 标为「双源事实近重复」，候选空间语义就在这段重复区里。任何只改一边都会触发 `AGENTS.md §1.1` 风险。
- `§3.5` 冻结了 8 个 real-case 的 boundary pair，是当前候选空间正确性的事实基线，本次审计的「实现差异」必须以是否能稳定复现这些 pair 为准。

---

## 3. 代码实现 vs 你的理解

| 维度 | 你的理解 | 代码现状 | 评价 |
|---|---|---|---|
| 候选空间承载体 | (L,R) 之间区域 | `pair_local_middle_geometry` = 沿轴扫描的 slice 并集；`pair_local_structure_face` = `middle.buffer(2.5m)`；`pair_local_region` = `face.buffer(4m)` | 大方向一致，但实际是「轴扫 + 横切」而非「分支走廊」 |
| 横切端点压在分支上 | 是 | `_build_between_branches_segment` 把 crossline 切到 `branch_a / branch_b` centerline 上；当 `pair_scan_truncated_to_local=True` 时若任一侧未命中即丢弃该 slice | 一致 |
| 分支可跨 sibling node 延续 | 是 | `_enumerate_complex_branch_paths` 受控游走；`_same_case_internal_member_node` 判断；`MAX_COMPLEX_BRANCH_CONTINUATION_HOPS = 6`、`MAX_COMPLEX_BRANCH_PATH_VARIANTS_PER_SEED = 6`、`MAX_COMPLEX_BRANCH_SET_VARIANTS = 24` | 一致；但跳数 6 + 角度 `CHAIN_CONTINUATION_MAX_TURN_DEG=55°` 没在文档里冻结 |
| 分支 ≤ 200m | 200m | `EVENT_REFERENCE_SCAN_MAX_M = 140.0`；实际 `hard_limit_m = min(140, max(20, patch_size_m * 0.45))`；步长 `PAIR_LOCAL_SCAN_STEP_M = 4.0`；连续未命中 `PAIR_LOCAL_SCAN_STOP_MISS_COUNT = 4`（≈16m）即停 | **不一致**：硬上限 140m，远低于 200m，且与 Step2/Step3 的 200m 不齐；patch 较小时还会再被压到 `patch_size_m * 0.45` |
| 分支太远停机 | 期望有 | 仅隐式：`EVENT_CROSS_HALF_LEN_MAX_M = 130.0` 决定 crossline 最大半长（≈260m 间距上限）；超过则 `_build_between_branches_segment` miss → 4 次连续 miss 后停 | **缺显式米距阈值**；目前是几何副作用，不是用户可读阈值 |
| 单向延伸（不反向追溯） | 期望 | 实现上 `_collect_pair_slice` 在 `(+1, -1)` 两个方向各扫一遍，再用 `_safe_normalize_geometry(unary_union(...)).area` 选「面积/步数最大」的方向作为正式方向 | **语义不一致**：契约 §3.4 L145「合法延续方向确定后只能单向延伸」是「先定方向再扫」；代码是「两向都扫再挑赢家」。结果上常常对，但在 L/R 不对称、轴向偏移的 case 里会偏向几何更宽松的一侧 |
| L'/R' 之间不能夹入其他 road | 期望硬约束 | 由 `variant_ranking._pair_interval_variant_metrics_from_data` 计算 `inside_count / gap_penalty_x10`：判断的是 boundary branch terminal angle 是否落在两条 seed angle 的「角度小弧」内。属于**角度近似**，不是几何上的「中间是否真有 road 几何穿过」 | 与契约文字（「不夹入其他 road」）存在弱化：角度内不等于几何上无穿越 |
| 节流到 patch | – | `pair_local_drivezone_union` / `pair_local_scope_roads` / `pair_local_scope_rcsd_*` 均按 `pair_local_region` 做 `_filter_*_to_scope`，pad 用 `PAIR_LOCAL_SCOPE_PAD_M=10` / `PAIR_LOCAL_RCSD_SCOPE_PAD_M` 裁剪 | 行为合理，但当 scope 过窄时会落入 `pair_local_scope_roads_empty` / `pair_local_middle_missing` 的 degraded fallback，并把候选空间退化成 `axis_centerline.buffer(10m) ∪ representative_node.buffer(10m)`。这种「静默退化」在用户口径下相当于「失去候选空间」，但代码只标 `degraded_scope_reason`，不会强制 FAIL |

---

## 4. 还需要审计的内容（建议优先级）

1. **P0｜Step4 扫描上限是否要对齐到 200m**
   - 决定权在你。两种修法：把 `EVENT_REFERENCE_SCAN_MAX_M` 提升到 `200.0`，并同步删掉 `patch_size_m * 0.45` 的隐式压制；或在 §3.4 文档里把 140m 显式写下来并解释为何与 Step2/Step3 的 200m 不一致。
2. **P0｜「分支太远」的显式阈值**
   - 当前依赖 `EVENT_CROSS_HALF_LEN_MAX_M=130` 隐式触发 miss；建议引入 `PAIR_LOCAL_BRANCH_SEPARATION_MAX_M`（用户可调），超过即上浮 `STEP4_REVIEW` 或 `STEP4_FAIL`，并落审计字段（如 `pair_local_summary.branch_separation_m / stop_reason`）。
3. **P0｜单向 vs 双向扫描语义**
   - 复核 §3.4 L145「单向延伸」的真实意图。如果保留「双向择优」，文档需要显式说明；如果坚持「单向」，需要在 `_collect_pair_slice` 入口先用 `(L, R)` 的 incoming/outgoing 角色决定唯一方向，禁掉反向桶。
4. **P1｜「L'/R' 之间不夹入其他 road」是否真的几何级 gate**
   - 现在是 angular `_pair_interval_variant_metrics_from_data` 近似。建议加一道几何 gate：用 `(L, R)` 的合法 continuation 几何 + scan envelope 做 `intersects(other_road)` 检查；命中即不允许把该 pair 列入候选 variant。
5. **P1｜chain continuation 跳数与角度阈值入档**
   - `MAX_COMPLEX_BRANCH_CONTINUATION_HOPS=6 / MAX_COMPLEX_BRANCH_PATH_VARIANTS_PER_SEED=6 / MAX_COMPLEX_BRANCH_SET_VARIANTS=24 / CHAIN_CONTINUATION_MAX_TURN_DEG=55 / CHAIN_CONTINUATION_MIN_MARGIN_DEG`，全部未在 §3.4 出现。建议固化为契约层硬阈值，避免实现侧静默漂移。
6. **P1｜degraded_scope 永不 FAIL 的副作用**
   - 当 `pair_local_middle_missing` 触发 fallback（用 `axis_centerline.buffer(10m) ∪ node.buffer(10m)` 当结构面）时，等价于丢失候选空间，但只产 `STEP4_REVIEW`。需要决定是否把它升 `STEP4_FAIL`，并冻结 §3.5 的 real-case 是否会受影响。
7. **P2｜§3.4 vs architecture/04 §3 双源近重复**
   - 已被 `2026-04-22-t04-divmerge-virtual-polygon-deep-audit.md` 列为风险。建议把候选空间规则集中到 `INTERFACE_CONTRACT.md §3.4`，`architecture/04 §3` 只保留「为什么」与互引，避免下一轮改一边触发停机。
8. **P2｜§3.5 冻结 case 的回归覆盖**
   - 8 个 real-case（`760213 / 785671 / 857993 / 987998 / 17943587 / 30434673 / 73462878` 等）需要在改任意阈值时跑一遍 `tests/modules/t04_divmerge_virtual_polygon/test_step14_real_*`，确保 boundary pair 不漂移。
9. **P2｜reverse / structure-mode 是否真的「不扩边界」**
   - 契约要求 reverse 只在已确定 `(L, R)` 内活动；需要从 `event_interpretation_selection` / `_runtime_step4_kernel*` 反查一遍是否存在反向追溯路径。

---

## 5. 关键文件指针（便于下钻）

- 边界 branch 与 continuation：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/event_interpretation_branch_variants.py`
  - `_enumerate_complex_branch_paths` / `_pick_branch_continuation` / `_same_case_internal_member_node`
  - 常量：`MAX_COMPLEX_BRANCH_CONTINUATION_HOPS=6`（L27）、`MAX_COMPLEX_BRANCH_PATH_VARIANTS_PER_SEED=6`（L28）、`MAX_COMPLEX_BRANCH_SET_VARIANTS=24`（L29）
  - 角度 gate：`_pick_branch_continuation` L87-L121
  - 多路枚举主体：L161-L273
- 候选空间物化（轴扫 + 横切 + 双向择优）：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py`
  - `_materialize_prepared_unit_inputs` 内部 L919-L1091
  - 常量：`PAIR_LOCAL_SCAN_STEP_M=4.0`、`PAIR_LOCAL_SCAN_STOP_MISS_COUNT=4`、`PAIR_LOCAL_SLICE_BUFFER_M=2.5`、`PAIR_LOCAL_REGION_PAD_M=4.0`、`PAIR_LOCAL_SCOPE_PAD_M=10.0`、`PAIR_LOCAL_THROAT_RADIUS_M=10.0`（L83-L89）
- 扫描硬上限与转角阈值：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_core.py`
  - `EVENT_REFERENCE_SCAN_MAX_M=140.0`（L92）
  - `CHAIN_CONTINUATION_MAX_TURN_DEG=55.0`（L101）
  - `EVENT_CROSS_HALF_LEN_*`（L111-L116）
- 「中间不夹其他 road」近似：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/variant_ranking.py`
  - `_pair_interval_variant_metrics_from_data` L94-L141

---

## 6. 后续动作建议

如果确认上面 P0/P1 的偏差需要落代码或落文档，下一步顺序建议：

1. 先把「200m 对齐」与「分支太远阈值」这两条写进 `INTERFACE_CONTRACT.md §3.4`；
2. 同步收敛 `architecture/04 §3` 的重复段落，避免触发 `AGENTS.md §1.1`；
3. 再回来调实现侧常数（`EVENT_REFERENCE_SCAN_MAX_M / 单向扫描入口 / 显式分支间距阈值`）；
4. 改完跑一遍 §3.5 冻结的 8 个 real-case 回归，确认 boundary pair 不漂移。
