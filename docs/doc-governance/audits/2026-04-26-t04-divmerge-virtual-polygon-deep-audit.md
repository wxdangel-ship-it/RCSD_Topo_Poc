# T04 `t04_divmerge_virtual_polygon` 深度审计报告（2026-04-26）

> 本文件供 GPT 进一步分析评估使用。审计**只读、不修改**任何 `INTERFACE_CONTRACT.md / architecture/* / src/* / tests/*` 等稳定面，亦不新增执行入口。
>
> 审计依据：项目级 `AGENTS.md`、`docs/doc-governance/module-lifecycle.md`、`docs/repository-metadata/{code-boundaries-and-entrypoints.md, code-size-audit.md, entrypoint-registry.md}`、模块级 `modules/t04_divmerge_virtual_polygon/{AGENTS.md, README.md, INTERFACE_CONTRACT.md, architecture/*}`，以及 `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/**`、`tests/modules/t04_divmerge_virtual_polygon/**`、`scripts/t04_*`、当前 Anchor_2 `2026-04-26` full-run 工件。
>
> 与既有审计衔接：本文件是 [`2026-04-22 deep audit`](./2026-04-22-t04-divmerge-virtual-polygon-deep-audit.md) 与 [`2026-04-23 full-rerun handoff`](./2026-04-23-t04-full-rerun-deep-audit-handoff.md) 的**第三轮全量复核**。复核口径以"项已闭环 / 项已演化 / 项仍未闭环 / 项新增"四档表述。

---

## 0. TL;DR：交付决策建议

| 维度 | 现状 | 与契约对齐 | 上轮（04-23）评级演化 |
|---|---|---|---|
| 模块级文档矩阵（Day-0 必建集） | `AGENTS.md / INTERFACE_CONTRACT.md / architecture/01-04, 06, 10` 齐备 | ✅ | 维持 |
| `INTERFACE_CONTRACT.md` 体量与切分 | 41,940 bytes，§3.4 单段已被进一步拉长（含 Step5-7、§3.8/§3.9 冻结基线） | ⚠️ 双源近重复仍未拆，§3.4 单段未做小节切分 | 未闭环（恶化） |
| Step1-4 业务正向 | 23 case / 31 unit 跑通；A 类 20 / B 类 6 / C 类 5 | ✅ 业务侧达标 | 已演化（从 8 case 扩到 23 case） |
| Step5-7 主链路 | 23 case，accepted=20 / rejected=3，与 §10 baseline gate `accepted=20 / rejected=3` 一致 | ✅ | 已演化（857993 仍 rejected，但已被契约 §10 写入 expected） |
| STEP4 状态机分布 | `STEP4_OK = 0 / STEP4_REVIEW = 31 / STEP4_FAIL = 0`，仍 100% 落 REVIEW | ⚠️ §3.4 已增条款承认 "REVIEW 是 Anchor_2 常态" | **已被契约背书**（不再算缺陷，但 OK 状态实质不可达） |
| 跨模块运行时依赖（T02/T03） | runtime import = 0；上轮发现的 T02 同名硬拷贝文件 `_runtime_stage4_execution_contract.py` 已删除 | ✅ | **已闭环** |
| 死代码（`_runtime_step4_kernel_reference.py`） | 仍存在，但 `_runtime_step4_kernel.py` 已 `from ._runtime_step4_kernel_reference import *`，不再是孤儿 | ⚠️ 命名误导（"reference" 是基座，不是参考实现） | **状态翻转**（不再死代码，但治理需登记） |
| 文件体量硬约束（§3 100 KB） | `_event_interpretation_core.py` = **94,960 bytes**（距阈值 5,040 bytes，使用率 95%）；`step4_road_surface_fork_binding.py` = **92,474 bytes**（92%） | ⚠️ 距停机阈值不到一轮中型改动 | **恶化**（核心文件 +6,985 bytes / 新增 92 KB 文件） |
| `code-size-audit.md` 同步 | 仅录入 04-23 当时数据，**24-26 当前最大文件 `step4_road_surface_fork_binding.py`、`support_domain.py` 未入表** | ⚠️ 违 `AGENTS.md §3` 同轮登记原则 | 未闭环 |
| 测试套件 | T04 测试目录下 17 个 `test_*.py`；`test_step14_pipeline.py` 已转为 split-files 注册检查；`test_anchor2_full_20260426_baseline_gate` 已锁定 23/20/3 数字门槛 | ✅ 数字基线入测；⚠️ 仍缺 PNG 视觉黄金图回归 | 已演化（从 27 passed / 2 failed 回到 baseline-gated） |
| 入口治理 | `scripts/t04_*` 三件套已登记 `entrypoint-registry.md`；模块入口 `run_t04_step14_batch / run_t04_step14_case / run_t04_internal_full_input` 维持 Python runner | ✅ | 维持 |
| `case_meta.json / preflight.json` 审计可追溯字段 | 仍不带输入数据集 hash / mtime / git SHA | ⚠️ | 未闭环 |
| `batch_runner.run_t04_step14_batch` 错误处理 | `except Exception:` 仍裸吞，仅落 `failed_case_ids`，**不写 traceback** | ⚠️ | 未闭环 |
| `run_root` 自动 `shutil.rmtree` | 仍存在 | ⚠️ 误调用风险 | 未闭环 |
| `architecture/05` 与实际代码层级一致性 | `_runtime_*` 与 `full_input_*` 大块仍未在 05 中表述；新增 `step4_road_surface_fork_binding / step4_rcsd_anchored_reverse / step4_final_conflict_resolver` 三个 step4 终段处理器也未入 05 | ⚠️ 架构描述滞后实现 | **恶化**（新增 3 个独立模块未入 05） |

**给 GPT 的总判定**：T04 当前**业务侧已达 §10 Anchor_2 full baseline 冻结门槛**（23/20/3），跨模块依赖已彻底切干净，可视为 *Step1-7 production-grade baseline freeze* 的稳定锚点。**但治理侧**（契约拆分、文件体量同步、架构描述同步、错误可观测性、回归可追溯性）**有 6 项历史缺口仍未闭环**，并已被三轮审计反复登记。在 §10 baseline 冻结的前提下，下一轮启动 SpecKit 应**优先补这些治理缺口**，而不是直接打开新业务范围。

---

## 1. 仓库中需求契约的完整性与逻辑性

### 1.1 文档矩阵盘点（对照 `_template/AGENTS.md`）

| Day-0 必建 | 文件 | 体量 | 状态 |
|---|---|---:|---|
| `AGENTS.md` | `modules/t04_divmerge_virtual_polygon/AGENTS.md` | 1,313 bytes | ✅ |
| `INTERFACE_CONTRACT.md` | 同上 | **41,940 bytes** | ✅ 但已偏胖，见 §1.3 |
| `architecture/01-introduction-and-goals.md` | 851 bytes | ✅ |
| `architecture/03-context-and-scope.md` | 1,107 bytes | ✅ |
| `architecture/04-solution-strategy.md` | 15,900 bytes | ⚠️ 与 `INTERFACE_CONTRACT §3.4` 高度重述 |
| 建议补齐 | `architecture/02-constraints.md` | 687 bytes | ✅ |
|  | `architecture/05-building-block-view.md` | 1,681 bytes | ⚠️ 与实际代码层级偏差较大，见 §2.2 |
|  | `architecture/10-quality-requirements.md` | 13,997 bytes | ✅（已含 Anchor_2 full baseline gate / 冻结判据） |
|  | `architecture/11-risks-and-technical-debt.md` | **缺** | ⚠️ |
|  | `architecture/12-glossary.md` | **缺** | ⚠️ |
|  | `architecture/06-step34-repair-design.md` | 8,544 bytes | ⚠️ 非 arc42 标准章节，README/01 中无显式裁剪声明 |
| 模块成熟后 | `review-summary.md` | **缺** | ⚠️ 推荐补齐 |
|  | `history/` | **缺** | ⚠️ 推荐补齐 |
| 操作者入口 | `README.md` | 2,870 bytes | ⚠️ 默认路径 `/mnt/e/...`，PowerShell 不可直接执行；`path-conventions.md` 治理缺口同步存在 |

**结论**：Day-0 必建集 100% 齐备；建议补齐项中 `02 / 05 / 10` 已建（其中 `10` 大幅补强），但 `11 / 12` 仍缺。`architecture/06-step34-repair-design.md` 是唯一非 arc42 章节，存在编号冲突风险（如未来要加 arc42 标准 06，需重命名）。

### 1.2 契约 vs 项目级硬规则（`AGENTS.md`）

| 项目级硬条款 | T04 检查点 | 结果 |
|---|---|---|
| §1.1 源事实之间不得冲突 | `INTERFACE_CONTRACT §3.4` 与 `architecture/04 §3` 在 pair-local region / `(L,R)` continuation / 200m 上限等条目上**两处平行重述**；与 §3.8 / §3.9 冻结基线之间也存在样本级二次重复 | ⚠️ 未闭环 |
| §1.2 入口治理 | `scripts/t04_run_internal_full_input_8workers.sh / t04_watch_internal_full_input.sh / t04_run_internal_full_input_innernet_flat_review.sh` 三件套已登记 `entrypoint-registry.md` 行 58-60；模块未新增 repo CLI | ✅ |
| §1.3 入口变更与 registry 一致 | 当前 registry 与 `scripts/` 与 `__init__.py` 公开 runner 一致 | ✅ |
| §1.4 / §3 文件体量 | `_event_interpretation_core.py = 94,960 bytes`（95%）；`step4_road_surface_fork_binding.py = 92,474 bytes`（92%）；`_runtime_types_io.py = 76,769 bytes`；`support_domain.py = 74,314 bytes`；`_runtime_step4_kernel_reference.py = 65,297 bytes`（命名误导） | ⚠️ 距硬阈值不足一轮；下次任何对前两个文件的"中型追加"都会触发停机 |
| §3 同轮登记 `code-size-audit.md` | T04 当前最大文件 / 第二大文件均未入 `code-size-audit.md` 表（该表仅列 T02 / T01 测试） | ⚠️ 未闭环 |
| §5 GIS 5 项 | CRS：`case_loader.py` / `_runtime_shared.py` 一处 gate；其余 step4-7 内核默认假设 EPSG:3857，无 runtime assertion；拓扑：`buffer(0)` / `buffer(1e-6)` 静默修复散布于 `support_domain.py / polygon_assembly.py / _runtime_step4_geometry_*` | ⚠️ 静默假设 + silent fix 风险 |
| §6.1 default-imp / §6.2 SpecKit | Step5-7 落地阶段已存在多个 `specs/t04-*` 任务包（含 `t04-step4-final-tuning-conflict-resolver / t04-step4-candidate-space-normalization / t04-positive-rcsd-selector-redesign-speckit` 等 8 个 spec 包）；但未见对应 `Product / Architecture / Development / Testing / QA` 五视角分头交付的统一索引 | ⚠️ 视角覆盖证据不全 |
| §7 路径换算 | README 仍使用 `/mnt/e/...` 单一表述；缺 PowerShell↔WSL 换算说明 | ⚠️ 同 `path-conventions.md` 治理缺口 |

### 1.3 契约本身的规范性问题（仍未闭环）

#### A. 双源近重复（未闭环）
`INTERFACE_CONTRACT §3.4`（约 240 行单段）与 `architecture/04 §3`（约 170 行）继续平行重述 pair-local region / continuation / 三层候选 / RCSD A/B/C / ownership guard 等。任意一边被改即触发 `AGENTS.md §1.1`。

#### B. §3.4 单段过长（恶化）
当前 §3.4 已包含从 "event unit 规则" 一路到 "second-pass resolver 字段保留" 的全部规则，单段约 290 行；与 §3.8 / §3.9 冻结基线之间还存在条款级映射重复（如 `pair_local_middle within pair_local_structure_face within pair_local_region` 同一句出现 ≥ 3 次）。

#### C. §6 Acceptance 部分仍缺数字门槛
`§6.1-§6.6` 是定性描述（"已存在 / 可运行 / 已纳入 / 不得拷贝"），仅 §6.7 引入 `accepted = 7 / rejected = 1`（基于早期 Anchor_2 8 case 子集）。当前 `architecture/10` 已明确 23/20/3 baseline gate，但 §6 与 §10 之间未做 cross-reference，且 §6.7 数字与 §10 数字不一致（前者 7/1，后者 20/3）。

> **逻辑性缺陷**：契约中存在两套 acceptance 数字（§6.7 的 7/1 与 §10 / §3.8 / §3.9 的 23/20/3），且未声明 "§6.7 是 legacy selected-case，§10 是 full baseline"。新读者无法迅速判断哪个是当前 acceptance 真相。

#### D. 输出 schema 不完整
- `step4_review_index.csv` 当前实际 ≥ 67 列（见 `outputs/_work/t04_anchor2_full_requested/.../step4_review_index.csv` 的 66,381 bytes 表头），契约 §4.4 仅列 32 列；多出来的 ~35 列没有契约定义。
- `step4_event_evidence.gpkg / step5_domains.gpkg / step6_assembly.gpkg / divmerge_virtual_anchor_surface_audit.gpkg` 全部**没有图层 schema 定义**。
- §4.5 / §4.6 / §4.7 仅写"至少持久化以下对象"，对图层 / 字段命名约定不做约束。

#### E. 冻结基线写进契约的副作用
`§3.8 / §3.9 / §10` 把 `case_id / road_id / divstrip:N:01` 等具体取值写进契约，导致每次 baseline 演化都触发契约改动；建议把"冻结基线"沉到 `architecture/11-frozen-baselines.md`，契约 §3.8 / §3.9 仅引用。

#### F. 缺项
- 仍无 `CHANGELOG.md / last-updated` 头。
- `STEP4_FAIL` 的下游语义无定义（Step5-7 是否会自动跳过 / 自动 reject？查阅 `final_publish.py` 可见 `STEP4_FAIL` 不会单独触发 Step7 reject，但契约未声明）。
- Step4 ↔ Step5 字段稳定性表缺失（哪些 Step4 字段是 Step5 必读 / 可选 / 不消费，没有清单）。
- `swsd_relation_type` 在 `final_publish` 中可产出 `partial / covering / unknown / offset_fact / no_relation` 等，**契约 §3.7 未列举**。
- `reject_reason / reject_reason_detail` 仍无枚举（实际可见 `final_polygon_missing / multi_component_result / hard_must_cover_disconnected / b_node_not_covered / assembly_failed` 等 ≥ 5 类）。

#### G. 对 T03 关系的口径分裂（仍未统一）
- `AGENTS.md` 行 13："不得直接 import / 调用 / 硬拷贝 T03 模块代码"
- `INTERFACE_CONTRACT.md §1` 行 32：同口径
- `architecture/02-constraints.md` 行 18："优先复用 T03 的 case-package / batch / review 输出组织"

三处口径**口语上歧义**（"复用组织" 在文档语义上似乎被允许，但代码语义上不允许），应统一表述。

### 1.4 §3 内部条款一致性

- §3.4 中 `pair-local continuation 200m` 与 §10 `valid_scan_offsets_m 只沿单一合法方向延续` 内涵相同但措辞不同；
- §3.4 `STEP4_REVIEW = 13` 是早期 Anchor_2 8-case 数据，§4.4 末尾 `STEP4_REVIEW = 13` 与之同步；但 §10 末段 `Anchor_2 full baseline gate` 隐含 `STEP4_REVIEW = 31`（与最新 run 一致），三处数字未对齐。
- §3.6 / §3.7 数字阈值（`STEP6_RESOLUTION_M = 0.5 / STEP6_GRID_MARGIN_M = 30`）等代码侧硬常量未在契约表达；契约 §3.6 仅写"raster-first"。

### 1.5 总评（需求契约维度）

- **完整性**：✅ 五类需求面（Step1-7、review、batch、internal full-input）均已被纳入；输入字段 §2.2 显式声明；输出对象 §4.x 显式声明。
- **逻辑性**：⚠️ 双源重复 + 单段过长 + 数字基线分裂 + 输出 schema 不全 + 状态枚举缺失，是当前主要缺口。这些不影响业务正确性，但会持续放大未来契约维护的成本。
- **是否符合"良好的需求分析实践"**：达到了 *coverage / explicit reason set / acceptance baseline frozen* 三项；缺 *single-source-of-truth / measurable acceptance / output schema / state enumeration / glossary* 五项。**整体处于 "可运行但可维护性不足" 的中段。**

---

## 2. 技术架构合理性

### 2.1 模块级源码分布

`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/` 共 44 个 `.py`，约 30K+ 行；按职责划分如下：

| 类别 | 文件 | 备注 |
|---|---|---|
| **Day-0 facade** | `case_loader.py / admission.py / local_context.py / topology.py / event_units.py / event_interpretation.py / review_render.py / outputs.py / batch_runner.py` | 都偏薄；admission 已彻底独立（清除 T02 硬拷贝） |
| **Step4 公共子层** | `event_interpretation_shared.py / event_interpretation_branch_variants.py / event_interpretation_selection.py / variant_ranking.py / rcsd_selection.py / _rcsd_selection_support.py` | 5+1 子模块结构 |
| **Step4 核心** | `_event_interpretation_core.py`（**94,960 bytes**） | 最大文件，下文详述 |
| **Step4 终段处理器（新）** | `step4_final_conflict_resolver.py / step4_road_surface_fork_binding.py / step4_rcsd_anchored_reverse.py` | 3 个新模块，均为 second-pass 后置层 |
| **Step5-7** | `support_domain.py / polygon_assembly.py / final_publish.py / _runtime_polygon_cleanup.py` | Step5-7 主链 |
| **Runtime support** | `_runtime_shared.py / _runtime_types_io.py / _runtime_step23_contracts.py / _runtime_step4_contracts.py / _runtime_step4_geometry_core.py / _runtime_step4_geometry_reference.py / _runtime_step4_kernel.py / _runtime_step4_kernel_reference.py / _runtime_step4_surface.py / _runtime_step2_local_context.py / _runtime_step3_topology_skeleton.py` | 11 个 runtime 文件，与 `architecture/05` 完全脱节 |
| **Internal full-input orchestration** | `internal_full_input_runner.py / full_input_bootstrap.py / full_input_case_pipeline.py / full_input_observability.py / full_input_perf_audit.py / full_input_shared_layers.py / full_input_streamed_results.py` | 7 个 full-input 文件，与 `architecture/05` 同样脱节 |
| **Models / audit** | `case_models.py / review_audit.py` | dataclass 与 review aggregation |

### 2.2 与 `architecture/05-building-block-view.md` 对照（恶化）

`architecture/05` 当前声明 13 个 building block：`case_loader / admission / local_context / topology / event_units / event_interpretation (含 5 子块) / review_render / support_domain / polygon_assembly / final_publish / outputs / batch_runner`。

**与代码差距**：
| 实际代码块 | `05` 中是否提及 |
|---|---|
| `_runtime_*`（11 个文件，约 460 KB） | ❌ 完全未提 |
| `full_input_*`（7 个文件，约 70 KB） | ❌ 完全未提 |
| `step4_final_conflict_resolver / step4_road_surface_fork_binding / step4_rcsd_anchored_reverse`（3 个新二次处理器，182 KB 合计） | ❌ 完全未提 |
| `case_models / review_audit` | ❌ 未提 |

**结论**：`architecture/05` 当前严重滞后实现。建议在补充轮次至少加 `runtime_support / full_input_orchestration / step4_postprocess` 三节。

### 2.3 高内聚 / 低耦合评估

#### A. 高内聚

| 子层 | 内聚度评估 |
|---|---|
| `case_loader / admission / local_context / topology / event_units` | ✅ 高（每文件单职责，且基本不互相反向依赖） |
| `event_interpretation_*` 组（shared / variants / selection / ranking / rcsd_selection） | ✅ 高（按 5 个明确语义维度分） |
| `support_domain / polygon_assembly / final_publish` | ✅ 高（Step5/6/7 严格分层） |
| `_runtime_step4_*` 群 | ⚠️ 中（命名上 `core / reference / kernel / kernel_reference / geometry_core / geometry_reference / surface` 七层，语义上有重叠，部分文件互为基座） |
| `_event_interpretation_core.py` 单文件 | ⚠️ 低（94 KB / ~2,100 行，承担 7 大职责：unit context preparation / unit inputs materialization / pair-local region 构造 / candidate pool 生成 / candidate evaluation / RCSD selection 接驳 / build_case_result 装配） |
| `_runtime_types_io.py` 单文件 | ⚠️ 低（76 KB，IO + 类型 + 几何辅助 + raster + io_utils 重叠） |
| `step4_road_surface_fork_binding.py` | ⚠️ 低（92 KB / ~2,000 行，单文件承载 binding / surface recovery / structure-only / window-mode / SWSD junction window / RCSD junction window 等多场景） |

#### B. 低耦合

| 维度 | 评估 |
|---|---|
| 跨模块运行时依赖 | ✅ T02 = 0，T03 = 0，T01 仅复用 `io_utils.write_csv`，T00 仅复用 `common.{build_run_id, normalize_runtime_path, sort_patch_key, write_json, write_vector}` 这类通用工具；符合契约 |
| T04 模块内层级依赖方向 | ✅ 大体单向（facade → shared → runtime），未发现明显循环依赖 |
| `event_interpretation.py` facade 与 `_event_interpretation_core.py` | ⚠️ facade 直接 import core 中 `_PreparedUnitInputs / _CandidateEvaluation / _build_candidate_pool / _evaluate_unit_candidate / _select_case_assignment` 等多个**带前导下划线的私有名**；facade 与 core 之间没有正式 public API 屏障 |
| `_runtime_step4_kernel.py` 通过 `from ._runtime_step4_kernel_reference import *` 注入符号 | ⚠️ 命名 *kernel vs kernel_reference* 与依赖方向相反（kernel 是 wrapper、reference 是基座），易误导新维护者；上轮（04-23）"reference 是死代码"的判断在本轮已**翻转为"reference 是隐式基座"**，但治理上未登记 |
| `_runtime_step4_geometry_reference.py` 通过 `from ._runtime_step4_geometry_core import *` 注入符号 | ⚠️ 同上，*reference vs core* 命名误导 |

#### C. 是否符合项目要求

| 项目规则 | 评估 |
|---|---|
| `AGENTS.md` 行 13：禁止把 T02 大一统 orchestrator 直接平移为 T04 主结构 | ✅ T04 已彻底拆为多个子模块；上轮发现的 `_runtime_stage4_execution_contract.py` T02 同名硬拷贝 **已删除** |
| `AGENTS.md` 行 13：禁止 import / 调用 / 硬拷贝 T03 | ✅ runtime grep 0 处 |
| `INTERFACE_CONTRACT §1` 优先按 `admission / local_context / topology / event_interpretation / support_domain / polygon_assembly / final_publish / review_render / outputs / batch_runner` 分层 | ✅ 主层级符合；`_runtime_*` 与 `full_input_*` 是隐式实现层，未在该列表声明，但在分层语义上属于 supporting infrastructure 而非业务对外面，可接受 |
| `AGENTS.md §3.1` 单文件 100 KB 硬阈值 | ⚠️ 两个文件（`_event_interpretation_core.py / step4_road_surface_fork_binding.py`）已分别处于 95% 与 92%；任一再做中型扩张即触发停机 |
| `AGENTS.md §3` 同轮更新 `code-size-audit.md` | ⚠️ 当前 T04 高风险文件未入表 |

### 2.4 总评（架构维度）

- **高内聚**：业务面（Step1-7 主链 + Step4 多子模块 + Step5-7 三段）整体优秀；但**两个核心文件 `_event_interpretation_core.py / step4_road_surface_fork_binding.py` 内聚度偏低**，是技术债重心。
- **低耦合**：✅ 跨模块依赖已极简；模块内 facade ↔ core 私有名直接引用是次要风险（不影响 T04 对外契约）。
- **是否符合项目规则**：✅ 业务面规则全部满足；⚠️ 治理面（体量 + `code-size-audit` 同步 + `architecture/05` 同步）有 3 项已多轮登记仍未闭环。
- **架构图与代码漂移**：架构 `05` 落后实现约 18 个文件 / 3 个独立子层未表述。

---

## 3. 代码实现逻辑与需求实现的一致性

### 3.1 已充分一致的链路

| 契约条款 | 代码实现 | 一致性 |
|---|---|---|
| §3.1 Step1 准入 (`kind 8/16/128`, `has_evd=yes`, `is_anchor=no`) | `admission.py` `build_step1_admission` | ✅ |
| §3.2 Step2 negative context | `local_context.py` + `_runtime_step2_local_context.py` | ✅ |
| §3.3 Step3 双层 skeleton（case coordination + unit-level executable） | `topology.py + outputs.build_unit_step3_status_doc + _runtime_step3_topology_skeleton.py` | ✅ |
| §3.4 Step4 unit envelope（含 `boundary_branch_ids / preferred_axis_branch_id`） | `_event_interpretation_core._build_unit_envelope` | ✅ |
| §3.4 RCSD A/B/C 链路（pair-local raw → candidate scope → local → aggregated → polarity → role mapping → A/B/C） | `rcsd_selection.resolve_positive_rcsd_selection` + `_rcsd_selection_support._build_aggregated_rcsd_units` | ✅ 链路完整 |
| §3.4 ownership guard（physical component union + same-axis Δs ≤ 5m + localized core overlap） | `event_interpretation_selection._apply_evidence_ownership_guards` | ✅ |
| §3.4 second-pass resolver 顺序（same-case evidence → same-case RCSD claim → cross-case → final consistency） | `step4_final_conflict_resolver.resolve_step4_final_conflicts` + `step4_road_surface_fork_binding.apply_road_surface_fork_binding` + `step4_rcsd_anchored_reverse.apply_rcsd_anchored_reverse_lookup` | ✅ 顺序与字段保留与契约一致 |
| §3.4 `rcsd_anchored_reverse` 末段旁路（含 `min sample = 3 / axis missing skip / same-case claim conflict / post_reverse_conflict_recheck`） | `step4_rcsd_anchored_reverse.py` 全实现 | ✅ |
| §3.4 SWSD / RCSD `junction_window`（前后 20m） | `step4_road_surface_fork_binding.SWSD_JUNCTION_WINDOW_REASON / RCSD_JUNCTION_WINDOW_REASON / JUNCTION_WINDOW_HALF_LENGTH_M = 20.0` | ✅ |
| §3.5 Step5 Unit/Case 两级 must_cover / allowed_growth / forbidden / terminal_cut | `support_domain.py` 全字段 | ✅ |
| §3.5 `junction_full_road_fill_domain`（轴向半宽 20m，纵向 20m terminal） | `support_domain.STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M = 20.0 / STEP5_JUNCTION_WINDOW_HALF_LENGTH_M = 20.0` | ✅ |
| §3.6 Step6 raster-first 单连通组装；clean 后必须重新套约束 | `polygon_assembly.py` 含 `STEP6_RESOLUTION_M = 0.5 / _reapply_case_limits_after_hole_fill / _polygon_components` | ✅ |
| §3.7 Step7 二态 (`accepted / rejected`)；`reject_stub_geometry` | `final_publish.py` `STEP7_ALLOWED_TOLERANCE_AREA_M2 / STEP7_REJECT_STUB_BUFFER_M / build_step7_case_artifact` | ✅ |
| §10 Anchor_2 full baseline gate (23 / 20 / 3) | `tests/.../test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate` | ✅ 已锁入测试 |

### 3.2 仍存在差距（按"是否需求不清 vs 代码未达"分类）

#### A. 需求不清 → 代码补全（应回写契约）

| 现象 | 代码事实 | 契约缺位 |
|---|---|---|
| Step4 候选空间纵向硬上限 | `_event_interpretation_core.PAIR_LOCAL_BRANCH_MAX_LENGTH_M`（来自 `_runtime_step4_geometry_core`，实际值需进一步审；契约 §3.4 写 200m） | 契约 §3.4 写 200m，但代码常量 `EVENT_REFERENCE_SCAN_MAX_M = 140.0` 与 `EVENT_CROSS_HALF_LEN_MAX_M = 130.0` 等更细的几何阈值未入契约 |
| `branch_separation_too_large` 阈值 | 隐式来自 `EVENT_CROSS_HALF_LEN_MAX_M = 130.0` 与 `_runtime_step4_geometry_core` 中 separation 常量 | 契约 §3.4 只要求"必须显式输出 stop reason"，未给米数 |
| `degraded_scope_severity` 判据 | `_event_interpretation_core.HARD_DEGRADED_SCOPE_REASONS = {"pair_local_middle_missing"}`；其余一律 soft | 契约 §3.4 只写 `soft / hard` 二态，未给完整判据矩阵 |
| `STEP4_OK / REVIEW / FAIL` 实际分布 | 当前 100% 落 REVIEW（31/31）；OK 实质不可达 | 契约 §3.4 已**承认** "Anchor_2 baseline 允许 STEP4_REVIEW 是常态"，但未定义 *什么数据上 OK 才会出现* |
| `swsd_relation_type` 取值集 | `final_publish.py` 可产出 `partial / covering / unknown / offset_fact / no_relation` 等 | 契约 §3.7 完全未列举 |
| `reject_reason / reject_reason_detail` 取值集 | `final_polygon_missing / multi_component_result / hard_must_cover_disconnected / b_node_not_covered / assembly_failed` 等 ≥ 5 类 | 契约 §3.7 完全未列举 |
| `evidence_source / position_source` 完整集 | 包含 `road_surface_fork / swsd_junction_window / rcsd_junction_window / rcsd_anchored_reverse / divstrip_split_window_after_reverse_probe / drivezone_split_*` 等 | 契约 §3.4 仅枚举其中部分 |
| `step4_review_index.csv` 实际 ≥ 67 列 | `outputs.REVIEW_INDEX_FIELDNAMES` | 契约 §4.4 仅 32 列，多 35 列没有契约定义 |
| `Step5-7` 多个 status / audit JSON 字段 | `step5_audit / step6_audit / step7_audit / step7_consistency_report` 字段集 | 契约 §4.5 / §4.6 / §4.7 仅"至少持久化"，无字段清单 |

> **建议**：将上述 9 项**作为契约不清缺口**补回 `INTERFACE_CONTRACT.md`。这是"需求侧 unfinished"，不属于"代码 over-implementation"。

#### B. 代码未达需求（应作为缺陷修）

当前**无明显代码未达需求项**。原因：契约 §10 已经把 Anchor_2 23 case 全量结果（含 857993 / 760598 / 760936 三个 rejected）显式列入 expected baseline，且 `test_anchor2_full_20260426_baseline_gate` 已对该 baseline 实施数字断言；上轮（04-23）的 `857993 multi_component_result` 缺陷已被治理决策**接受为正确业务结论**（人工目视审计确认），不再是缺陷。

#### C. 历史代码-契约偏差闭环情况

| 上轮（04-23）登记的差距 | 当前状态 |
|---|---|
| C-A. `_runtime_stage4_execution_contract.py` 是 T02 同名文件硬拷贝 | ✅ **已闭环**：文件不存在；`admission.py` 自给自足，仅复用 `_runtime_step4_geometry_core` 的 helper |
| C-B. STEP4_OK 永远为 0 | ⚠️ **状态翻转**：契约 §3.4 已增条款 *"`STEP4_REVIEW` 是 Step4 内部审计态… `pair_local_scope_roads_empty` 等 soft degraded 使 `STEP4_REVIEW` 成为常态"*，问题被契约接受。**但 OK 状态仍实质不可达**，建议保留为治理缺口（OK 是否仍有意义） |
| C-C. Step7 多 case 拒绝 | ✅ **已闭环并入 baseline**：23 / 20 / 3 已入契约 §10、入测试 baseline gate |
| C-D. `_runtime_step4_kernel_reference.py` 死代码 | ✅ **已翻转**：现在被 `_runtime_step4_kernel.py` `from ... import *`，是基座，不再死代码；但**命名仍误导** |
| C-E. `test_step14_pipeline.py` 空 stub | ✅ **已重构**：现在是"split files registered"检查，符合契约 §3.8 引用"测试断言为准"的语义 |
| C-F. `test_aggregated_rcsd_unit` 测试失败 | ✅ **已闭环**：测试断言已对齐 `selected_rcsdroad_ids >= {rc_axis, rc_mid, rc_right}`（3 项，非全 4 项），与契约"publish/core 子集"一致 |
| C-G. Step1 `kind=128` 准入路径走 T02 | ✅ **已闭环**：`admission.py` 内 `_is_stage4_supported_node_kind / _node_source_kind / _node_source_kind_2` 已是 T04 私有 |

### 3.3 总评（一致性维度）

- **代码达成需求**：✅ 23 case full baseline 通过；A/B/C / Step5-7 / second-pass 等链路全部对齐。
- **需求不清而代码补全**：⚠️ 9 类事实（阈值常量 / 状态枚举 / CSV 列 / status JSON 字段 / `STEP4_OK` 可达性）需要回补契约，否则代码默认值就成为事实契约。
- **代码未达需求**：✅ 无显著缺陷（上轮 6 项历史缺陷全部闭环或由契约接收）。

---

## 4. 自主决定的额外审计维度

### 4.1 测试矩阵覆盖与回归可信度

`tests/modules/t04_divmerge_virtual_polygon/` 当前 17 个 `test_*.py`：

| 文件 | 主断言 | 类型 |
|---|---|---|
| `test_step14_pipeline.py` | split-files 注册检查 | 文档级 |
| `test_step14_synthetic_batch.py` | 5 个 synthetic 全链路 | 单元 |
| `test_step14_support.py` | helper（被多个文件 import *） | 共享 fixture |
| `test_step14_real_anchor2.py` | Anchor_2 baseline 主证据冻结 | 真实数据 |
| `test_step14_real_regression.py` | 7 个真实 case 回归 | 真实数据 |
| `test_step14_real_rcsd_claims.py` | 3 个 RCSD claim 回归 | 真实数据 |
| `test_step14_candidate_space_normalization.py` | 候选空间字段 / degraded scope / 200m gate | 真实数据 + 单元 |
| `test_positive_rcsd_selection.py` | 7 个 RCSD A/B/C / aggregated / required_node 单元测试 | 单元 |
| `test_positive_rcsd_publish_subset_real.py` | 2 个真实 case 的 published 子集 | 真实数据 |
| `test_complex_multi_unit_decomposition.py` | 1 个 505078921 多 unit | 真实数据 |
| `test_real_anchor2_699870_rcsd_anchored_reverse.py` | 1 个 reverse 旁路 | 真实数据 |
| `test_step4_rcsd_anchored_reverse.py` | 9 个 reverse 旁路单元 | 单元 + 真实 |
| `test_step5_support_domain.py` | 5 个 Step5 | 合成 + 1 个 real 子流程 |
| `test_step6_polygon_assembly.py` | 8 个 Step6 | 合成 |
| `test_step7_final_publish.py` | 8 个 Step7（含 `test_anchor2_full_20260426_baseline_gate` 23/20/3） | 合成 + Anchor_2 全量 |
| `test_internal_full_input_smoke.py` | 5 个 internal full-input | smoke |

**优点**（与上轮对比）：
- ✅ §3.8 / §3.9 冻结基线已经从测试缺位演化为 `test_anchor2_full_20260426_baseline_gate` 全量数字门槛。
- ✅ Step5-7 已不再是纯合成：`test_anchor2_full_20260426_baseline_gate` 真实串通 23 case × Step1-7 全链路。
- ✅ `step4_rcsd_anchored_reverse` 有 10 个 dedicated 测试。

**缺口**：
- ⚠️ **PNG 视觉黄金图回归仍零覆盖**：所有 PNG 仅做 "存在 / 计数 / 命名" 检查。当前用户的"目视通过"是接受证据，CI 没有锁定下次 PNG 漂移的能力。
- ⚠️ Step6 测试 8 个全部合成 case，缺 Anchor_2 真实 raster-grid 行为锁定（如 857993 的 `multi_component_result` 是否被合成测试覆盖到 negative 断言？需进一步核对）。
- ⚠️ `internal_full_input_runner` 5 个 smoke 测试中 `test_t04_internal_full_input_watch_once` 在 Windows 上仍可能 `WinError 193`（`.sh` 不可执行），如 CI 跑在 Linux/Mac 应无影响，但跨平台 fixture 应加 `pytest.mark.skipif(os.name == 'nt')`。

### 4.2 可观测性 / 审计可追溯性

| 工件 | 是否带回溯标识 |
|---|---|
| `preflight.json` | ✅ 含 `python_executable / python_version / case_root / out_root / run_root / generated_at`；⚠️ **不含 git SHA / 输入数据集 hash / mtime** |
| `case_meta.json` | ✅ 含 case_id / mainnodeid；⚠️ 不含输入数据集 hash / git SHA |
| `step4_audit.json / step5_audit.json / step6_audit.json / step7_audit.json` | ✅ 字段丰富；⚠️ 文件层级缺 `producer_module_version / git_sha` |
| `summary.json` | ✅ 含 case_count / accepted / rejected；⚠️ 缺 `code_version / run_args` |
| `step4_review_index.csv` | ✅ ≥ 67 列；⚠️ 不含 `producer_run_id / produced_at` 列 |
| `divmerge_virtual_anchor_surface*` 发布层 | ✅ `final_state / publish_target / review_png_path` 等；⚠️ feature 层缺 `producer_run_id / produced_at` 字段 |

**结论**：审计材料的"业务字段"已经非常充实（可用于人工复核），但**回溯字段**（git SHA / 输入数据集 hash / 运行参数）缺失，跨轮次 `outputs/_work/...` 之间无法仅凭 artifact 追到代码版本。这是治理缺口，与上轮一致，仍未闭环。

### 4.3 错误处理 / 故障可见性

#### A. `batch_runner.run_t04_step14_batch` （未闭环）
```
case_results = []
failed_case_ids: list[str] = []
for spec in specs:
    try:
        case_bundle = load_case_bundle(spec)
        case_results.append(build_case_result(case_bundle))
    except Exception:
        failed_case_ids.append(spec.case_id)
```
- 裸吞 `Exception`，不写 traceback。
- 失败 case 进入 `failed_case_ids` 后，下游 `resolve_step4_final_conflicts / apply_road_surface_fork_binding / apply_rcsd_anchored_reverse_lookup / write_case_outputs` 不会处理它；最终 `summary.json` 把它列入 `failed_case_ids: []`，但**不知道为什么失败**。
- 与 `internal_full_input_runner.py` 中已经引入 `traceback` 模块的做法不一致（同模块两套错误处理标准）。

#### B. `shutil.rmtree(run_root)` （未闭环）
`batch_runner.py L69-70` 在 `run_root` 已存在时直接 `shutil.rmtree` 后重建。当前 `run_id` 拼时间戳防撞，未触发误删；但若用户传 `out_root=Path('outputs/_work')` 之类大目录，`run_root` 计算结果可能是已有审计工件目录。建议至少加 `assert run_root.parent != Path('/')` 与 `assert not (run_root / '.git').exists()` 这类 sanity guard。

#### C. silent fix
- `_safe_normalize_geometry` / `_safe_unary_union` 在 except 分支 silent return None；
- `support_domain.py / polygon_assembly.py / _runtime_step4_geometry_*` 共 ≥ 11 处 `buffer(0)` / `buffer(1e-6)` / `buffer(0.5)`；
- 与 `AGENTS.md §5` "拓扑一致性（不允许 silent fix）" 在表面上冲突，但实际是 GIS 工程不可避免的"小数误差吸收"。建议**显式审计**这些 buffer 是否有"误差吸收 vs 真错误掩盖"的判别逻辑；**当前未见**。

### 4.4 性能 / 复杂度

#### A. 已具备
- ✅ `full_input_shared_layers.py` STRtree 预建索引（用于 case-package discovery）。
- ✅ `internal_full_input_runner.py` `ThreadPoolExecutor` per-case 并行（默认 8 worker）。
- ✅ 全量 23 case run（最近 `anchor2_full_all_20260426_724067_surface_apex_fix`）从 00:44 到 00:45 完成，耗时不到 1 分钟（按目录 timestamp）。

#### B. 风险
- ⚠️ `_event_interpretation_core` 内部对 `scoped_*` 的过滤为线性扫描（O(unit × road)），未用 STRtree。当前 23 case 规模不触发，未来 multi-merge 大场景可能放大。
- ⚠️ `_select_case_assignment` 仍是指数级回溯（`MAX_CANDIDATES_PER_UNIT = 6`，N unit 即 7^N）；当前 N ≤ 4 未爆。
- ⚠️ `polygon_assembly.STEP6_MAX_GRID_SIDE_CELLS = 2000` 是硬上限；超过即直接拒绝，但契约未定义此上限（隐式契约）。

#### C. 缺失
- ⚠️ `INTERFACE_CONTRACT §6` 仍**无任何 perf budget / SLO**；案例端到端时间预算未上契约。
- ⚠️ `case-package` 路径不产 `t04_perf_audit.json`；`full_input_perf_audit.py` 仅 internal full-input 专属。

### 4.5 SpecKit 任务包覆盖度

`specs/` 下 T04 相关任务包共 8 个：
- `t04-step14-speckit-refactor`
- `t04-step14-runtime-detach-and-baseline-guard`
- `t04-step34-fixplan`
- `t04-step34-repair-formalization`
- `t04-step4-primary-evidence-positive-rcsd`
- `t04-step4-candidate-space-normalization`
- `t04-step4-final-tuning-conflict-resolver`
- `t04-positive-rcsd-selector-redesign` / `t04-positive-rcsd-selector-redesign-speckit`

**问题**：
- `AGENTS.md §6.3` 要求 SpecKit 任务书显式覆盖 `Product / Architecture / Development / Testing / QA` 五视角；目前每个任务包仅 `spec.md / plan.md / tasks.md` 三件套，未对 5 视角做章节级 / 索引级标注。
- 8 个任务包缺乏统一索引（如 `specs/index.md`），新读者难以快速判断"当前哪个 spec 仍 active / 哪个已合入主线 / 哪个 archived"。

### 4.6 路径治理 / 跨平台

- README 全部用 `/mnt/e/...`（WSL 风格）；当前 shell 是 PowerShell（Windows）。
- `INTERFACE_CONTRACT §3.8 / §3.9 / §10` 多次引用 `/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/...` 作为审计 evidence 路径；PowerShell 下需手工换算。
- `docs/repository-metadata/path-conventions.md` 仍为缺口（`AGENTS.md §7` 显式登记）。

### 4.7 入口治理验证

- 读取 `entrypoint-registry.md` 行 58-60，T04 三件套登记完整；
- `__init__.py` 暴露 `run_t04_step14_batch / run_t04_step14_case / run_t04_internal_full_input` 三个 runner；
- 模块未新增 repo 级 CLI 子命令（与契约一致）；
- `run_t04_step14_batch / run_t04_step14_case` 名字仍停留在 "Step1-4" 时代，但实际跑 Step1-7 全链路（同上轮 §5.4 §5.4 命名不一致问题）。

### 4.8 文档语言 / 命名一致性

- `AGENTS.md` 与 `INTERFACE_CONTRACT.md` 均中文，符合 `AGENTS.md §8`；
- 代码内常量 / API 名英文；符合 §8；
- 但 README 与 `architecture/04` 之间存在"业务术语翻译不一致"：如 `case coordination skeleton` vs `case-level skeleton` 同义不同名、`pair-local region / unit-local branch pair region` 在 `INTERFACE_CONTRACT §3.4` 与 `architecture/04 §3` 两处 alternate；建议建立 `architecture/12-glossary.md`。

---

## 5. 历史审计差距闭环对照（三轮总览）

| 上轮（2026-04-22 / 04-23）登记 | 本轮（2026-04-26）状态 | 备注 |
|---|---|---|
| P0. T02 私有 API 越界引用（13 符号） | ✅ 闭环 | runtime grep 0 |
| P0. `_runtime_stage4_execution_contract.py` T02 硬拷贝 | ✅ 闭环 | 文件已删 |
| P0. STEP4_OK = 0 | ⚠️ 契约接受 | OK 实质不可达，但契约 §3.4 / §10 已说明 |
| P0. 857993 multi_component_result | ✅ 接受为正确 reject | §10 / §3.8 / `test_anchor2_full_20260426_baseline_gate` 锁定 |
| P0. `test_aggregated_rcsd_unit` 失败 | ✅ 闭环 | 测试断言改为 ≥ 3 项，对齐契约 |
| P0. `test_step14_pipeline.py` 空 stub | ✅ 闭环 | 转为 split-files 注册检查 |
| P0. `_runtime_step4_kernel_reference.py` 65 KB 死代码 | ✅ 翻转 | 现在是基座；⚠️ 命名仍误导 |
| P0. `_event_interpretation_core` 拆分 | ⚠️ 未闭环 | 反而 +6,985 bytes / 至 95% 阈值 |
| P0. `INTERFACE_CONTRACT` 双源近重复（A） | ⚠️ 未闭环 | 与 04-22 / 04-23 一致 |
| P0. `INTERFACE_CONTRACT §3.4` 单段过长（C） | ⚠️ 恶化 | §3.4 + §3.8 + §3.9 + §10 持续追加 |
| P0. T03 关系口径分裂（G） | ⚠️ 未闭环 | AGENTS / CONTRACT / 02-constraints 三处口径仍歧义 |
| P1. `code-size-audit.md` 同步 | ⚠️ 未闭环 | T04 高风险文件未入表（含新增的 92 KB `step4_road_surface_fork_binding.py`） |
| P1. `architecture/05` 与代码漂移 | ⚠️ 恶化 | 新增 3 个 step4 后置层未入 05 |
| P1. `path-conventions.md` 缺失 | ⚠️ 未闭环 | |
| P1. `case_meta.json` 输入 hash / git SHA | ⚠️ 未闭环 | |
| P1. `batch_runner` 错误处理 | ⚠️ 未闭环 | 仍裸吞 + 不写 traceback |
| P1. `shutil.rmtree(run_root)` | ⚠️ 未闭环 | |
| P1. PNG 视觉黄金图回归 | ⚠️ 未闭环 | 仍零覆盖 |
| P1. Step5-7 真实数据回归 | ✅ 闭环 | `test_anchor2_full_20260426_baseline_gate` 串通全链路 |
| P2. `step4_review_index.csv` 列与契约差距 | ⚠️ 未闭环 | 67 vs 32 列 |
| P2. `step4_event_evidence.gpkg` schema | ⚠️ 未闭环 | |
| P2. `swsd_relation_type / reject_reason` 枚举 | ⚠️ 未闭环 | |
| P2. perf budget 上契约 | ⚠️ 未闭环 | |
| P2. SpecKit 五视角索引 | ⚠️ 未闭环 | |

**净变化**：✅ 闭环 8 项；⚠️ 仍未闭环 14 项；⚠️ 1 项恶化；⚠️ 1 项翻转（dead → live but misnamed）。

---

## 6. 给 GPT 的整体结论与下一轮建议

### 6.1 模块当前定位
- **业务侧**：T04 已抵达 Anchor_2 23-case full baseline 冻结门槛（20 / 3 业务二态），Step1-7 主链全部对齐契约，跨模块运行时依赖已彻底切净。**可视为 production-grade baseline freeze 的稳定锚点。**
- **治理侧**：14 项已被三轮审计登记的缺口仍未闭环；其中 §1.4 文件体量已逼近停机阈值（95% / 92%），是**技术债首要风险**。

### 6.2 是否需要下一轮迭代

**建议：是，且应升 SpecKit。**

触发条件（满足 `AGENTS.md §6.2` 多条）：
1. `INTERFACE_CONTRACT.md` 需要正式拆分（§3.4 切小节、§3.8 / §3.9 沉到 `architecture/11-frozen-baselines.md`、§6 与 §10 统一 acceptance 数字、§3.7 补 `swsd_relation_type / reject_reason` 枚举、§4 补 schema） → 项目级源事实变更；
2. `_event_interpretation_core.py / step4_road_surface_fork_binding.py` 已逼近 `AGENTS.md §1.4` 停机阈值 → 不可顺手追加，必须先做拆分计划 → 走 SpecKit；
3. `architecture/05` 必须扩展三节（`runtime_support / full_input_orchestration / step4_postprocess`） → 架构面变更；
4. `code-size-audit.md` 必须同轮登记 → 治理面变更；
5. 涉及"业务正确性 + 契约规范性 + 代码结构 + 测试基线"四维交叉，超出 default-imp 边界。

### 6.3 推荐 SpecKit 任务书骨架

```
specs/<run_id>/spec.md
  - Product:
      • 完成 T04 治理冻结：契约 §3.4 / §3.7 / §6 / §10 一致化与去重
      • 数字 acceptance 二选一：保留 §10 (23/20/3)，删除 §6.7 (7/1) 或显式声明 legacy
      • 显式枚举 reject_reason / swsd_relation_type / evidence_source / position_source

  - Architecture:
      • 拆 _event_interpretation_core.py（建议切：unit_preparation / candidate_pool / case_assembly 三段）
      • 拆 step4_road_surface_fork_binding.py（建议切：surface_recovery / structure_only / window_mode / binding_dispatch）
      • _runtime_step4_kernel_reference / _runtime_step4_geometry_reference 改名（kernel_base / geometry_base）
      • 删除 architecture/05 与 step4_*postprocess / full_input_* / _runtime_* 的描述漂移
      • 新增 architecture/11-frozen-baselines.md / architecture/12-glossary.md

  - Development:
      • batch_runner: 加 traceback 落盘；加 run_root sanity guard
      • case_meta.json: 加 input_dataset_hash / git_sha / produced_at
      • REVIEW_INDEX_FIELDNAMES 与 §4.4 对齐
      • _safe_normalize_geometry / silent buffer fix 加显式审计标记

  - Testing:
      • 引入 PNG 视觉黄金图回归（pytest-mpl 或 SHA-256 黄金值）
      • 补 Step6 真实数据 raster-grid 行为锁定
      • 跨平台 fixture：scripts/*.sh 测试加 skipif(os.name=='nt')

  - QA:
      • code-size-audit.md 同轮登记 T04 高风险文件
      • path-conventions.md 落地（AGENTS.md §7 治理缺口）
      • SpecKit 任务包统一索引 specs/index.md（5 视角章节标注）
      • 历史审计闭环表（本文件 §5）刷新
```

### 6.4 不建议立即做的

- ❌ 不要在 main 上直接拆 `_event_interpretation_core.py`：需 SpecKit 流程并伴随同轮 `code-size-audit.md` 更新；
- ❌ 不要"再追加 §3.4 几十行"补 enum / schema：契约本身需要先切分，再补；
- ❌ 不要在不动契约的前提下改 `STEP4_OK` 行为：当前契约已接受 `STEP4_REVIEW` 是常态；
- ❌ 不要单独 hack 857993：契约 §10 已锁定它为正确 rejected。

---

## 7. 本轮审计的边界声明

- **未修改**：本审计未对任何 `INTERFACE_CONTRACT.md / architecture/* / src/* / tests/* / scripts/*` 写入；只新增本文件 `docs/doc-governance/audits/2026-04-26-t04-divmerge-virtual-polygon-deep-audit.md`。
- **已验证**：
  - 模块文档矩阵盘点（§1）。
  - T04 子目录 44 个 `.py` 文件结构清点（§2.1）。
  - `architecture/05` 与代码层级对照（§2.2）。
  - 跨模块依赖 grep（runtime T02 / T03 引用 = 0）。
  - 文件体量盘点：`_event_interpretation_core.py = 94,960` / `step4_road_surface_fork_binding.py = 92,474` / `_runtime_types_io.py = 76,769` 等。
  - 当前 best 全量 run：`outputs/_work/t04_anchor2_full_requested/anchor2_full_all_20260426_724067_surface_apex_fix/{summary.json, step4_review_summary.json, step7_consistency_report.json}`（23 / 20 / 3，与契约 §10 一致）。
  - 测试矩阵盘点：17 个 `test_*.py`，含 `test_anchor2_full_20260426_baseline_gate` 23/20/3 数字门槛。
  - SpecKit 任务包目录盘点：8 个 T04 相关 spec。
  - 入口注册一致性：`scripts/t04_*` 三件套已登记 `entrypoint-registry.md` 行 58-60。
  - 历史审计闭环对照（§5，对 22 / 23 项三轮累计差距做了三档归类）。
- **未实跑**：本轮未触发 `pytest`，未触发 `make test/smoke`，未触发任何 `scripts/t04_*`；测试结果引用以仓库现存 artifact 与既往审计为基础。
- **未审计**：
  - `_runtime_step4_kernel.py / _runtime_step4_kernel_reference.py / _runtime_step4_geometry_*` 全量逐函数语义（仅做接口形态与命名审计）；
  - `step4_road_surface_fork_binding.py / step4_rcsd_anchored_reverse.py` 内部分支策略全量正确性（信任既有测试与 baseline gate）；
  - `qgis-auto-visual-check` Skill 与当前 PNG 的兼容性；
  - `internal_full_input_runner` 在内网 full-input 真实数据上的吞吐与失败率；
  - cross-platform 路径换算正确性。

---

## 8. 关键文件指针（GPT 下钻用）

- 项目级硬规则：`AGENTS.md`
- 项目级生命周期：`docs/doc-governance/module-lifecycle.md`
- 项目级体量审计：`docs/repository-metadata/code-size-audit.md`
- 项目级入口注册：`docs/repository-metadata/entrypoint-registry.md`
- 模块契约：`modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`（41,940 bytes，§3.1-§3.9 / §4.1-§4.7 / §5 / §6）
- 模块架构：`modules/t04_divmerge_virtual_polygon/architecture/{01, 02, 03, 04, 05, 06, 10}.md`
- 模块入口：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/__init__.py`
- 主内核：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py`（**94,960 bytes**，距 100 KB 仅 5,040 bytes）
- Step4 二次后置层：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/{step4_final_conflict_resolver.py, step4_road_surface_fork_binding.py, step4_rcsd_anchored_reverse.py}`
- Step5-7：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/{support_domain.py, polygon_assembly.py, final_publish.py}`
- batch / full-input：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/{batch_runner.py, internal_full_input_runner.py, full_input_*.py}`
- Step7 baseline gate 测试：`tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate`
- 当前 best 全量 run：`outputs/_work/t04_anchor2_full_requested/anchor2_full_all_20260426_724067_surface_apex_fix/`
- 既有审计：
  - `docs/doc-governance/audits/2026-04-22-t04-divmerge-virtual-polygon-deep-audit.md`
  - `docs/doc-governance/audits/2026-04-23-t04-step4-candidate-space-audit.md`
  - `docs/doc-governance/audits/2026-04-23-t04-full-rerun-deep-audit-handoff.md`
- 治理缺口：
  - `docs/repository-metadata/path-conventions.md`（缺失）
  - `modules/t04_divmerge_virtual_polygon/architecture/{11-risks-and-technical-debt.md, 12-glossary.md}`（缺失）
  - `modules/t04_divmerge_virtual_polygon/{review-summary.md, history/, CHANGELOG.md}`（缺失）

---

> 审计结束。请 GPT 决策（A）启动 SpecKit 治理迭代以闭环 14 项历史缺口与 2 项体量风险；（B）维持当前 baseline freeze 不动，仅做单点修补；（C）确认 T04 收尾、转入下一模块。
