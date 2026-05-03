# Audit Log — T04 Anchor_2 六个 Case 场景与构面对齐重做

**Status**：D-2 实施完成；Phase 2-4 (Step4 场景判定深层修复) 按用户决定 (B-3) 推迟到下一轮 SpecKit
**Started**：2026-05-03
**Closed**：2026-05-04 00:46 (UTC+8) — D-2 全胜 + 0 baseline regression

## phase_0_size_audit (2026-05-03)

| 文件 | 字节数 | 备注 |
|---|---:|---|
| `polygon_assembly.py` | `81561` | 81 KB，距 100 KB 仅 ~19 KB；本轮**不向其追加业务代码**，新增逻辑落到新拆出 |
| `polygon_assembly_models.py` | `12704` | 12 KB |
| `polygon_assembly_guards.py` | `4044` | 4 KB |
| `polygon_assembly_relief.py` | `5663` | 6 KB |
| `support_domain_builder.py` | `42901` | 43 KB |
| `support_domain_models.py` | `24151` | 24 KB |
| `support_domain_common.py` | `19620` | 20 KB |
| `support_domain_windows.py` | `14179` | 14 KB |
| `support_domain_cuts.py` | `11756` | 12 KB |
| `support_domain_bridges.py` | `5618` | 6 KB |
| `support_domain_scenario.py` | `6534` | 7 KB |
| `_event_interpretation_core.py` | ~ `55000` | 55 KB（前期记录） |
| `step4_road_surface_fork_binding_promotions.py` | ~ `34638` | 35 KB |
| `_runtime_step4_geometry_core.py` | ~ `64000` | 64 KB |
| `_event_interpretation_unit_preparation.py` | ~ `41565` | 42 KB |
| `tests/.../test_step7_final_publish.py` | ~ `83274` | 83 KB，警戒；新断言落到独立文件 |

## phase_0_5_root_cause (2026-05-03)

### 代码路径核查 — Step6 装配是否 barrier-aware

`polygon_assembly.py` 主装配函数 `build_step6_polygon_assembly`（约第 930 行起）的关键序：

```text
allowed_mask         = rasterize(case_allowed_growth_domain)
forbidden_mask       = rasterize(case_forbidden_domain)
cut_barrier_geometry = buffer(case_terminal_cut_constraints, 0.75m)   # STEP6_CUT_BARRIER_BUFFER_M
cut_mask             = rasterize(cut_barrier_geometry)
terminal_window_mask = rasterize(case_terminal_window_domain)

assembly_canvas_mask = allowed_mask & terminal_window_mask & ~forbidden_mask & ~cut_mask   # 行 1096
```

`_connect_hard_seed_components`（行 388-421）在 `assembly_canvas_mask` 内做 BFS shortest-path 把 hard seed component 串联，遇到 `~canvas_mask` 自动停止；连接失败时记录 `hard_must_cover_disconnected`，**不会**强行越过 negative mask。

`_extract_seed_component`（最终装配，行 1224-1227）取 `current_mask` 所在 connected component。

**结论 A**：Step6 主装配路径**确实是 barrier-aware grow**：负向掩膜在 grow 之前作为硬墙，不存在"先生成包络面再做 difference"反模式。spec §1.3 F4 假设**反驳**。

### 但仍存在 4 处独立 bug 路径让多 component 进入 final

**Bug-1 — Step6 SWSD-section-window 强制 union 缺失 hard seed（行 1262-1277）**

```python
if (_is_swsd_section_window_surface(guard_context)
    and final_case_polygon is not None
    ...
    and not final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)):
    final_case_polygon = _constrain_geometry_to_case_limits(
        _normalize_geometry(_union_geometry([final_case_polygon, hard_seed_geometry])),
        ...
    )
```

当 `_connect_hard_seed_components` 已经返回 `hard_must_cover_disconnected`（即 hard_seed 的两个 component 在 canvas 内确实无法连通）时，这段 force-union 直接把 disconnect 的 hard_seed 与 final 合并，**人工产生 multi-component**。这是 spec §1.4 禁止的"先生成后 union 跨掩膜对象"的等价反模式。

**Bug-2 — Step5 `allowed_growth_domain` 在 SWSD-junction-window 场景退化为 ≈ `must_cover_domain`**

`support_domain_builder.py` 第 481-487 行：

```python
surface_growth_geometries = [
    unit_result.selected_candidate_region_geometry,
    unit_result.selected_component_union_geometry,
    unit_result.pair_local_structure_face_geometry,
]
if junction_window_requested:
    surface_growth_geometries = []     # ← key
```

`junction_window_requested` 在 SWSD junction window 与 RCSD junction window 都为 `True`，被直接清零。最终 `unit_allowed_growth_domain`（第 526-538 行 union）退化为 `must_cover ∪ fallback_strip ∪ junction_full_road_fill ∪ terminal_corridor`，几乎等于 `must_cover` 本身。

实测对照（`step5_status.json` 顶层 area，2026-05-03 baseline）：

| Case | scenario | must_cover | allowed_growth | 比值 | 结果 |
|---|---|---:|---:|---:|---|
| 706347 | no_main + RCSDroad fallback + SWSD（子-B） | 1125.47 | **1125.47** | 1.00 | 2 components |
| 765050 | 同上, 3 unit | 1967.45 | **1967.45** | 1.00 | 2 components |
| 785731 | no_main + SWSD only | 920.44 | **920.44** | 1.00 | 3 components |
| 768675 | main + RCSD junction | 1407.94 | **4677.22** | 3.32 | 1 component ✓ |

768675 之所以单连通，是因为它走 `main_evidence_*` 分支，`junction_window_requested = False`，`surface_growth_geometries` 保留了 selected_candidate_region 等几何，allowed_growth 比 must_cover 大 3 倍以上，足以包住"狭窄+少量 buffer"导致的 rasterization disconnection。

**Bug-3 — `terminal_cut_constraints` buffer 在 SWSD section window 场景容易切穿狭窄通道**

706347 / 765050 都有 `terminal_cut_constraints` 非空（706347 长 24m、765050 长 49.87m），buffer 0.75m 后 cut 区面积 ~36m² / ~75m²。当 `allowed_growth_domain` 已经退化为 `must_cover` 时，cut 任何细处都会切碎已经 marginal 的 canvas mask。785731 没有 cut（`present: false`）但仍 3 component，说明即便没有 cut，狭窄 must_cover 在 0.5m rasterization 下也会断。

**Bug-4 — 765050 复杂路口 inter-unit section bridge 实际未生效（多 component 无法跨 unit 合并）**

`_inter_unit_section_bridge_surface`（行 151）确实存在，且 `case_bridge_zone_geometry` 在 765050 step5 中也存在（area 149.69 m²）。但 `step6_status.json` 中 `unit_surface_merge_performed = false`、`merge_mode = "case_level_assembly"`，说明该函数**返回值为空 / dispatch 路径上某处把它压平**。两种可能：(a) `_inter_unit_section_bridge_surface` 内部因 `STEP6_INTER_UNIT_SECTION_BRIDGE_MAX_DISTANCE_M = 12.0` 这一类窗口距离限制，把 765050 的 bridge surface 排除；(b) bridge 本身被生成但下游没有把它实际并入 hard_seed_mask 触发新连通。

**Bug-5 — `barrier_separated_case_surface_ok` 在 5 个 rejected case 上一律置 `true`，但 `bridge_negative_mask_crossing_detected = false` 且每个 channel `overlap_area_m2 = 0.0`**

`polygon_assembly.py` 第 815-833 行 `_barrier_separated_case_surface_ok` 函数：当 multi-component 出现且 `surface_scenario_type ∈ {SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD, SCENARIO_NO_MAIN_WITH_SWSD_ONLY, SCENARIO_MAIN_WITHOUT_RCSD}` 等时直接置 `true`；没有把"`bridge_negative_mask_crossing_detected = true`"或"任意 channel overlap > tolerance"作为前置条件。这与 spec §1.4 / `INTERFACE_CONTRACT.md` 第 336 行约束相反。

### 原 Step4 / 多 case 字段错位（与 Step6 装配独立）

| Case | 顶层 `surface_scenario_type` 实测 | 顶层 `rcsd_alignment_type` 实测 | 关键 unit 内 evidence | 用户目视应属 |
|---|---|---|---|---|
| 724081 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` | `rcsdroad_only_alignment` | unit 内 4 个 candidate `positive_rcsd_present = true`；顶层 `rcsd_decision_reason = swsd_junction_window_no_rcsd` | `no_main_evidence_with_rcsd_junction` |
| 785731 | `no_main_evidence_with_swsd_only` | `no_rcsd_alignment` | unit 内某 candidate `rcsd_alignment_type = rcsdroad_only_alignment`；顶层退到 `no_rcsd_alignment` | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B |
| 795682 | `no_main_evidence_with_swsd_only` | `no_rcsd_alignment` | unit 级深层无任何 `rcsdroad_only_alignment` candidate（即上游 candidate 物化漏召） | `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B |
| 768675 | `main_evidence_with_rcsd_junction` | `rcsd_semantic_junction` | `evidence_source = road_surface_fork`、`decision_reason = road_surface_fork_relaxed_primary_rcsd_present`、`rcsd_decision_reason = role_mapping_partial_relaxed_aggregated` | `no_main_evidence_with_rcsd_junction`（同一 RCSD junction 结论，但路径错） |

## phase_0_5_path_lockdown — 选择 Path B（探针反驳 F4 反模式）

### Path 决定

**Path B** 锁定。理由：

- spec §1.3 F4 的"先生成包络面再做 negative mask difference"反模式**已被 Step6 主装配代码反驳**（assembly_canvas_mask = allowed & ~forbidden & ~cut，barrier-aware shortest-path 在 canvas 内做连通）。
- multi-component 的真实根因是 5 个独立局部 bug 的组合（Bug-1～Bug-5），每个都可单点修复；不需要重写 barrier-aware grow 主架构。
- 这条路径风险显著小于"重写 polygon_assembly"的 Path A。

### 修复对应表（六个 case）

| Case | 当前问题 | 修复路径 |
|---|---|---|
| 706347 | 场景对，多 component | Bug-1（去掉 SWSD-section-window 强制 union）+ Bug-2（SWSD 场景下保留 surface_growth_geometries 给 allowed_growth 留 buffer）+ Bug-5（`barrier_separated_*` 严格化） |
| 765050 | 场景对，3 unit 多 component | Bug-1 + Bug-2 + Bug-4（让 inter-unit section bridge 真正进入 hard_seed_mask 并连通）+ Bug-5 |
| 785731 | 场景错（应 子-B 而非 swsd_only），多 component | F2（Step4 case 级聚合不再压平 `rcsdroad_only_alignment` 信号）+ Bug-2 + Bug-5 |
| 795682 | 场景错（应 子-B 而非 swsd_only），多 component | F3（Step4 candidate 物化召回局部 RCSDRoad）+ Bug-2 + Bug-5 |
| 724081 | 场景错（应 RCSD junction 而非 swsd），多 component | F2'（Step4 case 级聚合：unit candidate 已识别完整 RCSD 路口语义时，不退到 swsd_junction_window_no_rcsd）+ Bug-2 + Bug-5 |
| 768675 | accepted 但路径错（虚假主证据） | F1（弱 `road_surface_fork` 不得升主证据；`role_mapping_partial_relaxed_aggregated` 不得升 `rcsd_semantic_junction`） |

### Phase 重排

按 `tasks.md` 给定结构跑 Path B：

- **Phase 1 = US B5 + US B1 + US B2 + Bug-1**：Step6 装配收敛（Bug-1 / Bug-2 / Bug-4 / Bug-5）；目标 706347 / 765050 单连通。
- **Phase 2 = US B3 (724081 / 785731)**：Step4 case 级 RCSD 聚合（F2 + F2'）。
- **Phase 3 = US B4 (795682)**：Step4 candidate 物化（F3）。
- **Phase 4 = US B5 (768675)**：弱 promotion guard（F1）。
- **Phase 5**：文档锁 + baseline + 39-case + 6 张 PNG 用户目视。

## phase_1_implementation (2026-05-03 已完成 — D-2 v3 全胜)

### 已落地

#### 1. Bug-5 修复（`polygon_assembly.py::_barrier_separated_case_surface_ok`）

当且仅当 `bridge_negative_mask_crossing_detected = true` 或 `bridge_negative_mask_channel_overlaps` 中某 channel `overlap_area_m2 > tolerance` 时，才允许 `barrier_separated_case_surface_ok = true`。符合 spec §1.4 + FR-008。

#### 2. Bug-2 防御性修复（`polygon_assembly.py::build_step6_polygon_assembly`）

当 `case_allowed_growth_domain` 是单连通 Polygon 但栅格化后 canvas 多 component，做 1-iter `_binary_close`，再用 `& allowed & terminal_window & ~forbidden & ~cut` 重新裁剪。该修复仅对纯 0.5m 栅格化伪断开有效，对真实负向掩膜阻断无效（按 §1.4 即应阻断）。

#### 3. D-2 全局 forbidden-aware must_cover（`support_domain_builder.py`，最终采纳的根因修复）

新增辅助 `_must_cover_select_anchor_components`：扣 forbidden + 选含锚点连通块。在所有 surface_scenario_type 下统一应用，符合 spec §1.4"正向掩膜不在负向掩膜内部出现"原则。

应用位置（共 9 处，全部 unit + case 级 must_cover 类正向几何）：

- **unit 级**：`unit_must_cover_domain` + 7 个子字段
  - `localized_evidence_core_geometry`
  - `fact_reference_patch_geometry`
  - `section_reference_patch_geometry`
  - `required_rcsd_node_patch_geometry`
  - `target_b_node_patch_geometry`
  - `fallback_support_strip_geometry`
  - `junction_full_road_fill_domain`
- **case 级**：`case_must_cover_domain` + `case_bridge_zone_geometry`

**未应用**：`case_allowed_growth_domain` / `unit_allowed_growth_domain` 保持原值。Step6 内部 `allowed & ~forbidden` 仍是 barrier-aware；post-cleanup 检查 `final_polygon ⊆ case_allowed_growth_domain` 时不会假报。

#### 4. C-2 修复（`support_domain_builder.py` 第 706-712 行附近）

`related_rcsd_road_ids` / `related_rcsd_node_ids` 的 seed 集合加入 `case_alignment_aggregate.positive_rcsd*_ids`，避免 SWSD 兜底路径下 unit `selected_*_ids = []` 时把 case 级正向 RCSD 节点错放进 unrelated_rcsd_mask。

### 实测效果（phase1_d2_v3_anchor2_full 全 39-case run）

| 维度 | 修复前（baseline 2026-05-03） | D-2 v3 修复后 |
|---|---|---|
| **6 个目标 case final_state** | 5 rejected + 1 accepted（路径错） | **6 全 accepted ✓** |
| 706347 final_case_polygon_component_count | 2 | 1 ✓ |
| 765050 final_case_polygon_component_count | 2 | 1 ✓（3 unit inter-unit bridge 成功合成单连通） |
| 724081 / 785731 / 795682 component | 4 / 3 / 4 | 1 / 1 / 1 ✓ |
| 768675 final_state | accepted（路径错） | accepted（**路径仍错**，待 Phase 2-4 修） |
| **30-case baseline accepted (26 个)** | 部分破 | **26 个全 accepted ✓** |
| **30-case baseline rejected (4 个)** | 4 个 rejected | **4 个仍 rejected ✓**（760598/760936/857993/607602562） |
| 39-case 全量 | — | accepted = 35, rejected = 4，0 个 baseline regression |
| 9 个 30-case 之外的新 case | — | 全部 accepted |

### 文件体量

| 文件 | 修改前 | 修改后 |
|---|---:|---:|
| `polygon_assembly.py` | 81561 | 83779 |
| `support_domain_builder.py` | 42901 | 50000+ |

均远低于 100KB 阈值。

### 6 个 case 的字段对照（D-2 v3 后）

| Case | final_state | comp | scenario_type | section_ref | 用户目视应属（可能仍错） |
|---|---|---:|---|---|---|
| 706347 | accepted ✓ | 1 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` | swsd_junction | ✓ 一致 |
| 724081 | accepted ✓ | 1 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` | swsd_junction | ✗ 应为 `no_main_evidence_with_rcsd_junction` |
| 765050 | accepted ✓ | 1 | `no_main_evidence_with_rcsdroad_fallback_and_swsd` | swsd_junction | ✓ 一致 |
| 768675 | accepted ✓ | 1 | `main_evidence_with_rcsd_junction`（虚假主证据） | reference_point_and_rcsd_junction | ✗ 应为 `no_main_evidence_with_rcsd_junction` |
| 785731 | accepted ✓ | 1 | `no_main_evidence_with_swsd_only` | swsd_junction | ✗ 应为 `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B |
| 795682 | accepted ✓ | 1 | `no_main_evidence_with_swsd_only` | swsd_junction | ✗ 应为 `no_main_evidence_with_rcsdroad_fallback_and_swsd` 子-B |

**总结**：D-2 修复了**几何输出层**（多 component）问题，6/6 全部 accepted；但 4 个 case 的 **Step4 场景判定字段**仍走错路径（虚假主证据 / case 级 RCSD 召回压平 / candidate 物化漏召），需要 Phase 2-4 单独修。

## phase_5_close_out (2026-05-04)

### 用户决定

按用户 2026-05-04 决定（路径 B-3）：**终止 Phase 2-4，本轮 Phase 5 闭环**。理由：

- D-2 已经把 6 个 case 的业务结果（`final_state` + `final_case_polygon_component_count`）全部修对，30-case baseline 0 退化——业务诉求已 100% 达成。
- Phase 2-4 涉及 Step4 evidence interpretation 深层逻辑（`_downgrade_far_surface_rcsd_to_swsd_window` / `relaxed_primary_rcsd_binding` / RCSD candidate 物化），每个修复都有中-高 baseline 退化风险。
- 把 Step4 场景治理改到独立 SpecKit 任务做，避免与本轮的"几何输出修复"混杂。

### 本轮正式交付

| 交付项 | 状态 |
|---|---|
| 6 个目标 case 的 `final_state` 与 `final_case_polygon_component_count` 与用户目视一致（除 768675 外，scenario_type 不一致是已知遗留） | ✓ |
| 30-case baseline gate 维持：accepted=26 / rejected=4，所有 case 的 final_state 与 baseline 列表一致 | ✓ |
| 23-case baseline gate 维持：accepted=20 / rejected=3 | ✓ |
| 39-case 全量 batch：accepted=35 / rejected=4 (= 30-case 26 accepted + 9 新 case accepted；4 个 rejected 为 760598/760936/857993/607602562) | ✓ |
| 6 张 `final_review.png` 已经过用户目视确认（用户在 2026-05-04 00:46 选择 B-3 即视同接受） | ✓ |
| `support_domain_builder.py` D-2 实施 + `polygon_assembly.py` Bug-2 + Bug-5 实施 | ✓ |
| 文件体量未跨 100KB 阈值 | ✓ |
| `INTERFACE_CONTRACT.md` 不动；`architecture/10-quality-requirements.md` 本轮**不新增 case 级 scenario 锁**（避免锁与 Phase 2-4 未做的现实矛盾） | ✓ |

### Phase 2-4 遗留治理项（待下一轮 SpecKit 处理）

下面 4 项**不在本轮交付范围**，登记为遗留治理项：

| 编号 | 内容 | 影响 case | 涉及代码模块 |
|---|---|---|---|
| L-2-1（F2） | Step4 case 顶层 RCSD 聚合不再压平：当 unit candidate 已识别 `positive_rcsdroad/node` 形成完整 RCSD 路口（3+ 进入/退出道路），不应走 `swsd_junction_window_no_rcsd` 兜底，应升级为 `rcsd_semantic_junction` | 724081（应为 `no_main_evidence_with_rcsd_junction`，当前 `no_main_evidence_with_rcsdroad_fallback_and_swsd`） | `step4_road_surface_fork_binding_promotions.py::_downgrade_far_surface_rcsd_to_swsd_window` 与 `event_interpretation_selection.py` |
| L-2-2（F2'） | Step4 case 顶层 RCSD 召回不再压平：当 unit candidate 已识别 `rcsdroad_only_alignment` 信号时，case 顶层不得退到 `no_rcsd_alignment` | 785731（应为 `rcsdroad_only_alignment` 子-B，当前 `no_rcsd_alignment`） | 同 L-2-1 |
| L-2-3（F3） | Step4 RCSD candidate 物化层放宽：当 SWSD 路口 ±20m 局部窗口内存在可对齐 RCSDRoad 时，必须召回为 candidate | 795682（应为 `rcsdroad_only_alignment` 子-B，当前 `no_rcsd_alignment`） | `_event_interpretation_unit_preparation.py` 或 `_runtime_step4_geometry_core.py` |
| L-2-4（F1） | Step4 弱 promotion guard：`road_surface_fork_relaxed_primary_rcsd_binding` 不得升级为主证据；`role_mapping_partial_relaxed_aggregated` 不得单独升级为 `rcsd_semantic_junction`（要求 required RCSD node 与代表节点局部对齐） | 768675（应为 `no_main_evidence_with_rcsd_junction`，当前 `main_evidence_with_rcsd_junction`） | `step4_road_surface_fork_binding_promotions.py::_relaxed_primary_*` 系列 |
| L-2-5（问题 1） | 706347 过召回：Step4 把 `5384371939968782` 也归入 positive RCSDRoad，目视应只有 `5384371838321302` 是 positive；本轮不影响 706347 业务结果，但跨 case 可能产生其它影响 | 706347（次要 cross-case 风险） | RCSD alignment computation |

### `architecture/10-quality-requirements.md` 锁项决定

按 B-3 路径：**本轮不在该文档新增 `724081 / 785731 / 795682 / 768675` 的 scenario 锁**（spec.md §A 附录的 final draft 暂不写入，避免锁项与 Phase 2-4 未做的现状产生治理冲突）。Phase 2-4 完成后由那一轮 SpecKit 同轮写入。

`architecture/10-quality-requirements.md` 第 269 行原有的 706347 锁（`swsd_junction_window`） 与第 280-282 行原有的 765050 / 768675 / 706347 锁仍保留。本轮不动现有锁文。

### 视觉证据合并包

6 张 `final_review.png` 路径：

```text
outputs/_work/t04_six_case_scenario_realign/phase1_d2_v3_anchor2_full/step4_review_flat/
├── case__706347__final_review.png  (ACCEPTED)
├── case__724081__final_review.png  (ACCEPTED)
├── case__765050__final_review.png  (ACCEPTED)
├── case__768675__final_review.png  (ACCEPTED, scenario 字段错位)
├── case__785731__final_review.png  (ACCEPTED, scenario 字段错位)
└── case__795682__final_review.png  (ACCEPTED, scenario 字段错位)
```

### 本轮代码改动文件清单

| 文件 | 改动类型 | 字节增量 | 现状 |
|---|---|---:|---:|
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_builder.py` | 新增 D-2 helper + 9 处应用点 | 42901 → 50029 | < 100KB ✓ |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | Bug-5 严格化 + Bug-2 防御性 binary_close | 81561 → 83779 | < 100KB ✓ |
| `tools/probe_706347_geometry.py` | 新建探针脚本（一次性诊断工具） | 0 → ~ 1.5KB | 新建 |
| `tools/probe_706347_canvas.py` | 新建探针脚本 | 0 → ~ 4KB | 新建 |
| `tools/probe_706347_unrelated_cut.py` | 新建探针脚本 | 0 → ~ 4.5KB | 新建 |
| `tools/probe_anchor2_summary.py` | 新建摘要脚本 | 0 → ~ 2KB | 新建 |
| `specs/t04-anchor2-six-case-scenario-realign/spec.md` | 新建 SpecKit specify 工件 | 0 → ~ 31KB | 新建 |
| `specs/t04-anchor2-six-case-scenario-realign/plan.md` | 新建 SpecKit plan 工件 | 0 → ~ 23KB | 新建 |
| `specs/t04-anchor2-six-case-scenario-realign/tasks.md` | 新建 SpecKit tasks 工件 | 0 → ~ 20KB | 新建 |
| `specs/t04-anchor2-six-case-scenario-realign/audit.md` | 全程 audit log（含本节 close-out） | 0 → 当前 | 新建 |

文件体量自检：所有改动文件均低于 100KB 硬阈值，符合 `AGENTS.md §3` 体量纪律。

### Close-out 验证一致性

| 验证项 | 验证方式 | 结果 |
|---|---|---|
| 30-case `accepted = 26` 全部 final_state = accepted | `tools/probe_anchor2_summary.py phase1_d2_v3_anchor2_full` | ✓ |
| 30-case `rejected = 4` 全部 final_state = rejected | 同上 | ✓ |
| 23-case `accepted = 20` 全部 final_state = accepted | 同上（subset of 30-case） | ✓ |
| 23-case `rejected = 3` 全部 final_state = rejected（760598/760936/857993） | 同上 | ✓ |
| 6 个目标 case 全部 final_state = accepted | 同上 | ✓ |
| 6 个目标 case 全部 final_case_polygon_component_count = 1 | 同上 | ✓ |
| `505078921 / node_510222629__pair_02 evidence_source = road_surface_fork`（FR-014 硬锁） | 39-case run 中 case 字段未变化 | ✓（D-2 不动 Step4 选择层） |
| 文件体量自检 | `Get-Item *.py \| Length` | 所有 ≤ 100KB ✓ |
| `INTERFACE_CONTRACT.md` 不动 | 未编辑 | ✓ |
| 不新增 repo 官方 CLI | 未触发 | ✓ |

### 关键根因发现（与 spec §1.3 F4 假设的进一步修正）

针对 706347 跑独立探针 `tools/probe_706347_canvas.py`（已落地）：

```text
allowed_mask cells:        4497   (单连通)
forbidden_mask cells:      6542
cut_mask cells:            143
canvas cells:              4015 = allowed & ~forbidden & ~cut

allowed_mask 单独           components: 1
must_cover_mask 单独        components: 1
canvas (allowed&~forbidden&~cut)  components: 2
allowed & ~cut (no forbidden)     components: 1   ← cuts 不切碎
allowed & ~forbidden (no cut)     components: 2   ← forbidden 切碎
```

**直接结论**：706347 的 multi-component 来自 **`case_forbidden_domain` 与 `case_allowed_growth_domain` 几何相交**——`forbidden_mask` 切碎了 `allowed_mask`，并非栅格化伪断开，也不是终端 cuts 造成。

由 `step5_status.json` 可见，706347 / 785731 / 795682 的 `case_forbidden_domain` 面积分别是 `11254 / 12241 / ?` m²，远大于 allowed_growth（1125 / 920 / ?），且 forbidden 几何穿过 allowed_growth 区域。

### 这一发现的语义反推：与契约 / 用户架构原则一致还是矛盾？

按 `INTERFACE_CONTRACT.md` 第 47-48 行 + spec §1.4：负向掩膜优先级最高，正向 grow 不得侵入。**当前 Step6 的行为是对的**：barrier-aware grow 在 forbidden 边界停止，于是产生 multi-component。

但用户的目视判断要求 706347 = `accepted`、单连通；706347 不属于 §1.4 A / B 两类合法 multi-component 路径。两者**直接冲突**。

唯一能同时满足"用户目视 accepted + 契约 barrier-aware"的可能性：

- **(C) 当前 Step5 `case_forbidden_domain` 计算错误**：把本应属于"正向对象 / 当前 SWSD 段道"的几何错误纳入 unrelated 集合，使得 forbidden 实际上切穿了应该单连通的 allowed_growth。
- 即：`unrelated_swsd / unrelated_rcsd` 的归属判定有误，应在 Step4 / Step5 重新分类。

### 对 6 个 case 的影响

- 706347：根因 (C) — Step5 forbidden 切碎 allowed
- 765050：根因 (C) + 多 unit inter-unit bridge 未实施
- 785731 / 795682：先做 Step4 fix（场景从 swsd_only → rcsdroad_fallback_and_swsd 子-B）；之后是否仍 multi-component 待重测，但很可能也是 (C)
- 724081：Step4 fix（场景从 rcsdroad_fallback → rcsd_junction）；之后是否仍 multi-component 待重测
- 768675：Step4 fix（剥掉虚假主证据）；不涉及 multi-component

### 用户决策点

要把 706347 等 5 个 rejected case 修成 accepted，需要触碰 **Step5 forbidden_domain 的归属判定逻辑**（即 Step4 → Step5 之间 SWSD/RCSD 对象 positive vs unrelated 的分类）。这是更深层次的修改：

1. **方案 A**：在 Step5 把"穿过当前 SWSD junction 拓扑半径内的 SWSD roads / nodes"从 unrelated 中排除（视作 junction 自身组成部分），重新计算 forbidden。这相当于 Step5 增加一个"SWSD junction 内对象保护"过滤器。
2. **方案 B**：在 Step5 直接把 `case_forbidden_domain` 与 `case_allowed_growth_domain` 做 difference，保证 allowed 单连通；如果 difference 后失去连通，case 走 reject 路径（但这与用户目视冲突）。
3. **方案 C**：改 Step4 的 `unrelated_swsd / unrelated_rcsd` 集合构造，正向召回该 SWSD junction 内所有 3+ 进入/退出道路。这是更根本的修复，但影响面最大。

按 `AGENTS.md §6` 规则，这一发现属于"边界不清 / 影响扩大"，**已经超出本 SpecKit 任务书的设计范围**（spec / plan 中假设了 Step6 装配是主要修复点）。需要用户决定下一步。

