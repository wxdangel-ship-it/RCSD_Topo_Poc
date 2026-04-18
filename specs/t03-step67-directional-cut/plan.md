# Implementation Plan: T03 Step67 Directional Cut

**Branch**: `codex/t03-step67-directional-cut` | **Date**: 2026-04-18 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t03-step67-directional-cut/spec.md)  
**Input**: Feature specification from `/specs/t03-step67-directional-cut/spec.md`

## Summary

本轮先修 Step67 当前最直接的业务偏差：`20m` 仍停留在校验窗口，没有进入 Step6 构面主链。  
实现策略是让 Step6 从 `allowed_space` 出发，基于 selected-road branches 生成 directional cut geometry，对候选空间先做路向裁剪，再执行 foreign / must-cover / required RC 校验与有限 cleanup。

## Technical Context

**Language/Version**: Python 3.x  
**Primary Dependencies**: geopandas, shapely, pytest  
**Storage**: File-based GIS outputs (`GPKG`, `JSON`, `PNG`, `MD`)  
**Testing**: pytest, focused synthetic cases, focused real-case validation (`584141`, `520394575`)  
**Target Platform**: WSL on Windows, external data root `/mnt/e/TestData/POC_Data`  
**Project Type**: GIS topology processing module / internal batch runner  
**Performance Goals**: 保持当前 Step67 可用，不把性能优化作为本轮主目标  
**Constraints**:
- T03 模块正式文档仍停在 Step45，本轮实现必须通过 spec-kit 工件显式声明 clarified requirement
- 不新增 CLI / 执行入口
- 不回写 T03 Step3 / Step45 既有业务定义
- 本轮先解决 generic `20m` directional cut，不宣称已完成 `A` 趋势匹配和 `single_sided_t_mouth` 横向 `5m` 特化

## Constitution Check

*GATE: Must pass before implementation. Re-check after design.*

- 已读仓库治理入口：`AGENTS.md`、`docs/doc-governance/README.md`、`SPEC.md`
- 已复审模块边界：`modules/t03_virtual_junction_anchor/*`、`modules/t02_junction_anchor/*`
- 当前变更属于中等以上结构修订，已切分支 `codex/t03-step67-directional-cut`
- 本轮不新增执行入口，符合 registry 约束
- 本轮只修改 T03 Step67 代码与 spec-kit 工件，不触碰 T02 正文实现

## Project Structure

### Documentation (this feature)

```text
specs/t03-step67-directional-cut/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/
├── step67_geometry.py          # Step6 directional cut 主改动面
├── step67_models.py            # 若需要补几何/审计对象
├── step67_writer.py            # 如需落盘新增 Step6 审计/几何
└── step67_render.py            # 本轮仅在必要时调整视图

tests/modules/t03_virtual_junction_anchor/
├── test_step67_geometry.py
├── test_step67_batch_runner_summary.py
└── test_step67_case_520394575_regression.py
```

**Structure Decision**: 正确性主改动集中在 `step67_geometry.py`。只要新规则不需要新增几何落盘层，就不扩大 `writer/render` 改动面。

## Phase Plan

### Phase 0 - Spec Clarification

- 把 `20m` 是 Step6 构造规则写入 spec-kit 工件
- 明确 thread-level clarified requirement 与旧正式文档的差异

### Phase 1 - Directional Cut Solver

- 从 target-group anchor 出发，拆 selected roads 的 outward branches
- 计算每条 branch 在 `allowed_space` 中的 contiguous available length
- 生成 branch-specific cut geometry：
  - `available >= 20m` -> 按 `20m` cut
  - `available < 20m` -> preserve candidate boundary
- 用 directional cut geometry 直接裁 `allowed_space`

### Phase 2 - Step6 Validation & Audit

- 保留 existing hard checks：legal / foreign / must-cover / conditional required RC
- 将 `selected_road_core_cover_ratio` 对齐到 directional-core geometry
- 在 `step6_audit.json` 写出 branch-cut 审计

### Phase 3 - Regression

- 合成 case：锁住 center-junction directional cut 和 `support_only` accepted
- single-sided helper：确认 `20m` 规则已生效
- real case：至少复查 `584141` 与 `520394575`

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 保留 Step7 二态与视觉层解耦 | 当前线程已确认新业务口径 | 回退到旧三态会继续误判 `support_only` |
| 在 Step67 里先落 generic `20m`，不同时宣称收口 `5m` 特化 | 先解决阻塞性的“20m 未进入构面”问题 | 一次性并入 `A` 趋势匹配 + `single_sided` 特化会放大改动面与定位成本 |
