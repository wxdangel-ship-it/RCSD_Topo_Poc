# Implementation Plan: T04 Step3/Step4 Repair Formalization

**Branch**: `codex/t04-step14-speckit-refactor` | **Date**: 2026-04-21 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t04-step34-repair-formalization/spec.md)

## Summary

本轮按输入需求完成“spec 固化 -> 正式文档回写 -> Step4 修复 -> case 回归”。总体策略是：

- Step3 不先重写 T02 全量内核，而是在 T04 层补齐 `representative-node-anchored unit-level executable skeleton`
- Step4 不再把 Step3 粗骨架直接当成 throat 几何，而是引入 `unit envelope + ordered pair (L, R) + unit-local event branches / boundary branches / preferred axis`
- 对 `continuous complex/merge`，明确采用“unit population 不扩，但传播 `(L, R, middle-region)`，并按四条规则筛 sibling arm”的正式口径
- 先更新 `specs/t04-step34-repair-formalization/`，再回写 `INTERFACE_CONTRACT.md` 与 `architecture/*`，随后改代码并回归 `17943587`

## Technical Context

**Language/Version**: Python 3.10, Markdown  
**Primary Dependencies**: `shapely`, `fiona`, repo `.venv`  
**Storage**: `specs/` + thread handoff  
**Testing**: `pytest tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py -q -s`、`pytest tests/test_smoke_t02_stage4_divmerge_virtual_polygon.py -q -s`、`pytest tests/test_cli_t02.py -q -s`、selected real-case batch  
**Target Platform**: WSL on Windows  
**Project Type**: Brownfield GIS topology / event-interpretation repair formalization  

## Constitution Check

- 已遵守 `AGENTS.md -> docs/doc-governance/README.md -> SPEC.md -> PROJECT_BRIEF.md -> module docs` 主阅读链。
- 用户已明确要求以输入 `REQUIREMENT.md` 为本轮对齐口径，允许回写 T04 模块 source-of-truth 与实现。
- 已识别“source-of-truth 收窄了 continuous merge complex branch 语义”的冲突点，本轮按 requirement 回写并修复。
- 未进入 `Step5-7`，未新增 repo 官方 CLI。

## Design Decisions

1. **Step3 拆成两层语义**
   - `case coordination skeleton`
   - `unit-level executable skeleton`

2. **complex Step4 只认 unit-level executable skeleton**
   - `case coordination skeleton` 只用于 population、chain relation、overview、cross-unit orchestration
   - 但 `unit-level executable skeleton` 在 continuous complex/merge 下允许按 branch continuation context 穿过 same-case sibling internal node，不等于“只看当前 node 直连 road”

3. **pair propagation 不扩 unit population**
   - `unit_population_node_ids` 仍只属于当前 representative node
   - same-case sibling internal node 只允许进入当前 unit 的 `(L, R, middle-region)` 传播与 boundary 语义，不得反向扩成 event-unit population

4. **Step4 引入 unit envelope**
   - `unit_population_node_ids`
   - `context_augmented_node_ids`
   - `event_branch_ids`
   - `boundary_branch_ids`
   - `preferred_axis_branch_id`

5. **Step4 geometry/point 语义拆层**
   - `selected_component_union_geometry`
   - `localized_evidence_core_geometry`
   - `coarse_anchor_zone_geometry`
   - `fact_reference_point`
   - `review_materialized_point`

6. **complex/multi 的 gate 输入必须 unit-local**
   - merge 单元的 `boundary_branch_ids` 应由当前 unit 的 entering branches 组成
   - diverge 单元的 `boundary_branch_ids` 应由当前 unit 的 exiting branches 组成
   - `preferred_axis_branch_id` 应来自唯一 opposite-direction trunk，而不是 `kind_2=128 -> 16` 的默认降级

7. **sibling arm 选择按 pair 规则而不是贪心方位角**
   - 先看 `external associated road` 一致性
   - 再看 `L' / R'` 之间不得夹入其他 road
   - 再看左右顺序不变
   - 最后才允许用最小转角做 tie-breaker

8. **Step4 编排层采用 facade + 子模块解耦**
   - `event_interpretation.py` 保留为唯一公开编排面与 `build_case_result` 出口
   - `event_interpretation_shared.py` 承担私有 dataclass 与共用 geometry/scope helper
   - `event_interpretation_branch_variants.py` 承担 direct-adjacency / complex continuation / executable branch variants
   - `event_interpretation_selection.py` 承担 candidate merge、priority、case-level reselection、ownership guard
   - 本轮属于内部架构拆分，不改变 Step4 对外契约、审计字段和 runner 入口

## Planned Formal Backwrite Targets

在冲突点确认后，正式文档回写目标为：

- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`
- `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`
- `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`
- 新增 `modules/t04_divmerge_virtual_polygon/architecture/06-step34-repair-design.md`

## Phase Plan

### Phase 1 - Specify

- 冻结 Step3/Step4 修复问题定义
- 冻结当前 source-of-truth 冲突点
- 冻结 continuous merge complex 的 branch continuation 语义边界

### Phase 2 - Plan

- 设计 Step3 新接口层次
- 设计 complex unit-local arm augmentation / branch continuation
- 设计 Step4 unit envelope
- 设计 ownership / throat / reverse tip / review materialization 的新边界

### Phase 3 - Tasks

- 拆出契约回写任务
- 拆出实现任务
- 拆出回归任务

### Phase 4 - Implement

- 回写正式文档
- 再改代码与回归

## Implementation Notes For Next Thread

- Step3 首要改动不是重写 case-level skeleton，而是补出 complex unit-local executable branch continuation。
- Step4 首要改动不是新增更多 fallback，而是让 `event_branch_ids / boundary_branch_ids / preferred_axis_branch_id` 建立在正确 ordered pair `(L, R)` 与 sibling propagation 上。
- `selected_component_ids` 后续应降级为 debug label，不再承担跨 unit 稳定身份。
- `event_interpretation.py` 已重新超过 `100KB` 阈值；修复与回归继续推进前，必须优先把 Step4 内部职责抽成 facade + 子模块，避免后续 pair/local-candidate 规则继续堆回单文件。
