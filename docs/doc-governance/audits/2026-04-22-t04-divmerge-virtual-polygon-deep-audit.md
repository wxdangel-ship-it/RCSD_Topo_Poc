# T04 `divmerge_virtual_polygon` 深度审计（2026-04-22）

> 本文件供 GPT / CodeX 作为下一轮优化任务的输入。仅审计结论，不含代码改动。
> 审计范围：`modules/t04_divmerge_virtual_polygon/*`、`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/*`、`tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py`。
> 审计前置：用户目视审计已确认"按当前正向召回 RCSD 节点，目视通过，结果正确；新出现的错误属于本阶段范围外，暂时忽略"。

## 0. TL;DR

| 维度 | 结论 |
|---|---|
| 文档规范性 | 完整度高，但存在双源事实近重复、章节裁剪未声明、契约 §3.4 单段过长、Acceptance 不可度量、输出 schema 不全等结构性问题 |
| 实现 vs 契约 | 主链路完成度高（Step1-Step4 + review），但存在 T02 私有 API 越界引用、`degraded_scope` 永不 FAIL、异常裸吞、`run_root` 误删风险 |
| 架构 / 体量 | `event_interpretation.py = 91298 bytes`（距 100KB 硬阈值不足 9KB，已构成下一轮 §1.4 停机风险）；`rcsd_selection.py = 67572 bytes`；测试单文件 67233 bytes，均需架构级拆分 |
| 跨域审计 | T02 跨模块依赖、性能与确定性、CRS / silent-fix、测试结构、治理同步、审计可追溯性均需补强 |

---

## 1. 需求文档的规范性与完整性

### 1.1 总体评估

T04 已具备 source-of-truth 形态，文件齐全：`AGENTS.md / README.md / INTERFACE_CONTRACT.md / architecture/01-06,10`。`INTERFACE_CONTRACT.md`（28.6KB）已经把 Step1-4 的语义、字段、冻结基线写得相当详细，超过同类模块平均水平。但"规范性"层面存在以下结构性问题。

### 1.2 必须给 CodeX 优化的具体不规范点

#### A. 双源事实之间出现近重复（强约束 §1.1 风险点）

`architecture/04-solution-strategy.md` 的 `### 3. Step4`（约 100 行）与 `INTERFACE_CONTRACT.md §3.4`（约 180 行）几乎是平行重述，违反 repo `AGENTS.md §1.1`（项目级源事实之间禁止冲突）的精神：任何一边修改未同步对侧，立即触发停机。

- `architecture/04-solution-strategy.md` L37-L160
- `INTERFACE_CONTRACT.md` L132-L312

**建议**：
- `04-solution-strategy.md` 改为只保留"为什么做这个 Solution / 与 T02/T03 的关系 / 关键 trade-off"，不再重述契约级规则
- `INTERFACE_CONTRACT.md` 保留全部稳定字段与语义清单
- 加显式互引：`架构文档不重复契约，详见 INTERFACE_CONTRACT.md §X`

#### B. arc42 章节缺失但未声明缺失原因

实际目录：

```
01-introduction-and-goals.md
02-constraints.md
03-context-and-scope.md
04-solution-strategy.md
05-building-block-view.md
06-step34-repair-design.md     # 非 arc42 标准章节
10-quality-requirements.md
```

缺 `07-deployment / 08-crosscutting / 09-decisions / 11-risks-and-debt`。本身可以接受（arc42 允许裁剪），但需要在 README 或 01 里**显式说明本模块当前裁剪了哪些章节**，否则审阅者无法判断"是有意裁剪还是治理缺失"。

#### C. `INTERFACE_CONTRACT.md §3.4` 单段过长

L132-L312 是单一无小节的长段，混合了：

- event unit 拆分规则（L134-L138）
- pair-local region 几何规则（L140-L160）
- candidate layering（L177-L180）
- 三层几何（L202-L206）
- 正向 RCSD 整套链路与 A/B/C 判级（L213-L274）
- 输出字段清单（L260-L271）
- 审计字段清单（L275-L281）
- ownership guard（L295-L301）

**建议**拆为：`§3.4.1 event unit 划分 / §3.4.2 候选空间 / §3.4.3 候选分层 / §3.4.4 正向 RCSD / §3.4.5 ownership / §3.4.6 字段输出与审计`。

#### D. Acceptance（§6）过于松散，缺可度量门槛

```text
1. repo 已存在 T04 正式模块文档面。
2. Step1-4 可对 case-package 运行并产出稳定文件集。
3. Step4 review overview / event-unit png / flat mirror / index / summary 可直接人工检查。
4. 本轮未进入 Step5-7，也未新增 repo 官方入口。
```

"可直接人工检查"不是可执行的验收门槛。**建议**补：

- 与 `tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py` 中冻结测试函数的 1-1 映射
- Anchor_2 baseline 上的 `STEP4_OK / REVIEW / FAIL` 数量门槛
- 当前正向 RCSD `A/B/C` 的目标分布

#### E. 输出 schema 不完整

- `§4.4` 列出 `step4_review_index.csv` **26 个最少列**，但 `outputs.REVIEW_INDEX_FIELDNAMES` 实际是 ~58 列（如 `positive_rcsd_present_reason / pair_local_rcsd_empty / local_rcsd_unit_kind / better_alternative_signal / shared_object_signal / focus_reasons / case_overview_path` 等）。多出来 30+ 列**未在契约中提及**，下游消费者不知道哪些是稳定字段哪些是临时审计。
- `step4_event_evidence.gpkg` **完全没有图层 schema**（CRS、layer 名、字段、几何类型、缺失语义），但代码已经在写。这是后续 Step5-7 接管的关键交接面。
- `step4_review_summary.json` 在 `§4.4` 列出 9 个键，但代码可能写更多键（如 `failed_case_ids / rerun_cleaned_before_write`）。

#### F. 冻结基线（§3.5 / §3.6）写进契约的副作用

把具体 case_id（`760213 / 17943587 / node_55353239` 等）和具体 road_id pair (`12557730 / 1112045`) 写入 `INTERFACE_CONTRACT.md` 是反常的：契约是"对外稳定的语义面"，case-level 冻结样本属于"回归 fixture"。这导致：

- 契约会因每次审计通过新样本而被改写，违反"契约稳定"承诺
- 读者无法快速判断"哪些是语义、哪些是 fixture 索引"
- 真正应该承担 fixture 角色的 `tests/test_step14_pipeline.py` 与契约出现两个并行 source-of-truth

**建议**把 §3.5 / §3.6 移到新文件 `architecture/11-frozen-baselines.md`，契约里只保留"冻结基线由 architecture/11 维护，回归门槛由 tests 维护"的引用。

#### G. 操作入口路径与 repo 治理冲突

`README.md` 默认路径用 `/mnt/e/...`（POSIX/WSL）：

```text
- 默认本地 case 根：`/mnt/e/TestData/POC_Data/T02/Anchor_2`
- 默认输出根：`/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_step14_batch`
```

而 repo 根 `AGENTS.md §7` 已经把"建立 path-conventions.md"列为治理缺口（实际 `docs/repository-metadata/path-conventions.md` 不存在）。本模块文档中没有任何"PowerShell 等价路径换算说明"，对 Windows 会话的操作者来说默认入口直接不可用。

#### H. 缺项

- 没有 `CHANGELOG.md` 或文档级 "last-updated" 头，无法看出契约近一次冻结时间
- 没有 `Step5-7 handoff 字段稳定性表`：哪些 T04 字段是 Step5 可以依赖的、哪些只是当前实现细节
- `STEP4_FAIL` 的下游语义没有写：是否会被 Step5-7 直接丢弃？是否要 republish？

---

## 2. 代码对应需求的完成情况

### 2.1 完成情况盘点

按 `architecture/05-building-block-view.md` 与 INTERFACE_CONTRACT 对照，T04 实现完成度高：

| 契约要求 | 文件 | 状态 |
|---|---|---|
| Step1 admission contract | `admission.py` | ✅ |
| Step2 patch-scoped local context | `local_context.py` | ✅（直接复用 T02 内核） |
| Step3 case coordination + unit-level skeleton 双层 | `topology.py / outputs.py:build_unit_step3_status_doc` | ✅ |
| Event unit 拆分（simple / multi / complex） | `event_units.py` | ✅ |
| `unit envelope` 显式输出 | `case_models.T04UnitEnvelope`、`event_interpretation._build_unit_envelope` | ✅ |
| pair-local region / structure_face / middle / throat | `event_interpretation._materialize_prepared_unit_inputs` L909-L1080 | ✅ |
| candidate 三层分层 | `event_interpretation._candidate_layer` | ✅ |
| 三层 ownership 几何 | `case_models.T04EventUnitResult` | ✅ |
| `fact_reference_point` vs `review_materialized_point` 拆层 | 同上 | ✅ |
| 正向 RCSD `pair_local → candidate_scope → local_unit → aggregated_unit → A/B/C` 链路 | `rcsd_selection.resolve_positive_rcsd_selection` | ✅ |
| `required_rcsd_node` 与 `A/B` 解耦 | `rcsd_selection._select_required_node_id` | ✅ |
| ownership guard（component / core / Δs） | `event_interpretation_selection._apply_evidence_ownership_guards` | ✅ |
| 单 Case 内重选（不直接 fail） | `event_interpretation_selection._select_case_assignment` | ✅ |
| review PNG / index / summary / flat mirror | `review_render.py / outputs.py` | ✅ |
| 程序内 runner（不新建 CLI） | `batch_runner.run_t04_step14_batch / run_t04_step14_case` | ✅ |

### 2.2 实现与需求之间的不合格 / 偏差

#### P1. T02 私有符号大量越界引用（高优先级）

T04 通过 `_` 前缀符号大量调用 T02 内部私有 API，违反 `architecture/02-constraints.md` 的"先把 unit-local 结构封装清楚再传入 T02"。`event_interpretation.py` 的 import 段：

```python
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    EVENT_REFERENCE_SCAN_MAX_M,
    _build_between_branches_segment,
    _build_event_crossline,
    _node_source_kind_2,
    _pick_cross_section_boundary_branches,
    _resolve_branch_centerline,
    _resolve_event_axis_branch,
    _resolve_event_axis_unit_vector,
    _resolve_event_cross_half_len,
    _resolve_scan_axis_unit_vector,
    _explode_component_geometries,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_event_interpretation import (
    _build_stage4_event_interpretation,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedRoad,
    _resolve_group,
)
```

`virtual_intersection_poc.py` 已是 990KB 的结构债（见 `code-size-audit.md`），任何拆分会同步打穿 T04。**建议**：

- 在 T02 内开放一个**对 T04 友好的 stable façade**（如 `t02_junction_anchor.stage4_public.py`），把这些 `_` 符号显式 re-export 为公共 API
- T04 这边只 import 公共 façade
- 把 façade 列入 `INTERFACE_CONTRACT.md` 跨模块依赖章节

#### P2. 文档与实现的输出字段集差异未闭环

- `step4_review_index.csv` 实际 ~58 列 vs 契约 §4.4 列表的 26 列；多出 30+ 列没有契约定义
- `step4_event_evidence.gpkg` 几何与图层完全无契约描述
- `T04EventUnitResult` 中存在 `event_reference_point` / `selected_divstrip_geometry` 等 alias property，契约中说明是 review alias，但**没有列出全部 alias 与 deprecation 时间点**

#### P3. degraded_scope 静默上浮 REVIEW，永不 FAIL

契约 §3.4 / 04-solution-strategy.md 规定"degraded_scope 至少上浮为 STEP4_REVIEW"，但 `_build_result_from_interpretation` 的实现是：

```python
if prepared.degraded_scope_reason:
    review_reasons.append(f"degraded_scope:{prepared.degraded_scope_reason}")
if fail_reasons:
    review_state = "STEP4_FAIL"
```

`degraded_scope_reason` 永远进 `review_reasons`、永不进 `fail_reasons`。哪怕"insufficient_local_scoped_branches + insufficient_local_scoped_divstrip + pair_local_middle_missing + pair_local_scope_rcsd_outside_drivezone_filtered" 四项同时命中，最坏也只会落 REVIEW。**建议**：

- 在 `degraded_scope_reason` 的每一类原因上明确"是否允许只 REVIEW"
- 对"几何已经退化到不可能给出有效证据"的组合，应被允许 / 强制升 FAIL

#### P4. 异常被批量吞掉

```python
# batch_runner.py
for spec in specs:
    try:
        case_bundle = load_case_bundle(spec)
        case_result = build_case_result(case_bundle)
        review_rows.extend(write_case_outputs(run_root=run_root, case_result=case_result))
    except Exception:
        failed_case_ids.append(spec.case_id)
```

裸 `except Exception` + 无 traceback 落盘，违反 repo `AGENTS.md §5` "审计可追溯性"。**建议**：

- 至少把 `traceback.format_exc()` 写到 `<run_root>/cases/<case_id>/_failed.json`
- `failed_case_ids` 在 summary 里有明确"此 case 因哪类异常落败"的可追溯链路

#### P5. `run_root` 已存在即 `shutil.rmtree`

```python
if run_root.exists():
    shutil.rmtree(run_root)
    rerun_cleaned_before_write = True
run_root.mkdir(parents=True, exist_ok=True)
```

`run_id` 默认由 `build_run_id("t04_step14_batch")` 生成，理论上每次唯一；但若调用方显式传入相同 `run_id` 或路径配置错误，会无声删除已有产出。当前没有"目录是否真的属于本工具产出"的 sanity check（如检查目录里是否有 `preflight.json`），存在数据丢失风险。

#### P6. Step1 准入与契约 §3.1 的 `kind=128` 准入路径未在 `admission.py` 显式可见

契约说 Step1 接受 `kind/kind_2 = 8 / 16 / 128`，但 `admission.py` 只调 `evaluate_stage4_candidate_admission` + `_is_stage4_supported_node_kind`，128 的准入语义完全埋在 T02 内部（再次回到 P1 的 T02 私有依赖问题）。从 T04 的源码无法独立审出"我是怎么承认 128 的"。

#### P7. 测试文件已逼近 100KB 软上限

`tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py = 67233 bytes`，已经是 67% 阈值，且 21 个测试函数有继续扩张趋势。`code-size-audit.md` 列举的 `test_virtual_intersection_poc.py 252KB` 就是同类 pattern 走到末路的结果。

---

## 3. 架构合理性 / 代码量 / 100KB 风险

### 3.1 当前体量速览

| 文件 | bytes | 与 100KB 距离 |
|---|---:|---:|
| `event_interpretation.py` | **91298** | **8.7KB（紧迫）** |
| `rcsd_selection.py` | 67572 | 32KB（中等） |
| `review_render.py` | 29514 | 70KB |
| `outputs.py` | 28168 | 72KB |
| `case_models.py` | 20398 | 80KB |
| `event_interpretation_branch_variants.py` | 18596 | 81KB |
| `event_interpretation_selection.py` | 18450 | 81KB |
| `review_audit.py` | 17875 | 82KB |
| `event_interpretation_shared.py` | 10704 | 89KB |
| 其余 | < 8KB | 充裕 |
| `tests/.../test_step14_pipeline.py` | 67233 | 32KB（中等） |

`event_interpretation.py` 距硬阈值 **不到 9KB**，下一轮如果继续在主文件加一个 `_materialize_*` / 大型 candidate 评估器就会触发 §1.4 停机。

### 3.2 `event_interpretation.py` 的真实结构债

虽然已经按 `building-block-view` 拆出 `_branch_variants / _selection / _shared / _ranking`，但主文件依然承担 7 大职责：

1. **Unit context 准备**（L98-L143）
2. **Branch / kind / scope 工具**（L146-L282）
3. **Candidate 物化辅助**（L284-L482）
4. **Review-side 几何 materialize**（L484-L573）
5. **Pair-local 几何与扫描**（L576-L1209，**单函数 `_materialize_prepared_unit_inputs` ~500 行**）
6. **Candidate pool / unit envelope / interpretation bridge**（L1285-L1762）
7. **Case 级编排**（L1794-L2030：`build_case_result`，**~240 行编排**）

**建议拆分方案**：

| 建议新文件 | 职责 | 估算体量 |
|---|---|---:|
| `event_interpretation_pair_local.py` | (5)：pair-local region/middle/structure_face/throat 构造、scope clip | ~30KB |
| `event_interpretation_candidates.py` | (3)+(6 中的 pool 构造)：candidate_summary / layer / pool / reference_point_from_region | ~20KB |
| `event_interpretation_materialize.py` | (4)：review-side geometry materialize | ~6KB |
| `event_interpretation_case_orchestrator.py` | (7)：build_case_result 全部编排 | ~14KB |
| `event_interpretation.py` | facade only：保留 `build_case_result` 作为对外入口 | ~6KB |

收益：单文件最大降到 ~30KB，且每个文件对应 architecture/05 中一个清晰职责。

### 3.3 `rcsd_selection.py` 的结构债

67KB 单文件，内容自然分 5 段：

1. 几何与节点小工具（L1-L260）
2. side-label / role-map（L345-L430）
3. `_LocalRcsdUnit` + `_unit_from_roads_and_node`（L433-L828）
4. `_AggregatedRcsdUnit` + `_build_aggregated_rcsd_units`（L484-L1078）
5. `PositiveRcsdSelectionDecision` + `resolve_positive_rcsd_selection`（L541-L1567）

`resolve_positive_rcsd_selection` 中包含 **4 段几乎重复的 ~50 行 "early-return decision"**（L1148-L1198 / L1244-L1295 / L1346-L1396 / L1409-L1459），区别只是 `positive_rcsd_present_reason / rcsd_decision_reason / 部分几何字段`。可抽 `_no_support_decision(...)` 工厂：每个 early-return 段缩到 5-8 行。粗估**节省 ~120 行（≈ 6KB）**，同时大幅提升可读性。

进一步建议拆 `rcsd_selection_local_unit.py` / `rcsd_selection_aggregated.py` / `rcsd_selection.py`（facade）。

### 3.4 `case_models.py` 的次级结构债

- `T04EventUnitResult` 当前 **60+ 字段**（L193-L336）
- `T04ReviewIndexRow` 当前 **~50 字段**（L360-L487），且 `to_csv_row` 平铺了所有字段

**建议**把 `T04EventUnitResult` 按语义聚合为子 dataclass：

- `RcsdEvidence`：所有 `selected_rcsdroad_ids / selected_rcsdnode_ids / *_rcsd_node*` 等
- `PairLocalGeometry`：所有 `pair_local_*_geometry`
- `OwnershipGeometry`：`selected_component_union_geometry / localized_evidence_core_geometry / coarse_anchor_zone_geometry`
- `RcsdAudit`：`positive_rcsd_audit / first_hit_*` 等

主类只保留 `spec / unit_context / unit_envelope / review_state` 等顶层骨架与组合的 sub-dataclass。这能在不动 `to_summary_doc` 的对外 schema 下，把 `case_models.py` 的语义复杂度降到可审。

### 3.5 治理同步缺口

- `docs/repository-metadata/code-size-audit.md` 的"审计日期 2026-04-14" 已经过期；当前 t04 的 `event_interpretation.py = 91KB` 未进表，违反 repo `AGENTS.md §3` "登记同步"约束的精神（虽然还未越过 100KB，但已构成 high-risk）。建议本轮提醒 CodeX 同步审计表，加一行 high-risk 预警。

---

## 4. 主动深度审计：以下还需要 CodeX 关注的内容

### 4.1 跨模块依赖与封装

- T04 私有越界引用 T02 至少 13 个私有符号（前文 P1）
- `local_context.py / topology.py / admission.py` 都是薄包装，内核全在 T02。等于 T04 把"模块化继承"承诺打了折扣
- **建议**在 `architecture/03-context-and-scope.md` 里补"跨模块依赖矩阵"：T04 用 T02 的哪些公共 API、哪些私有 API、风险等级

### 4.2 性能与确定性

- `event_interpretation_selection._select_case_assignment` 是 **指数级回溯**：每个 unit 7 选项（`MAX_CANDIDATES_PER_UNIT=6` + None），N 个 unit 即 7^N。若某 case 出现 5+ event units（multi-merge / multi-diverge 完全展开），即 7^5 = 16807 次冲突检查，每次还要做 shapely intersection。**建议**：
  - 在契约里给一个 N 的硬上限（如 N ≤ 6 时正式承认结果，N > 6 时上浮 REVIEW）
  - 或显式说"全量 Step4 之后做二次处理"承担这条 fallback
- `_build_aggregated_rcsd_units` 的并查集双重遍历 OK，但聚合后排序对 tie-break 未完全确定，`set` 遍历顺序在不同 Python 解释器下虽稳定但仍依赖插入顺序。**建议**显式 sorted() once more

### 4.3 GIS / 几何审计（repo AGENTS.md §5 GIS 强约束）

- **CRS**：`INTERFACE_CONTRACT.md §2.2` 写 EPSG:3857，但 T04 代码内部没有 CRS assertion，只在 case_loader / T02 内核侧隐式假设。建议加 CRS gate test
- **Silent fix**：代码大量 `geometry.buffer(1e-6).covers(...)` / `buffer(0)` 用法用于规避 shapely 数值毛刺，请审计每一处：
  - `1e-6` 是否会吞掉真正的拓扑错误？
  - `buffer(0)` 是否在某些 self-intersect Polygon 上会丢失分量？
- **几何语义可解释性**：`fact_reference_point` 的 "formation-side" 约束在代码里只是软选择（`_reference_point_from_region(reference_strategy="formation")`，先 nearest_points 再 representative_point）；契约说必须"更靠近 throat / representative node"，**建议**增加显式断言或 ratio 限值

### 4.4 测试结构审计

- 单文件 `test_step14_pipeline.py = 67KB / 21 函数`，**建议**按现有契约 §3 拆为：
  - `test_t04_step1_admission.py`
  - `test_t04_step2_local_context.py`
  - `test_t04_step3_skeleton.py`
  - `test_t04_step4_pair_space.py`
  - `test_t04_step4_evidence_and_reference.py`
  - `test_t04_step4_positive_rcsd.py`
  - `test_t04_step14_batch_io.py`
  - `test_t04_real_case_baselines.py`
- 所有 fixture 提到 `Path("/mnt/e/TestData/POC_Data/T02/Anchor_2")` 强依赖 WSL 路径，PowerShell 环境直接跑不通，等价于 OS-bound test
- 没看到对 `step4_event_evidence.gpkg` 的图层 schema test

### 4.5 文档治理同步

- `code-size-audit.md` 已过期（前述 3.5）
- `docs/repository-metadata/path-conventions.md` 仍是缺口
- `entrypoint-registry.md`：本轮契约说"未新增 repo 官方 CLI / 不更新 registry"，状态一致；但 `run_t04_step14_batch` 已经是事实上的程序内入口，**建议**至少在 registry 里加一行"模块内 runner，不计入官方 CLI"，避免后续被误升级

### 4.6 审计可追溯性

- `case_meta.json` 里写了 `case_root / input_paths`，但**没有写入数据集签名 / hash / mtime**，无法回溯审计当时的输入数据是哪个版本（如 Anchor_2 被覆盖后，已有的 run_root 对不上）
- `summary.json` / `preflight.json` 缺少代码版本号 / git SHA / 模块版本号
- `step4_audit.json` 的内容代码里有写但契约 §4.2 仅一行带过，没有列出关键字段

### 4.7 Step1-3 子契约一致性

- Step1 准入语义 128 由 T02 内部决定（前述 P6）
- Step3 `topology.build_step3_status_doc` 在 case-coordination 模式下把 `event_branch_ids/boundary_branch_ids = ()`、`preferred_axis_branch_id = None`，与契约 §3.3 "case skeleton 不承担 unit-local throat" 一致 ✅
- 但 `build_unit_step3_status_doc` 在 unit 维度时 `degraded_scope_reason` 直接来自 `prepared.degraded_scope_reason`，没有过滤"哪些 reason 应当落到 unit-level skeleton"

---

## 5. 给 CodeX 的优化优先级建议（按 ROI 排序）

| 优先级 | 任务 | 收益 |
|---|---|---|
| **P0** | `event_interpretation.py` 拆分（按 §3.2 五份方案）| 解除 91KB → 8KB 风险，避免下一轮触发 §1.4 停机 |
| **P0** | `architecture/04-solution-strategy.md` 与 `INTERFACE_CONTRACT.md §3.4` 去重 | 消除双 source-of-truth |
| **P0** | T02 私有 API 改 façade | 解除 T02 重构对 T04 的冲击 |
| P1 | `rcsd_selection.py` 抽 `_no_support_decision` + 拆 3 文件 | 节省 ~6KB、可读性大幅提升 |
| P1 | `INTERFACE_CONTRACT.md §3.4` 拆 6 个子小节、§4.4 列全 CSV 列与 GPKG schema | 契约可作为对外稳定面 |
| P1 | `degraded_scope_reason` 严重组合升 FAIL | 与契约 §3.4 完全对齐 |
| P1 | `batch_runner` 异常落盘 + 防 `rmtree` 误删 | 修可追溯性硬伤 |
| P2 | `case_models.T04EventUnitResult` 按子领域聚合 | 字段从 60+ 降到 ~10 顶层 + nested |
| P2 | 测试文件按契约切片 | 控制测试侧 100KB 风险 |
| P2 | `code-size-audit.md` 同步 t04 high-risk 行 | 治理同步 |
| P3 | `architecture/11-frozen-baselines.md` 把 §3.5 / §3.6 移出契约 | 契约保持稳定 |
| P3 | path-conventions / entrypoint-registry 提示行 | 关闭治理缺口 |
| P3 | CRS gate / GPKG schema test / 数据签名落 case_meta | 修 GIS 审计可追溯性 |

---

## 6. 本轮审计的边界声明

- **未修改**：本审计未对 `INTERFACE_CONTRACT.md / architecture/* / src/* / tests/* / outputs/*` 做任何写入。
- **已确认**：当前 `git status` 显示的 `M modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md / architecture/04 / architecture/10` 是上一轮线程留下的修改，与本审计无关。
- **未审计**：`outputs/_work/...` 下批量审计工件按 repo `AGENTS.md §2` 不在默认主搜索路径，本轮只确认目视通过结论由用户主张。
- **强提示**：如需让 CodeX 直接进入实施阶段，建议把 P0 三项作为一个 SpecKit `specify` 任务书下发；其规模与"跨模块重构"边界相符，必须走 SpecKit 主流程，不应走 default-imp。
