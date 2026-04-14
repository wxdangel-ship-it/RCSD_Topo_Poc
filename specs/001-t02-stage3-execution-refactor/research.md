# Research: T02 Stage3 Execution-Layer Refactor

## 1. 当前问题不是 case 表现，而是执行层未完成重构

QA 结论已经明确：

- 结构性重构未完成
- 仍不符合冻结文档契约

依据材料：

- [qa_refactor_completion_audit.md](/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t02_stage3_rebuild/20260413_stage3_delivery/round_15/qa_refactor_completion_audit.md)
- [pm_contract_gap_matrix.md](/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t02_stage3_rebuild/20260413_stage3_delivery/spec_kit_phase1/pm_contract_gap_matrix.md)
- [arch_target_architecture.md](/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t02_stage3_rebuild/20260413_stage3_delivery/spec_kit_phase1/arch_target_architecture.md)
- [qa_refactor_acceptance_gates.md](/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t02_stage3_rebuild/20260413_stage3_delivery/spec_kit_phase1/qa_refactor_acceptance_gates.md)

## 2. 已确认的结构根因

### 2.1 超大单体主流程仍承载 Step3~7

- [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py) 约 `984049 bytes`
- `run_t02_virtual_intersection_poc()` 从 [8645](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py:8645) 延伸到文件尾部

结论：

- 当前还不是按步骤分层执行
- 任何 case 修补都容易污染其它步骤

### 2.2 Step7 不是唯一终裁层

- `_effect_success_acceptance()` 定义在 [8002](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py:8002)
- 主流程在 [17473](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py:17473) 就调用它
- 但后续仍继续做 `soft_excluded_rc_corridor_trim`、`late_post_soft_overlap_trim`、`late_final_foreign_residue_trim`、`late_single_sided_partial_branch_strip_cleanup`、`late_single_sided_corridor_mask_cleanup`、`late_single_sided_tail_clip_cleanup`

结论：

- Step7 被提前执行
- Step5/6/7 仍混层

### 2.3 审计链仍主要靠字符串 reason 反推

- [stage3_review_contract.py:135](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_review_contract.py:135) 的 `derive_stage3_review_metadata()` 仍从 `acceptance_reason/status` 反推审计元数据

结论：

- 执行层没有先产出稳定的步骤级事实
- 审计层仍不是执行层原生产物

### 2.4 现有 late pass 已经承担主语义

当前仍存在：

- `late post-soft overlap trim`
- `late final foreign residue trim`
- `late single-sided partial-branch strip cleanup`
- `late single-sided corridor-mask cleanup`
- `late single-sided tail clip cleanup`

结论：

- 这些逻辑不能继续作为主修复手段
- 它们最多只能降级为 bounded optimizer

## 3. 研究结论

### 3.1 当前不应继续的事情

- 不应继续以 `724123 / 769081 / 851884` 为主线不断堆 patch
- 不应先盯 `V4/V5` 数量
- 不应把 packaging contract 达成误判为执行层重构达成

### 3.2 当前应该先做的事情

- 先定义 Step3~7 的显式结果对象
- 先把 Step7 从提前裁决改为唯一终裁
- 先把 Step4/5/6 的职责边界钉死
- 先让审计链从步骤结果原生生成

### 3.3 恢复 case 优化的前提

- 结构重构门槛通过
- 保护锚点不回退
- `61-case` 全量恢复时，必须拆开“正常准出正确性”和“目视分类正确性”
