# T04 全量审计与 GPT 握手（2026-04-23）

> 本文件供 GPT 线程作为下一轮 SpecKit / default-imp 决策输入，仅审计结论，不含代码改动。
>
> 审计触发：用户已对 `E:\TestData\POC_Data\T02\Anchor_2` 全量 8 case 完成人工目视审查（Step4 review PNG 通过），要求"再做一次深层全量审计，重点覆盖契约、需求清晰度、实现差异、架构、质量、性能与其他你认为应审的项"。
>
> 审计范围：
> - 文档：`modules/t04_divmerge_virtual_polygon/{AGENTS.md, README.md, INTERFACE_CONTRACT.md, architecture/01-06,10}`
> - 代码：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/**` 共 42 个 `.py`（约 24.3K 行）
> - 测试：`tests/modules/t04_divmerge_virtual_polygon/**` 共 9 个 `test_*.py`
> - 入口脚本：`scripts/t04_*.sh`、`docs/repository-metadata/entrypoint-registry.md`
> - 全量回归实跑：`outputs/_work/t04_anchor2_full_rerun/anchor2_full_*_20260423/*`（今日 4 次迭代结果）
> - 既有审计：`docs/doc-governance/audits/2026-04-22-t04-divmerge-virtual-polygon-deep-audit.md`、`2026-04-23-t04-step4-candidate-space-audit.md`
>
> 审计执行环境：本地 PowerShell + Python 3.12.9，`PYTHONPATH=src`，pytest 完整跑通；Anchor_2 测试数据在用户磁盘可访问。

---

## 0. TL;DR：握手判定建议

**建议 GPT 启动一次 SpecKit 迭代**（不要默认 default-imp 收尾）。理由：

| 维度 | 现状 | 与契约对齐情况 |
|---|---|---|
| 文档规范性 | 较 04-22 略有改善，但 2026-04-22 列出的 12 条 P0/P1/P2 文档治理缺口**绝大多数仍未闭环** | ⚠️ 未达对齐 |
| Step1-4 主链路 | 8 case / 13 unit 全部 `positive_rcsd_present=true / primary_support / A`，正向 RCSD 已稳定，目视通过 | ✅ 业务侧达标 |
| Step5-7 主链路 | 今日 4 次迭代后从 `accepted=3/8` 提升到 `accepted=7/8`；最后 1 个 case (857993) 仍以 `multi_component_result` 被拒 | ⚠️ 未完全达标 |
| STEP4 状态机分布 | `STEP4_OK=0`、`STEP4_REVIEW=13`、`STEP4_FAIL=0`，**13/13 全部退化到 REVIEW**，全部命中 `degraded_scope:pair_local_scope_roads_empty` (severity=soft) | ⚠️ 实现回路存在永久 soft-degrade |
| 单测套件 | `27 passed / 18 skipped / 2 failed` | ⚠️ 1 个真实业务失败 + 1 个跨平台失败 |
| 代码体量 | `_event_interpretation_core.py = 87,975 bytes`（距 100 KB **不到 12 KB**），`_runtime_types_io.py = 76,769 bytes` | ⚠️ 距 §1.4 停机阈值不足一轮 |
| 跨模块依赖 | T02 代码运行时引用**已清零**（grep 0 matches），但 `_runtime_stage4_execution_contract.py` 与 T02 同名文件**逐行硬拷贝** | ⚠️ 形态违规 |
| 死代码 | `_runtime_step4_kernel_reference.py`（65,297 bytes）**无任何 importer**；`test_step14_pipeline.py` 是空 stub 指向不存在文件 | ⚠️ 净增结构债 |
| 测试覆盖 | 契约 §3.8 / §3.9 冻结的 8 case / 13 unit 在测试层**只被松散覆盖**；`785675 / 987998 / 30434673` 无专用回归用例 | ⚠️ 回归闸门弱 |

**握手优先级（按影响 × 紧迫度）**：

- **P0** — 修复 `857993` 仍被拒（`multi_component_result`）；明确 `degraded_scope:pair_local_scope_roads_empty` 永远 soft 触发是设计还是缺陷；裁掉 `_runtime_step4_kernel_reference.py` 死文件；修复 `test_aggregated_rcsd_unit_upgrades_multiple_partial_local_units` 失败。
- **P0** — 闭环 2026-04-22 deep audit 中仍未处理的 P0 三项（`event_interpretation` 拆分、文档去重、T02 private API façade）。当前虽然运行时 import 已去除，但**`_runtime_stage4_execution_contract.py` 是 T02 同名文件硬拷贝**，违反 `AGENTS.md` 与 `INTERFACE_CONTRACT.md` 关于"不得直接 import / 调用 / 硬拷贝 T02 模块代码"。
- **P1** — Step5-7 缺乏 Anchor_2 真实数据回归测试；视觉黄金图（golden PNG）回归零覆盖；`code-size-audit.md` 仍是 2026-04-14 数据，T04 高风险文件未入表。
- **P2** — 契约 §3.4 / §3.8 / §3.9 仍把 case_id / road_id 作为正式契约写入；`step4_review_index.csv` 实际 ~58 列与契约 §4.4 的 26 列差距未闭环；`step4_event_evidence.gpkg` 仍无 schema。

---

## 1. 模块契约（文档侧）符合度

### 1.1 阅读顺序与 Day-0 文档集

| 项 | 要求 | 现状 | 结论 |
|---|---|---|---|
| `AGENTS.md` | 必建 | 1,313 bytes，含范围、与 T02/T03 边界、复用线、Step4 review state 命名约束 | ✅ |
| `INTERFACE_CONTRACT.md` | 必建，唯一稳定契约 | 37,229 bytes，覆盖 §1-§6 | ✅（但内容仍偏胖，见 §1.3） |
| `architecture/01-introduction-and-goals.md` | 必建 | 851 bytes | ✅ |
| `architecture/03-context-and-scope.md` | 必建 | 1,107 bytes | ✅ |
| `architecture/04-solution-strategy.md` | 必建 | 15,241 bytes | ⚠️ 与 `INTERFACE_CONTRACT §3.4` 双源近重复（2026-04-22 P0，**未闭环**） |
| `architecture/02 / 05 / 10` | 建议尽早补齐 | 已具备 | ✅ |
| `architecture/06-step34-repair-design.md` | 非 arc42 标准章节 | 8,544 bytes | ⚠️ 缺 README/01 显式裁剪声明（2026-04-22 1.2.B，**未闭环**） |
| `architecture/07/08/09/11/12` | 建议补齐 | 缺 | ⚠️ 不阻断，但 11/12 缺失影响 `frozen baseline` 与 glossary 治理 |
| `README.md` | 操作者入口 | 2,870 bytes，路径仍用 `/mnt/e/...`（PowerShell 不可直接执行） | ⚠️ 与 `path-conventions.md` 治理缺口同步 |
| `review-summary.md` / `history/` | 模块成熟后 | 不存在 | ⚠️ 推荐补齐，便于 GPT 跨轮做 diff |

### 1.2 契约 vs 项目级硬规则（`AGENTS.md`）

| 硬规则 | 检查点 | 结果 |
|---|---|---|
| §1.1 源事实之间不得冲突 | `architecture/04 §3` 与 `INTERFACE_CONTRACT §3.4` 仍是平行重述 | ⚠️ 未闭环 |
| §1.2 入口治理 | T04 当前不新增 repo 官方 CLI；`scripts/t04_*` 三件套均已登记 `entrypoint-registry.md` 行 54-56 | ✅ |
| §1.4 / §3 文件体量 | `_event_interpretation_core.py = 87,975 bytes` (88% 阈值)；`_runtime_types_io.py = 76,769 bytes` (77%)；`_runtime_step4_kernel_reference.py = 65,297 bytes` (66%) | ⚠️ 高风险预警未入 `code-size-audit.md` |
| §5 GIS 5 项 | CRS gate 在 `case_loader.py L55-58` 与 `_runtime_shared.py` 一处；其余 step4/5/6/7 内核**默认假设已为 EPSG:3857**，无 runtime assertion | ⚠️ 静默假设 |
| §6.1 default-imp / §6.2 SpecKit | 当前 Step5-7 实现已完成主链路；下一轮如再触碰契约层，应明确升 SpecKit | ⚠️ 决策面 |
| §7 路径换算 | `README.md / 测试 fixture` 强依赖 `/mnt/e/...`；PowerShell 会话直接 unusable | ⚠️ 同 `path-conventions.md` 治理缺口 |

### 1.3 契约本身的规范性问题（仍未闭环）

来自 2026-04-22 deep audit，**本轮复核发现以下条目仍存在**：

- **A. 双源近重复**：`INTERFACE_CONTRACT §3.4`（约 230 行单段）与 `architecture/04 §3`（约 170 行）仍平行重述。任意一边被修改即触发 `AGENTS.md §1.1` 风险。
- **C. §3.4 单段过长**：本次复核 `INTERFACE_CONTRACT §3.4` 已扩张到 ~220 行无小节，并新增 §3.5-§3.9（Step5-7 与冻结基线），单文件 37 KB；`§3.4` 子小节切分仍未做。
- **D. Acceptance 不可度量**：`§6` 6 条仍是"已存在 / 可运行 / 已纳入 / 默认遵循 / 不得拷贝 / 以 final_review.png 为准"，**没有任何数字门槛**（如 "Step4 OK 数 / Step7 accepted_count / 性能预算"）。
- **E. 输出 schema 不全**：`step4_review_index.csv` 实际 67 列（见 `outputs/.../step4_review_index.csv` 表头），契约 §4.4 列 32 列；多出来的 ~35 列没有契约定义。`step4_event_evidence.gpkg` / `step5_domains.gpkg` / `divmerge_virtual_anchor_surface_audit.gpkg` 全部**没有图层 schema**。
- **F. 冻结基线写进契约的副作用**：`§3.8 / §3.9` 把 `case_id / road_id pair / divstrip:N:01` 形态写进契约，`§10 quality requirements` 又写一次"冻结守门 case"，这意味着每次审计通过新 case 都会改契约。建议拆 `architecture/11-frozen-baselines.md`。
- **H. 缺项**：仍无 `CHANGELOG.md` / "last-updated" 头；STEP4_FAIL 的下游语义无定义（Step5-7 是否会自动放弃？）；Step4-Step5 字段稳定性表缺失。

### 1.4 新增问题

- **`AGENTS.md` 与 `INTERFACE_CONTRACT.md` 关于 T03 关系**：`AGENTS.md` 第 13 行禁止 "直接 import / 调用 / 硬拷贝 T03 模块代码"；`INTERFACE_CONTRACT §1` 第 32 行同口径；`architecture/02-constraints.md` 第 18 行只说 "优先复用 T03 的 case-package / batch / review 输出组织"。三处口径**口语上存在歧义**，应统一表述。
- **`architecture/05-building-block-view.md` 缺 `full_input_*` 大块描述**：实际代码中 `full_input_bootstrap / full_input_case_pipeline / full_input_observability / full_input_perf_audit / full_input_shared_layers / full_input_streamed_results / internal_full_input_runner` 共 7 个文件构成一个完整 building block，但 05 完全没提。`architecture/05` 应增加 `full_input_orchestration` 一节。

---

## 2. 需求是否清晰准确

### 2.1 业务语义

- **正向 RCSD A/B/C 链路** 在 `INTERFACE_CONTRACT §3.4 L246-L312` 描述完整、与 `rcsd_selection.resolve_positive_rcsd_selection` 对得上；2026-04-22 P1 中 "T02 私有 API 越界引用" **本轮复核已解除**（`grep -r "from rcsd_topo_poc.modules.t02" src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/` 无匹配）。✅
- **Step3 双层 skeleton** 在 `INTERFACE_CONTRACT §3.3` 与 `outputs.build_unit_step3_status_doc` 对得上。✅
- **Step5 must/allowed/forbidden/terminal_cut** 在 `§3.5` 与 `support_domain.build_step5_support_domain` 对得上。✅

### 2.2 仍不够清晰的地方

- **Step4 候选空间硬阈值**：`§3.4` 写"continuation 硬上限 200m"，但代码 `EVENT_REFERENCE_SCAN_MAX_M = 140.0`，实际还会被 `min(140, max(20, patch_size_m * 0.45))` 二次压缩。已在 2026-04-23 candidate-space audit 列为 P0，**未闭环**。
- **"分支太远停止"阈值未定义**：契约 `§3.4 L173` 只说 `branch_separation_too_large` 必须出现，但不写米数；代码用 `EVENT_CROSS_HALF_LEN_MAX_M = 130.0` 隐式触发。
- **`degraded_scope_severity` 的判定标准**：`§3.4 L327-L331` 写 `soft / hard` 二态，但**未给具体判据**。当前实现下 `pair_local_scope_roads_empty` 永远落 `soft`（见 `_event_interpretation_core.py L1245`），导致 13/13 unit 全部 `STEP4_REVIEW`。
- **Step7 `swsd_relation_type` 取值集**：`final_publish.py` 代码可产出 `partial / covering / unknown / offset_fact / no_relation` 等，但契约 `§3.7` 完全没有列举。今日运行 `summary.csv` 已出现 `offset_fact`（785671/785675/987998/73462878），未在契约。
- **Step7 `reject_reason / reject_reason_detail` 集**：契约 `§3.7` 未枚举；今日运行有 `final_polygon_missing / multi_component_result / hard_must_cover_disconnected / b_node_not_covered / assembly_failed` 5 类，需要在契约固化。

---

## 3. 实现 vs 需求差异

### 3.1 已闭环（与 2026-04-22 audit 对照）

| 2026-04-22 列出的差异 | 当前状态 |
|---|---|
| P1. T02 私有 API 越界引用（13 个符号） | ✅ 已清零（grep 0 matches） |
| 主链路完成度 Step1-4 | ✅ 维持 |
| 主链路完成度 Step5-7 | ✅ 已落地（support_domain / polygon_assembly / final_publish） |

### 3.2 未闭环（需 GPT 决策）

#### A. **`_runtime_stage4_execution_contract.py` 与 T02 同名文件逐行相同**（高优先级）

- 文件：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_stage4_execution_contract.py` (3,864 bytes)
- 镜像：`src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_execution_contract.py`（同结构、同函数签名、同常量集）
- 引用方：`admission.py` 从 T04 私有路径导入
- 违反：`AGENTS.md` 第 13 行 "**禁止把 T02 大一统 orchestrator 直接平移为 T04 主结构**"；`INTERFACE_CONTRACT §1` 第 32 行 "**不得直接 import / 调用 / 硬拷贝 T02 模块代码**"。
- 风险：T02 改 contract → T04 不会自动同步 → 静默 drift。

#### B. **STEP4_OK 永远为 0**（中-高优先级）

- 今日 4 次 anchor2 全量回归，`STEP4_OK = 0`，`STEP4_REVIEW = 13`，`STEP4_FAIL = 0`。
- 根因：`_event_interpretation_core.py L1242-1245` 当 `pair_local_scope_roads` 为空时一律 append `pair_local_scope_roads_empty` 进 `degraded_scope_reason`；L1747-1750 只要 `degraded_scope_reason` 非空就把 review_state 升到 `REVIEW`。
- 13/13 unit 全部触发同一原因（`degraded_scope_severity=soft`），即"**`STEP4_REVIEW` 在生产数据上是常态而不是异常**"。
- 与契约 `§3.4 L324-L331` 的语义不符："仅 `soft` degraded 可继续维持 `STEP4_REVIEW`；候选空间语义已实质丢失时升 `STEP4_FAIL`"。当前实现没有任何路径升 FAIL。
- 决策建议：要么收紧 `pair_local_scope_roads_empty` 的触发条件（不是所有 unit 都该 fire），要么承认 STEP4_OK 实际上是不可达状态并把契约改为 `REVIEW / FAIL` 二态。

#### C. **Step7 多 case 拒绝**（中优先级）

今日 4 次迭代回归（`run_id` 时间序列）：

| run_id | accepted | rejected | 主要 reject reason |
|---|---:|---:|---|
| `anchor2_full_current_fix_20260423` (18:06) | 3 | 5 | final_polygon_missing × 4，multi_component_result × 1 |
| `anchor2_full_terminal_anchor_fix_20260423` (18:11) | （未细查） | | |
| `anchor2_full_rcsd_publish_fix_20260423` (19:59) | （未细查） | | |
| `anchor2_full_rcsd_support_graph_fix_20260423` (20:03) | **7** | **1** | multi_component_result × 1 (857993) |

- **正向**：4 次迭代显著收敛，最终 7/8 accepted。
- **遗留**：`857993` 仍被拒，`step6_status.json` 显示 `component_count=3`、`hard_must_cover_disconnected`、Layer1/Layer2/Layer3 候选都过不了"组装单连通"。
- **风险**：用户主张"目视通过"是基于 `final_review.png`（Step4 层），并非基于 `divmerge_virtual_anchor_surface_summary.csv` 的 final_state；用户**很可能未注意到 Step7 仍有 1 个 reject**。需 GPT 与用户对齐。
- 决策建议：把 857993 升 P0；同时在 `INTERFACE_CONTRACT §6` 增加 "Acceptance 必须包含 Anchor_2 baseline `accepted_count` 数字门槛"，否则 visual 通过 ≠ 业务通过。

#### D. **`_runtime_step4_kernel_reference.py` 死代码**（低-中优先级）

- 文件：`_runtime_step4_kernel_reference.py` (65,297 bytes，约 2,900 行)
- grep 全仓 `_runtime_step4_kernel_reference` 无任何 importer。
- 与 `_runtime_step4_kernel.py` (56,450 bytes) 并列存在，命名暗示 "reference 实现 vs 生产实现"，但代码层面 reference 已被孤立。
- 风险：65 KB 死代码 + 占用 100 KB 阈值 65%，未来易被误维护。

#### E. **测试 `test_step14_pipeline.py` 是空 stub**

- 文件 hint：原本应承担"主管道集成测试"职责（2026-04-22 audit P7 已警示），现状是几乎空文件指向不存在的拆分文件。
- explore 子代理报告："points at split files that are not present in this tree"。
- 与 `INTERFACE_CONTRACT §3.8 L435` "若审计工件缺失，以本契约与 `tests/modules/t04_divmerge_virtual_polygon/test_step14_*.py` 的冻结断言为准" **冲突**：契约把回归闸门指给测试，但测试不存在。

#### F. **测试失败：`test_aggregated_rcsd_unit_upgrades_multiple_partial_local_units`**

- 命中：`tests/modules/t04_divmerge_virtual_polygon/test_positive_rcsd_selection.py:101`
- 断言：`set(decision.selected_rcsdroad_ids) >= {"rc_axis", "rc_mid", "rc_right", "rc_left"}`
- 实际：缺 `rc_left`
- 根因（子代理分析）：`_published_rcsd_subset` 在 A 类一致性下重建于 primary local unit `role_assignments` + `aggregated_positive_branch_road_ids` + 必要 trace；不是把 aggregated 全量 road ids 落入 `selected_rcsdroad_ids`。这与契约 `§3.4 L300` "selected_rcsdroad_ids 表达供 Step5-7 正式下游消费的 publish/core 子集；当前冻结实现优先取 primary local unit core roads + 必要 trace；聚合全量 component 成员必须保留在 positive_rcsd_audit" 一致。
- 结论：**测试期望与契约口径不一致**。要么改测试（更可能正确），要么明确改契约把 publish 子集要求扩到全量。需 GPT 决策。

#### G. **Step1 `kind=128` 准入路径仍走 T02 内部**

虽然 runtime 不再 import T02 私有 API，但 `admission.py` 通过 `_runtime_stage4_execution_contract.py` 间接复用 T02 的 `evaluate_stage4_candidate_admission` 逻辑（即上述 A 项的硬拷贝结果）。从 T04 源码无法独立审出"我是怎么承认 128 的"。需要在 `admission.py` 内显式落地。

---

## 4. 架构合理性

### 4.1 层级与契约对照

| `architecture/05` 声明 | 实际文件 | 状态 |
|---|---|---|
| `case_loader` | `case_loader.py` | ✅ |
| `admission` | `admission.py` + `_runtime_stage4_execution_contract.py` | ⚠️ 后者是 T02 硬拷贝 |
| `local_context` | `local_context.py` (薄包装) + `_runtime_step2_local_context.py` | ✅ |
| `topology` | `topology.py` (薄包装) + `_runtime_step3_topology_skeleton.py` | ✅ |
| `event_units` | `event_units.py` | ✅ |
| `event_interpretation` (含 5 子块) | `event_interpretation.py` + `event_interpretation_shared / branch_variants / selection / variant_ranking / rcsd_selection` + `_event_interpretation_core / _runtime_step4_*` 7 个 runtime | ⚠️ runtime 文件群未在 `05` 描述 |
| `review_render` | `review_render.py + review_audit.py` | ✅ |
| `support_domain` | `support_domain.py` | ✅ |
| `polygon_assembly` | `polygon_assembly.py + _runtime_polygon_cleanup.py` | ✅ |
| `final_publish` | `final_publish.py + step4_final_conflict_resolver.py` | ⚠️ resolver 不在 `05` |
| `outputs` | `outputs.py` | ✅ |
| `batch_runner` | `batch_runner.py + internal_full_input_runner.py + full_input_*` 7 个 | ⚠️ `full_input_*` 大块缺 `05` 描述 |

**结论**：层级骨架基本符合，但 `_runtime_*` 私有内核与 `full_input_*` orchestration 集群在 `architecture/05` 中**完全未表述**。建议补 `architecture/05` 增加两节：`runtime support modules` 与 `full_input orchestration`。

### 4.2 体量

| 文件 | bytes | 距 100 KB |
|---|---:|---:|
| `_event_interpretation_core.py` | **87,975** | **12,025** |
| `_runtime_types_io.py` | 76,769 | 23,231 |
| `_runtime_step4_kernel_reference.py` | 65,297 | 34,703（死代码） |
| `_runtime_step4_geometry_core.py` | 64,063 | 35,937 |
| `support_domain.py` | 56,805 | 43,195 |
| `_runtime_step4_kernel.py` | 56,450 | 43,550 |
| `_runtime_step4_geometry_reference.py` | 48,003 | 51,997 |
| `_rcsd_selection_support.py` | 43,582 | 56,418 |
| `outputs.py` | 35,345 | 64,655 |
| `review_render.py` | 35,013 | 64,987 |
| `step4_final_conflict_resolver.py` | 34,718 | 65,282 |
| `rcsd_selection.py` | 29,089 | 70,911 |
| `final_publish.py` | 27,915 | 72,085 |
| `case_models.py` | 25,829 | 74,171 |
| `polygon_assembly.py` | 25,349 | 74,651 |

- **`_event_interpretation_core.py` 距硬阈值 12 KB**，下一轮 P0 改动如果再追加几个 helper（譬如 D 项 STEP4_OK 修复）就会触发 `AGENTS.md §1.4` 停机。
- 2026-04-22 audit P0 拆分方案（`event_interpretation` 5 文件拆分）**未实施**；本轮 `_event_interpretation_core.py` 仍是 `_materialize_prepared_unit_inputs` (~500 行) + `build_case_result` (~240 行) + 多个候选评估器。
- `code-size-audit.md` (2026-04-14) 只列 T02 / 测试两个超阈值文件，T04 高风险预警**未入表**。本轮如果做拆分，必须按 `AGENTS.md §3` 同轮更新该表。

### 4.3 跨模块依赖

- `t02_junction_anchor.*` runtime 引用：**0 处**（已清零）✅
- `t03_virtual_junction_anchor.*` runtime 引用：**0 处** ✅
- `t00_utility_toolbox` / `t01_data_preprocess` 引用：仅工具函数（CRS、IO、build_run_id），符合 ✅
- 但 `_runtime_stage4_execution_contract.py` 是 T02 同名文件逐行硬拷贝 → 按 `AGENTS.md` "硬拷贝" 视角属于违规 ⚠️

### 4.4 `event_interpretation` 子模块切分

- 现状：`event_interpretation.py` (15,642 bytes facade) + `_event_interpretation_core.py` (87,975 bytes 主内核) + 5 子模块。
- 与 `architecture/05` 描述对得上的"facade / shared / branch_variants / selection / ranking" 五块都已存在，**但 `_event_interpretation_core.py` 仍承担 7 大职责**（同 2026-04-22 audit §3.2）。

---

## 5. 代码质量

### 5.1 错误处理

- **`batch_runner.run_t04_step14_batch`** 仍裸吞 `except Exception` 把 case_id 加进 `failed_case_ids`，**不写 traceback**（2026-04-22 P4 未闭环）。
- **`run_root` 已存在即 `shutil.rmtree`**（同 2026-04-22 P5 未闭环）。今日 4 次回归没出问题，但若调用方传错 `out_root`，可能销毁历史审计工件。

### 5.2 死代码 / 重复

- `_runtime_step4_kernel_reference.py` 65 KB 死代码（前述）。
- `_runtime_step4_geometry_reference.py` 48 KB **不是**死代码（被 `_event_interpretation_core` import），但与 `_runtime_step4_geometry_core.py` 的关系是 `from ._runtime_step4_geometry_core import *` + 增量补充。命名歧义"core vs reference"易误读。
- `_runtime_stage4_execution_contract.py` 是 T02 硬拷贝（前述）。
- `test_step14_pipeline.py` 空 stub。

### 5.3 配置 / 常量

- 所有 Step4 行为常量散落在 `_event_interpretation_core.py L83-L89`、`_runtime_step4_geometry_core.py L92-L116`、`event_interpretation_branch_variants.py L27-L29` 等 ≥ 6 处。
- 没有 `T04_CONFIG` 集中类，无法在审计工件 `case_meta.json / preflight.json` 一处落"本轮 run 用的所有阈值"。
- `case_meta.json` 不含输入数据集 hash / mtime / git SHA（2026-04-22 §4.6 未闭环）。

### 5.4 命名 / API

- `run_t04_step14_batch` / `run_t04_step14_case` 名字停留在 "Step1-4" 时代，但实际跑 Step1-7 全链路。**API 命名与契约不一致**，外部调用方读 README 易误解为"只跑 Step4"。
- `outputs.py` 仍叫 `step14_*`：`materialize_review_gallery / write_review_summary` 都是 Step4 视角，但同一函数体也写 Step5-7 工件。

### 5.5 GIS 静默修复

- 全仓 `buffer(1e-6)` / `buffer(0)` 共 ≥ 11 处（`support_domain.py` / `polygon_assembly.py` / `_runtime_step4_geometry_*`）。每一处都需要审 "是否会吞掉真正的拓扑错误"（同 2026-04-22 §4.3 未闭环）。
- `_event_interpretation_core.py` 与 `_runtime_step4_geometry_core.py` 中 `_safe_normalize_geometry / _safe_unary_union` 等"safe-wrappers"在 except 分支 silent return None，可能掩盖真实 invalid geometry。

---

## 6. 性能

### 6.1 已具备

- `full_input_shared_layers.py` 用 `STRtree + query_spatial_index` 做 case-package discovery（行 105-119、203-208、273-296）✅
- `internal_full_input_runner.py` 用 `ThreadPoolExecutor` per-case 并行（行 ~483）✅

### 6.2 风险

- **核心 case-package 路径 `_event_interpretation_core` 内部不显式使用 STRtree**：所有 `scoped_*` 过滤是线性扫描；当 case 内 unit 数 / road 数较大时为 O(unit × road)。
- **`_select_case_assignment` 指数级回溯**（2026-04-22 §4.2 未闭环）：`MAX_CANDIDATES_PER_UNIT = 6`，N 个 unit 即 7^N。Anchor_2 当前 N ≤ 4（`17943587` 4 unit），未触发。但 multi-merge 大场景未来会爆。
- **`polygon_assembly._connect_hard_seed_components` / `_constrain_geometry_to_case_limits` 在每个 unit 重复 buffer**：raster grid 已构建，但 vector clean 反复 constrain 相同 case_limits（同子代理 §5）。
- **重复 IO**：每 case `step5_audit.json / step6_audit.json / step7_audit.json` 都重复写入相似 metadata（case_id / paths）；批量 close-out 时 `final_publish.write_step7_batch_outputs` 会再读一次每 case 的 step7 audit。
- **本轮回归吞吐**：8 case full pipeline 从 18:06 起到 20:03 共 4 次完整跑，每次 < 5 分钟（按 timestamp 推算）。当前规模性能可接受；但缺**性能预算契约**（2026-04-22 §1.2.D 未闭环）。

### 6.3 缺失指标

- 没有 perf budget 写入 `INTERFACE_CONTRACT §6`：每 case 端到端时间预算、`case_count × event_unit_count × road_count` 复杂度上限、内存预算都没有 SLO。
- 没有 `t04_perf_audit.json` 顶层口径；`full_input_perf_audit.py` 是 internal full-input 专属，case-package 路径不产 perf 工件。

---

## 7. 测试质量

### 7.1 单测概况

- pytest：`27 passed / 18 skipped / 2 failed`，耗时 ~18s。
- 2 个 failed：
  1. `test_t04_internal_full_input_watch_once`：`subprocess.run(['scripts/t04_..._innernet_flat_review.sh'])` 在 Windows PowerShell 下 `[WinError 193]`（.sh 不可直接执行），属于跨平台 fixture 问题，**非业务缺陷**，但应 `pytest.mark.skipif(os.name == "nt")`。
  2. `test_aggregated_rcsd_unit_upgrades_multiple_partial_local_units`：见 §3.2 F。**真实业务/契约口径分歧**。
- 18 个 skipped 多数因为 Anchor_2 数据不可用 / 平台限制。需 GPT 评估"在 CI 环境下测试是否能真实回归"。

### 7.2 契约 §3.8 / §3.9 冻结基线 vs 测试覆盖

| 冻结样本 | 测试覆盖 | 强度 |
|---|---|---|
| `760213` (node_760213, node_760218) | `test_real_same_case_sibling_continuation` | 松散，未冻结 §3.9 divstrip 基线 |
| `785671` (event_unit_01) | `test_forward_official_direction` | 松散 |
| `785675` | **无** | ❌ |
| `857993` (node_857993, node_870089) | `test_857993_node_870089_*` | 部分（仅 RCSD road id） |
| `987998` (event_unit_01) | **无** | ❌ |
| `17943587` (4 nodes) | `test_real_anchor2_*` + `test_17943587_keeps_*` | 松散，仅 audit/Step5 |
| `30434673` | **无** | ❌ |
| `73462878` (event_unit_01) | 与 17943587 共测一项 | 松散 |

### 7.3 Step5/6/7 测试

- `test_step5_support_domain.py / test_step6_polygon_assembly.py / test_step7_final_publish.py`：**纯合成数据**（`1001 / 1002 / 2002`），**无 Anchor_2 真实数据回归**。
- `test_positive_rcsd_publish_subset_real.py` 唯一一个把 `857993 / 17943587` 真实数据带入 Step5 子流程的测试，但只验 `related_rcsd_road_ids`，不验 `must_cover / allowed / forbidden / terminal_cut` 完整性。
- 与 `INTERFACE_CONTRACT §10.可回归性 L99-L102` "Step5-7 回归顺序固定为：先单 case → 再 batch → 最后做发布层与汇总层核对" **不符**。

### 7.4 视觉黄金图回归

- **零覆盖**。当前所有 PNG 仅做 "存在 / 计数 / 命名" 检查，不做像素级 / 感知级 diff。
- 用户的"目视审查通过"是 T04 当前唯一的接受证据，但 CI 没有任何方式锁定"下次改动后图像不漂"。
- 推荐：引入 `pytest-mpl` 或 hash-based 黄金图对比；或在 `tests/` 下落 `golden/` 目录，比 SHA-256；或调用 `qgis-auto-visual-check` Skill 做 in-road coverage ratio 黄金值固化。

### 7.5 测试结构

- `test_step14_pipeline.py` 空 stub，文档级声明（契约 §3.8 L435）说 "fixture 真相在此"，实际指向不存在文件。
- `test_step14_synthetic_batch.py / test_step14_candidate_space_normalization.py` 各 1 个文件承载多类断言（多用 `import * from test_step14_support`）。
- 没有按"Step1 / Step2 / Step3 / Step4 candidate / Step4 evidence / Step4 RCSD / Step5 / Step6 / Step7" 的契约分层切分。

---

## 8. 其他需审计点

### 8.1 治理同步

- `docs/repository-metadata/code-size-audit.md` 仍是 2026-04-14 数据；T04 高风险文件（`_event_interpretation_core.py 88KB / _runtime_types_io.py 77KB / _runtime_step4_kernel_reference.py 65KB死代码`）**未入表**。下次任何 T04 拆分动作必须同轮更新。
- `docs/repository-metadata/path-conventions.md` 仍是缺口。T04 README 默认路径 `/mnt/e/...` 在 PowerShell 不可用。
- `docs/repository-metadata/entrypoint-registry.md` 中 T04 三件套已登记 ✅。

### 8.2 审计可追溯性

- `case_meta.json` 不含 input dataset hash / mtime / git SHA → 无法回溯"当前 run 的输入是哪个版本的 Anchor_2"（同 2026-04-22 §4.6）。
- `summary.json / preflight.json` 不含代码版本 / git SHA。
- `step4_audit.json / step5_audit.json / step6_audit.json / step7_audit.json` 字段在契约 §4 中只一行带过，没有列出关键字段。

### 8.3 输入字段管控（`AGENTS.md §5`）

- 当前用到的输入字段列表在 `INTERFACE_CONTRACT §2.2` 已声明：`id / mainnodeid / has_evd / is_anchor / kind|kind_2 / grade_2 / snodeid / enodeid / direction`。✅
- 没有显式声明 "DivStripZone 必需字段集" / "RCSDRoad 必需字段集" / "RCSDNode 必需字段集"，仅在代码实现里隐式假设。建议在 §2.2 显式补齐。

### 8.4 与 SpecKit 守则的一致性

- `INTERFACE_CONTRACT §1` 与 `AGENTS.md` 都说 Step5-7 正式研发"默认遵循 SpecKit"；当前 Step5-7 已有实现，但**没有显式 SpecKit 任务书 / specs/<id>/spec.md / plan.md / tasks.md / implementation 工件**留痕（特别是 `specs/` 目录里看不到对应 T04 Step5-7 的任务工件）。
- 这与 `AGENTS.md §6.3` "任务书必须显式覆盖 Product / Architecture / Development / Testing / QA"不符。本轮 GPT 决策时建议 SpecKit 任务书显式覆盖。

### 8.5 工件物化与 GPS

- `step6_status.json / step6_audit.json` 在 `857993` 显示 `component_count=3`，意味着 raster-first 组装出了 3 个独立片，未能 connect。`hard_connect_notes=["hard_must_cover_disconnected"]` 说明 `_connect_hard_seed_components` 没把 must-cover seeds 连起来。需要审 `polygon_assembly._connect_hard_seed_components` 的 raster connect kernel 半径与 dilation 是否需要参数化。

---

## 9. 整体结论与给 GPT 的握手建议

### 9.1 当前 T04 主链路状态

- **Step1-4** 业务正向稳定，13/13 unit `positive_rcsd_present=true`，目视通过。
- **Step5-7** 业务侧今日已收敛到 7/8 accepted，但**仍有 1 个 case 未通过**，且用户大概率没意识到（用户审的是 PNG，不是 final_state）。
- **STEP4_OK 0%** 是实现回路问题，与契约定义不符。
- **代码层面**：T02 私有引用已清零（大胜利），但出现 T02 硬拷贝、死代码与逼近 100 KB 阈值的大文件，风险代偿。

### 9.2 是否需要再迭代

**建议：是，需要再迭代一轮，且应升 SpecKit。**

理由（满足 `AGENTS.md §6.2` 升 SpecKit 触发条件）：
- 任务跨"业务正确性 + 契约规范性 + 代码结构 + 测试基线"四个维度，属于跨模块结构治理。
- 涉及 Step4 状态机语义重定义（OK/REVIEW/FAIL）、Step7 acceptance 数字门槛入约、`_event_interpretation_core` 拆分、Step5-7 真实数据回归补齐 → 任意一项落 default-imp 都会顺手扩大边界。
- `INTERFACE_CONTRACT §3.4 / §3.7 / §6` 需要正式改动 → 项目级源事实变更，必须走 SpecKit。

### 9.3 推荐的 SpecKit 任务书骨架

```
specs/<run_id>/specify.md
  - Product：完成 T04 全链路 acceptance gate（含 STEP4_OK 可达性 + Step7 全 case accepted）
  - Architecture：拆 _event_interpretation_core；删 _runtime_step4_kernel_reference 死代码；
                   消除 _runtime_stage4_execution_contract 与 T02 硬拷贝；落 architecture/05 缺失模块描述
  - Development：修复 857993 multi_component；调整 pair_local_scope_roads_empty 触发条件；
                   修复 test_aggregated_rcsd_unit；补 batch_runner traceback 落盘
  - Testing：补 Anchor_2 8 case × Step5-7 真实回归；按 step 切分单测；引入视觉黄金图
  - QA：契约 §3.4 / §3.7 / §6 / §4 字段对齐与去重；code-size-audit 同轮更新；
        path-conventions.md 落地；case_meta.json 增加 input hash / git SHA
```

### 9.4 不需要做的

- 不要再独立扩 `INTERFACE_CONTRACT §3.4`（已经 230 行）；改动应是切分而非追加。
- 不要为修 857993 单 case 而 hack 几何阈值；应作为 Step6 组装算法稳健性问题来对待。
- 不要把 `_runtime_step4_kernel_reference.py` "再续一段"；应先确认是否删除。
- 不要在 main 上直接做拆分；按 `AGENTS.md §4` "中等及以上结构化治理变更走 SpecKit"。

---

## 10. 本轮审计的边界声明

- **未修改**：本审计未对任何 `INTERFACE_CONTRACT.md / architecture/* / src/* / tests/*` 写入；只新增本文件 `docs/doc-governance/audits/2026-04-23-t04-full-rerun-deep-audit-handoff.md`。
- **已验证**：
  - 文档完整性盘点（§1）。
  - 测试套件运行：`27 passed / 18 skipped / 2 failed`。
  - 全量回归输出对比：`outputs/_work/t04_anchor2_full_rerun/anchor2_full_*_20260423/{summary.json, step4_review_summary.json, step7_consistency_report.json, divmerge_virtual_anchor_surface_summary.csv, step7_rejected_index.csv}`。
  - 跨模块依赖 grep（runtime T02 / T03 引用 = 0）。
  - 文件体量盘点（§4.2）与 `code-size-audit.md` 对比。
- **待确认**：
  - 用户主张的"目视通过"是否包含 Step7 final_state（5 → 1 reject 的演化是否在用户认知内）。
  - `test_aggregated_rcsd_unit_upgrades_multiple_partial_local_units` 是测试错还是实现错。
  - `857993 multi_component_result` 是数据特殊性还是组装算法缺陷。
  - `STEP4_OK` 是否应改为可达 vs 直接退化为 `REVIEW/FAIL` 二态。
- **未审计**：
  - Step5-7 内部细颗粒（如 `terminal_cut_constraints` 边界化是否覆盖所有 sibling-axis 共轴 case）。
  - `internal_full_input_runner` 在内网 full-input 数据上的真实吞吐与失败率。
  - `qgis-auto-visual-check` Skill 与当前 PNG 的兼容性。

---

## 11. 关键文件指针（GPT 下钻用）

- 契约：`modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`（37 KB，§3.4 / §3.5-§3.7 / §3.8-§3.9）
- 主内核：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py`（87,975 bytes，L1242-L1245 的 degraded_scope 触发；L1700-L1837 的 STEP4_OK 决策）
- T02 硬拷贝：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_stage4_execution_contract.py` ↔ `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_execution_contract.py`
- 死代码：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel_reference.py`
- Step6 组装：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py:_connect_hard_seed_components`（与 857993 reject 直接相关）
- Step7 决策：`src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py:build_step7_case_artifact`（L237-L308 reject_reasons / final_state）
- 失败测试：`tests/modules/t04_divmerge_virtual_polygon/test_positive_rcsd_selection.py:101`
- 空 stub：`tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py`
- 当前 best 回归：`outputs/_work/t04_anchor2_full_rerun/anchor2_full_rcsd_support_graph_fix_20260423/`
- 治理文档：`docs/repository-metadata/{code-size-audit.md, entrypoint-registry.md, code-boundaries-and-entrypoints.md, path-conventions.md (缺失)}`
- 既有审计：`docs/doc-governance/audits/{2026-04-22-t04-divmerge-virtual-polygon-deep-audit.md, 2026-04-23-t04-step4-candidate-space-audit.md}`

---

> 握手结束：请 GPT 决策（A）启动 SpecKit 任务书；或（B）针对单点（如 857993 / test 失败）走 default-imp 小修；或（C）确认本轮 T04 收尾、暂停迭代。
