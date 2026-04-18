# Implementation Plan: T03 Step45/67 Boundary-First And U-Turn Filter Fix

**Branch**: `codex/t03-step67-directional-cut` | **Date**: 2026-04-18 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t03-step67-boundary-first-local-required/spec.md)

## Summary

把 Step6 从“directional cut 只约束 seed”的实现改成真正的 `boundary-first`：
- 先确定 directional boundary
- 再只在这个边界内构造 must-cover / required RC cover
- final geometry 全程不得突破该边界

同时：
- 在 Step45 上游加入 `RCSD 调头口过滤`
- 过滤后重算 `degree2 connector / chain merge / required-support-excluded`
- 收紧 `single_sided_t_mouth` 横向特化，只在清洗后的局部 required semantic signal 足够明确时才触发 `semantic + 5m`
- 当 `boundary-first` 直接切掉 target semantic cover 时，在边界生成阶段做 target-connected regeneration，而不是直接失败

## Technical Context

- Primary code:
  - `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step67_geometry.py`
- Regression focus:
  - `706389`
  - `707476`
  - `709431`
  - `758888`
  - `851884`
  - existing Step67 geometry regressions
- Remaining known rejected-by-data cases:
  - `707913`
  - `954218`
  - `520394575`

## Phase Plan

### Phase 0 - Audit

- 固化当前问题根因：
  - directional cut 只作用于 `polygon_seed`
  - `required RC` 全量回补导致 final geometry regrow
  - `single_sided` 横向特化触发条件过宽

### Phase 1 - Implementation

- 在 Step45 引入 `RCSD 调头口过滤`
- 在调头口过滤后重算 `degree2 connector / chain merge / required-support-excluded`
- 把 directional boundary 提升为 final hard cap
- 引入 localized required RC geometry / node set
- 收紧 `single_sided_t_mouth` 横向特化触发条件
- 为 `single_sided_t_mouth` 增加 target-connected boundary regeneration

### Phase 2 - Verification

- 更新 `706389 / 707476 / 709431` 真实 case 回归
- 更新 `758888 / 851884 / 520394575` 真实 case 回归
- 运行 focused pytest
- 运行 formal 58 case regression

### Phase 3 - Thread Sync

- 更新线程 `SUMMARY.md`
- 更新线程 `TO_GPT.md`
- 更新线程 `RUN_EVIDENCE.md`
- 回写模块长期契约文档，正式吸收 `RCSD 调头口过滤 + boundary-first + local required RC`
