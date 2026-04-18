# Implementation Plan: T03 Step67 Single-Sided Horizontal Cut Fix

**Branch**: `codex/t03-step67-directional-cut` | **Date**: 2026-04-18 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t03-step67-single-sided-horizontal-cut/spec.md)

## Summary

在 `single_sided_t_mouth` 上，把横向 pair roads 从 generic `20m directional cut` 中分流出来，按“最外侧语义路口 + `5m`”求横向截断；竖向仍维持当前 `20m` 规则。

## Technical Context

- Primary code: `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step67_geometry.py`
- Regression focus:
  - `706389`
  - `707476`
  - `520394575`
  - existing Step67 geometry tests
- Constraints:
  - 不新增 CLI
  - 不把求解常量写回长期契约
  - 尽量局部改动，避免影响非 single-sided case

## Phase Plan

### Phase 0 - Audit

- 复核 `706389` 横向 pair road 的当前 cut 行为
- 确认最小实现位置与回归面

### Phase 1 - Implementation

- 在 `step67_geometry.py` 中新增 `single_sided_t_mouth` 横向特化 cut 规则
- 补充分支审计字段

### Phase 2 - Verification

- 更新/新增 focused regression
- 运行 targeted pytest
- 视结果运行 formal 58 case batch

### Phase 3 - Thread Sync

- 同步线程证据与 GPT 交接材料
