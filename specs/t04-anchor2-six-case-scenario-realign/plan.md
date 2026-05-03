# Implementation Plan: T04 Anchor_2 六个 Case 场景与构面对齐重做

**Branch**: `codex/t04-anchor2-six-case-scenario-realign` | **Date**: 2026-05-03 | **Spec**: [spec.md](./spec.md)
**Status**: Implemented (D-2 only) — Phase 2-4 deferred per B-3 close-out 2026-05-04

## 1. Summary

修复 T04 在 `706347 / 724081 / 765050 / 768675 / 785731 / 795682` 6 个 Anchor_2 case 上的 `surface_scenario_type` 与 `final_state`。

实施严格遵守 spec.md §1.4 的"负向掩膜先行 / barrier-aware grow"架构原则；任何 implement 任务之前先做 **Phase 0.5 根因探针**，确认或反驳 §1.3 F4"先生成后切割"反模式假设。探针确认后按 Path A 实施（共享 Step6 架构修复 + 4 个独立 user story）；探针反驳则按 Path B 拆分（具体由探针完成时锁定）。

每个 phase 收尾以 PNG + 字段对比表 + baseline test 输出供用户目视；用户回 `OK` 才推进下一 phase。同时把 `724081 / 785731 / 795682` 的场景锁补登到 `architecture/10-quality-requirements.md`，措辞按 spec.md §A 附录 final draft 一字写入。

**本轮放弃 23-case PNG fingerprint baseline 整体守门**（用户 2026-05-03 决定）；只守 23-case + 30-case baseline test 的 `accepted / rejected` 列表，以及 6 个 case 的目视 PNG。其它 case 的 PNG / 字段差异留待后续重新审计评估。

## 2. Technical Context

- **Language/Version**：Python 3.11
- **Primary Dependencies**：`shapely`、`geopandas`、`numpy`、`rasterio`（Step6 raster assembly）
- **Storage**：GPKG / GeoJSON / JSON / CSV / PNG（按 `INTERFACE_CONTRACT.md §4`）
- **Testing**：`pytest`，重点测试 `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` 中 `test_anchor2_30case_surface_scenario_baseline_gate`、`test_anchor2_full_20260426_baseline_gate`
- **Target Platform**：本地 / WSL 离线计算环境
- **Project Type**：library + module-internal CLI wrapper（无 repo 官方 CLI 新增）
- **Performance Goals**：39-case batch `threshold_seconds_total = 240.0`、`threshold_avg_completed_case_seconds = 6.5`，保持 `within_threshold`
- **Constraints**：单文件 `100KB` 硬阈值；CRS = `EPSG:3857`；不得新增 repo 官方 CLI；不得改 `INTERFACE_CONTRACT.md` 已有枚举语义
- **Scale/Scope**：39 个 Anchor_2 case；本 spec 直接关注 6 个，但所有修复必须通过 23-case + 30-case + 39-case 全量回归

## 3. Constitution Check

按 `AGENTS.md §1`、§3、§5、§6 自检：

| 触发器 | 当前评估 |
|---|---|
| §1.1 源事实冲突 | 本 spec 显式 supersede `t04-anchor2-swsd-window-repair` 对 `785731 / 795682` 的场景结论；同轮把新结论补到 `architecture/10-quality-requirements.md`，不留漂移。 |
| §1.2 触碰对外接口 | 不触 `INTERFACE_CONTRACT.md` 现有枚举语义；只在 `architecture/10-quality-requirements.md` 新增 case 锁。属于"不变更对外接口"。 |
| §1.3 新增正式入口 | 不新增 `Makefile` 目标、`scripts/`、模块 `__main__.py`、CLI 子命令。 |
| §1.4 文件体量 | 写入前必须按 §3 自检。预期主要改动文件：`_event_interpretation_core.py`（55KB）、`step4_road_surface_fork_binding_promotions.py`（34KB）、`polygon_assembly.py`（81KB，**接近阈值，须重点警戒**）、`support_domain_builder.py`（42KB）、`test_step7_final_publish.py`（83KB，**接近阈值**）。**`polygon_assembly.py` 与 `test_step7_final_publish.py` 在 implement 阶段的任何写入都必须先做体量自检，并优先把新增逻辑落到既有的拆分文件（`polygon_assembly_*.py`）或新拆出的子模块**（Path A 必须新建 `polygon_assembly_barrier_aware_grow.py` + `polygon_assembly_inter_unit_bridge.py`）。 |
| §1.5 字段语义反推 | 6 个 case 都基于人工目视审计结论，且所有结论已写入或将写入 `10-quality-requirements.md`，符合"先固化字段语义再修改强规则"。 |
| §3 体量硬约束 | 同 §1.4。任何首次跨 100KB 的改动必须停机回报并提供拆分计划。 |
| §5 GIS / 拓扑 | CRS、拓扑一致性、几何语义可解释性、审计可追溯、性能可验证全部覆盖在 §6 测试策略与 §7 QA 视角。 |
| §6 SpecKit | 本任务正在 SpecKit 流程内。implement 阶段默认遵循 `default-imp/SKILL.md`。 |

**结论**：本 plan 在 implement 阶段开工前不存在硬停机触发器；`polygon_assembly.py` 与 `test_step7_final_publish.py` 的体量风险在 implement 阶段必须重点把守。

## 4. Architecture View

### 4.1 修复点与既有代码层映射

下表的 F4 / F5 路径**取决于 Phase 0.5 探针结论**；此处给出 Path A（探针确认 F4 反模式）与 Path B（探针反驳）的备选映射，选定后由探针报告锁定。

| 修复路径 | 主修改文件（Path A） | 主修改文件（Path B） | 影响层 |
|---|---|---|---|
| F1 弱 `road_surface_fork` 不得升主证据；`role_mapping_partial_relaxed_aggregated` 不得升 `rcsd_semantic_junction` | `step4_road_surface_fork_binding_promotions.py`（34KB） + `_event_interpretation_core.py`（55KB）次修 | 同 Path A | Step4 pair-local promotion + RCSD aggregation |
| F2 case 顶层 RCSD 召回聚合不再压平 | `_event_interpretation_core.py`（55KB） + `_runtime_step4_kernel_base.py`（65KB）次修 | 同 Path A | Step4 case-level aggregation |
| F3 RCSD candidate 物化漏召 | `_runtime_step4_geometry_core.py`（64KB）或 `_event_interpretation_unit_preparation.py`（41KB） | 同 Path A | Step4 candidate materialization |
| F4 Step6 装配收敛（共性 + inter-unit bridge） | **新建** `polygon_assembly_barrier_aware_grow.py` + `polygon_assembly_inter_unit_bridge.py`，由 `polygon_assembly.py` 做最小 dispatch | 仅新建 `polygon_assembly_inter_unit_bridge.py`；`polygon_assembly.py` / `support_domain_builder.py`（42KB）做局部修复 | Step5 allowed_growth + Step6 装配 |
| F5 `barrier_separated_case_surface_ok` 审计标记修正 | `polygon_assembly_models.py`（12KB） | 同 Path A | Step6 audit field |
| 文档锁 | `architecture/10-quality-requirements.md`（按 spec §A 附录措辞一字写入） | 同 Path A | 模块源事实 |

**拆分策略**：F4 是体量最高风险路径。`polygon_assembly.py` 当前 81KB，距 100KB 仅约 19KB。

- **Path A（barrier-aware 重写）**：本轮在 `polygon_assembly.py` 中**仅做 dispatch 改动（< 2KB 新增）**；核心 barrier-aware grow 逻辑落到**新建** `polygon_assembly_barrier_aware_grow.py`；inter-unit bridge 落到**新建** `polygon_assembly_inter_unit_bridge.py`。原"先生成后切割"代码路径作为 legacy fallback 暂留，但默认不调用，由 §1.4 架构开关控制；Phase 6 收尾决定是否同轮删除。
- **Path B（barrier-aware 已存在但有局部 bug）**：仅按探针定位的具体 bug 修补；`polygon_assembly.py` 任何写入都先做 §3 体量自检，必要时把局部修复也下沉到新建子模块。

`test_step7_final_publish.py`（83KB）原则上**不向其追加业务代码**，本 spec 的所有新 case 断言落到新建 `tests/.../test_six_case_scenario_realign.py`。仅在更新 30-case / 23-case baseline gate 测试 `accepted / rejected` 列表断言时对该文件做最小调整。

### 4.2 Step1-7 链路语义不变

本轮不改 Step1-7 总体链路语义。所有改动遵循契约 `architecture/04-solution-strategy.md` 的现有分层：

- Step4 仍负责事件解释、主证据判定、RCSD 对齐与 case-level 唯一性消歧；只修内部 promotion guard 与聚合策略。
- Step5 仍只发布 `must_cover / allowed_growth / forbidden / terminal_cut` 约束；只在场景识别正确后由约束自动重组，不改约束生成口径。
- Step6 仍负责单一连通面装配；本轮新增 inter-unit section bridge 是 §3.5 末段的 contract-aligned 实施，不是新算法。
- Step7 二值最终态不变。

### 4.3 字段与契约影响

| 字段 | 是否新增 / 改动 | 影响范围 |
|---|---|---|
| `surface_scenario_type` | 不增不改枚举；6 个 case 的实际取值因实现修复发生变化 | Step4/5/Step7 audit |
| `rcsd_alignment_type` | 不增不改枚举；6 个 case 的实际取值因实现修复发生变化 | Step4 audit |
| `barrier_separated_case_surface_ok` | 不增不改字段；语义保持 `INTERFACE_CONTRACT.md` 第 336 行原义，本轮修正实现侧的滥用 | Step6 audit |
| `unit_surface_merge_performed` | 不增不改字段；本轮在 inter-unit bridge 真正执行时置 `true` | Step6 audit |
| `architecture/10-quality-requirements.md` 新增 case 锁 | 文档新增 3 行（`724081 / 785731 / 795682`）；与现有 `765050 / 768675 / 706347` 同节 | 模块源事实 |

## 5. Development View

### 5.1 实施顺序与依赖

```
Phase 0: SpecKit 闭环 (spec / plan / tasks 三阶段全部完成；用户回 OK)
   │
Phase 0.5: 根因探针 (Probe)                                 ◀── 必须最先做，无任何代码改动
   │     ├── 代码路径核查 (polygon_assembly* / support_domain_builder)
   │     ├── 几何中间产物核查 (706347 / 765050 / 785731 / 795682 / 724081)
   │     ├── inter-unit bridge dispatch 核查 (765050)
   │     └── 输出 phase_0_5_root_cause 报告 + Path A/B 锁定
   │           └── 用户回 OK 或 不通过 + 原因
   │
   ▼ (Path A：F4 反模式确认)               ▼ (Path B：F4 反驳)
Phase 1A: US A1 Step6 barrier-aware 架构修复  Phase 1B: 按探针逐 case 单点修复
   │     ├── 新建 polygon_assembly_barrier_aware_grow.py
   │     ├── 新建 polygon_assembly_inter_unit_bridge.py
   │     ├── polygon_assembly.py 仅最小 dispatch (体量自检)
   │     ├── 同时实施 US A5 (barrier_separated_* 字段语义)
   │     ├── 出 706347 / 765050 final_review.png (Step4 仍未修，但装配单连通)
   │     └── 用户目视
   │
Phase 2: US A2 / B2 — 724081 / 785731 case 级 RCSD 聚合       ◀── P1
   │     ├── 改 _event_interpretation_core.py 聚合策略
   │     ├── 验证 Step4 顶层字段；Step5/6 由 Phase 1 已支撑
   │     ├── 出 724081 / 785731 final_review.png
   │     └── 用户目视
   │
Phase 3: US A3 / B3 — 795682 candidate 物化                 ◀── P2
   │     ├── 改 _runtime_step4_geometry_core.py 或 _event_interpretation_unit_preparation.py
   │     ├── 出 795682 final_review.png
   │     └── 用户目视
   │
Phase 4: US A4 / B4 — 768675 弱 promotion guard             ◀── P3
   │     ├── 改 step4_road_surface_fork_binding_promotions.py
   │     ├── 验证 505078921 不被误伤 (FR-014)
   │     ├── 出 768675 final_review.png
   │     └── 用户目视
   │
Phase 5: 文档锁 + baseline test 更新 + 39-case 全量回归
         ├── architecture/10-quality-requirements.md 按 spec §A 附录写入 3 case 锁
         ├── 23-case + 30-case baseline test 业务断言更新（PNG fingerprint 整体 baseline 不再守）
         ├── 39-case 全量回归 + 性能阈值复核
         └── final 用户目视：6 张 PNG + 综合 summary + audit.md close-out
```

依赖关系：

- Phase 0.5 必须在所有代码 phase 之前；Phase 0.5 是只读探针，不写代码、不改契约。
- Phase 1（A 或 B）必须先做：它给后续 4 个 phase 提供"装配能产生单连通面"的基础；Step4 修复完成后没有 Step6 收敛能力，case 仍会 rejected。
- Phase 2 / 3 / 4 之间相互独立，可并行；但本 plan 串行以保证用户 PNG 目视粒度。
- Phase 5 必须最后做（baseline test 断言依赖前 4 个 phase 全部生效）。

### 5.2 体量自检流程（每个 phase 内强制）

每个 phase 写入文件前：

1. `Get-ChildItem <file>` 拿到当前字节数；
2. 估算本次新增字节数（行数 × 平均行长）；
3. 如新增后总量 ≥ 100KB，停机回报，提交拆分计划，等用户授权。

`polygon_assembly.py` 与 `test_step7_final_publish.py` 是已知接近阈值文件，本轮**默认假定不向其追加业务代码**：

- inter-unit bridge 实施落到新建 `polygon_assembly_inter_unit_bridge.py`；
- 测试断言落到新建 `tests/modules/t04_divmerge_virtual_polygon/test_six_case_scenario_realign.py`，不混进既有 `test_step7_final_publish.py`。

### 5.3 不动的边界

- `INTERFACE_CONTRACT.md` 不动；本 plan 仅消费契约，不修改契约。
- `entrypoint-registry.md` 不动。
- `t04_run_internal_full_input_*.sh` 包装脚本不动；如需新参数走可选 env var，与现有脚本签名兼容。
- T03 / T02 模块代码不动。

## 6. Testing View

### 6.1 测试金字塔

| 层级 | 文件 | 覆盖 |
|---|---|---|
| Unit / contract | `tests/modules/t04_divmerge_virtual_polygon/test_six_case_scenario_realign.py`（新建） | 6 个 case 的 `surface_scenario_type / rcsd_alignment_type / final_state / final_case_polygon_component_count / unit_surface_merge_performed / barrier_separated_case_surface_ok` 字段断言 |
| Integration | `test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate` | 30-case 全量 26 accepted / 4 rejected |
| Integration | `test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate` | 23-case 全量 20 accepted / 3 rejected |
| Performance | summary.json `performance_audit_version` 与阈值字段 | 39-case batch `within_threshold` |
| Visual（人工目视） | 6 张 `final_review.png` | 用户回 `OK / 不通过`，不再做 raw hash 比对 |

**移除项**：原"23-case visual fingerprint test"在本轮 baseline 整体放弃后**不再作为本 spec 的硬 gate**。如该测试当前存在并失败，按 plan §6.4 处理（要么跳过、要么按用户后续重新审计的统一刷新策略）。

### 6.2 每个 user story 的独立测试

- **US A1 / B1+B2（Step6 装配）**：706347 / 765050 / Step4 修复后的 724081 / 785731 / 795682 全部 `final_case_polygon_component_count = 1` + `barrier_separated_case_surface_ok = false`；30-case baseline test 中 706347 / 724081 / 765050 = accepted。
- **US A2 (724081 / 785731)**：单 case 测试 Step4 顶层 `surface_scenario_type / rcsd_alignment_type` 与 §1.2 用户目视一致。
- **US A3 (795682)**：单 case 测试 candidate pool 中至少 1 个 `rcsdroad_only_alignment` 候选 + 顶层 `rcsd_alignment_type = rcsdroad_only_alignment` + `final_state = accepted`。
- **US A4 (768675)**：单 case 测试 `has_main_evidence = false` + `surface_scenario_type = no_main_evidence_with_rcsd_junction` + `final_state = accepted`；23-case baseline test 业务断言通过；`505078921 / node_510222629__pair_02 evidence_source = road_surface_fork`（FR-014）保持原状。
- **US A5（barrier_separated_*）**：6 个 case 的 `barrier_separated_case_surface_ok` 修复后全部 `false`；该字段置 `true` 必须配 `bridge_negative_mask_crossing_detected = true` + 至少一个 channel `overlap_area_m2 > tolerance`。

### 6.3 回归保护

- 30-case `accepted` 列表（`INTERFACE_CONTRACT.md §6` 第 614-636 行）一字不变。
- 23-case `accepted / rejected` 列表（同上 §6）一字不变。
- `857993 / 760598 / 760936 / 607602562 = rejected` 不变。
- `699870` 必须保持 `accepted`（RCSD-anchored reverse 关键回归）。
- `505078921` 的 `node_510222629__pair_02 evidence_source = road_surface_fork`（contract 第 267 行硬锁）不被 US A4 / B4 promotion guard 抢占（FR-014）。
- **本轮放弃**：23-case PNG fingerprint baseline 整体；其它 23-case / 30-case / 39-case case 在本轮 6 case 修复中可能产生的 PNG / 字段差异不再守，留待用户后续重新审计统一处理。

### 6.4 测试数据约束

- 输入根：`E:\TestData\POC_Data\T02\Anchor_2`（Windows）/ `/mnt/e/TestData/POC_Data/T02/Anchor_2`（WSL）
- 跨盘符路径换算遵循 `docs/repository-metadata/path-conventions.md`（如存在）或 §7 沿用历史约定
- 不得修改测试数据本身

## 7. QA View

### 7.1 验收材料

每个 phase 收尾必须交付：

1. 该 phase 涉及 case 的 `final_review.png`（高分辨率，用户可目视的工件）。
2. 该 phase 涉及 case 的 `cases/<case>/step7_status.json` + `step6_status.json` + `step5_status.json` + `step4_event_interpretation.json` 关键字段摘要。
3. 该 phase 的字段对比表：实现修复前 vs 修复后 vs 用户目视目标。
4. 该 phase 的 baseline test 通过证据（pytest 输出）。
5. 该 phase 体量自检证据（写入前后字节数）。

最终交付（Phase 6 完成后）：

- 6 张 `final_review.png`（706347 / 724081 / 765050 / 768675 / 785731 / 795682）的目视审计材料合并包。
- 23-case + 30-case + 39-case batch 完整 summary 与 nodes 写回审计。
- `nodes_anchor_update_audit.csv/json` 与 `divmerge_virtual_anchor_surface_summary.json` 一致性核对。
- `step7_consistency_report.json` 通过。
- `architecture/10-quality-requirements.md` diff（新增 3 case 锁）。

### 7.2 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Phase 0.5 探针报告与用户目视不一致 | Path 选错，整轮返工 | 探针报告必须由用户回 `OK` 才推进；不一致须先重做探针 |
| `polygon_assembly.py` 跨过 100KB | §3 硬停机 | barrier-aware grow + inter-unit bridge 全部落新文件；本轮不向其追加业务代码 |
| `test_step7_final_publish.py` 跨过 100KB | §3 硬停机 | 新断言落到新建 `test_six_case_scenario_realign.py`；只对该既有文件做最小 baseline assertion 更新 |
| US A4 / B4 副作用打破 23-case 其它 case 业务 final_state | baseline 回归 | 必跑全 23-case + 30-case；`accepted / rejected` 列表任何变化都需用户目视复核；其它 PNG fingerprint 差异不再守 |
| Path A barrier-aware 重写改变某非 6-case case 的 final_state | baseline 回归 | 全 39-case 跑批；列表性 final_state 守住，PNG fingerprint 不守 |
| US A2 / A3 修复后 Step5/Step6 仍切碎 | accepted 仍不达成 | 在 Path A 下应被 Phase 1A 共享修复涵盖；如 Phase 2/3 完成后单 case 仍切碎，回到 Phase 0.5 重新探针 |
| 性能阈值越过 | QA 风险 | 每个 phase 收尾跑一次 39-case 性能审计；超阈值需在交付材料中说明 |
| 用户目视 PNG 不通过但字段全部对 | phase 卡住 | 不顺手推进；当前 phase 重新定位（可能是 review 渲染问题或截面边界几何问题）；必要时回到 Phase 0.5 |

### 7.3 用户最终目视确认协议

每个 phase 收尾，提供 PNG + 字段摘要给用户；用户回复 `OK` 或 `不通过 + 原因`：

- `OK`：进入下一个 phase。
- `不通过`：当前 phase 重新定位 root cause，更新 plan / tasks 后重做；不顺手推进下一个 phase。

最终 6 张 PNG 都通过用户目视后，本 SpecKit 任务才算 close。

## 8. Project Structure

### 8.1 文档结构（this feature）

```text
specs/t04-anchor2-six-case-scenario-realign/
├── spec.md              # 已生成（specify 阶段）
├── plan.md              # 当前文档
├── tasks.md             # 由 /speckit.tasks 后续生成
└── audit.md             # 可选：每个 phase 的字段对比与 PNG 引用，由 implement 阶段生成
```

### 8.2 Source Code（修改 / 新增预期，Path A 与 Path B 取并集）

```text
src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/
├── _event_interpretation_core.py                              # 修改：F2 case-level RCSD 聚合
├── _event_interpretation_unit_preparation.py                  # 可能修改：F3 candidate 物化
├── _runtime_step4_geometry_core.py                            # 可能修改：F3 candidate 物化
├── step4_road_surface_fork_binding.py                         # 可能修改：F1 facade dispatch
├── step4_road_surface_fork_binding_promotions.py              # 修改：F1 弱 promotion guard
├── polygon_assembly.py                                        # 仅最小 dispatch 改动（81KB 警戒）
├── polygon_assembly_barrier_aware_grow.py                     # **Path A 新建**：barrier-aware grow 主路径
├── polygon_assembly_inter_unit_bridge.py                      # **新建**：F4 inter-unit bridge 子模块
├── polygon_assembly_models.py                                 # 修改：F5 / US A5 barrier_separated_* 字段
└── support_domain_builder.py                                  # 可能修改（Path B 主路径或 Path A 次修）

modules/t04_divmerge_virtual_polygon/architecture/
└── 10-quality-requirements.md                                 # 修改：按 spec §A 附录写入 3 case 锁

tests/modules/t04_divmerge_virtual_polygon/
├── test_step7_final_publish.py                                # 仅修改 baseline assertion（83KB 警戒）
└── test_six_case_scenario_realign.py                          # **新建**：本 spec 6 case 字段断言
```

**Structure Decision**：维持现有 T04 模块分层；本 spec 在 Path A 下引入 `polygon_assembly_barrier_aware_grow.py` 与 `polygon_assembly_inter_unit_bridge.py` 两个新子模块，避免对 81KB 的 `polygon_assembly.py` 追加业务逻辑；Path B 下至少新建 `polygon_assembly_inter_unit_bridge.py`，其它修复在 `support_domain_builder.py` 局部完成。测试新建独立 `test_six_case_scenario_realign.py`。

## 9. Complexity Tracking

| Violation / Risk | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Phase 0.5 探针前置 | §1.4 架构原则需先确认 / 反驳 F4 反模式假设；706347 / 765050 / 785731 / 795682 / 724081 切碎可能是同一架构问题 | "直接按 case 单点修"会反复返工：每修一个 case 仍然多 component，根因不在 case 自身 |
| 新建 `polygon_assembly_barrier_aware_grow.py` (Path A) | `polygon_assembly.py` 已 81KB；架构重写不能塞回去 | 直接重写 polygon_assembly.py 必然跨 100KB |
| 新建 `polygon_assembly_inter_unit_bridge.py` | 同上；inter-unit bridge 是独立职责 | 复用 polygon_assembly.py 同函数会让两条逻辑耦合 |
| 新建 `test_six_case_scenario_realign.py` 而非 append 到 `test_step7_final_publish.py` | 既有测试文件 83KB，append 风险高 | 即便不超阈值，混入会让回归责任不清 |
| 串行 phase 而非并行 | 用户 PNG 目视 gate 要求每 phase 独立可验 | 并行：多个 phase 同时改装配路径，无法独立目视 |
| 整体放弃 23-case PNG fingerprint baseline | 用户 2026-05-03 决定：本轮只守 6 case 与 baseline 业务断言 | 仅刷新一个 case 不能覆盖本轮多 phase 改动产生的几何 drift；逐 phase 单独刷新 fingerprint 工作量过大 |
