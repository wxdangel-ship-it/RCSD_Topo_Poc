# Implementation Plan: T03 Step67 Foreign Mask Normalization

**Branch**: `codex/t03-step67-directional-cut` | **Date**: 2026-04-18 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t03-step67-foreign-mask-normalization/spec.md)  
**Input**: Feature specification from `/specs/t03-step67-foreign-mask-normalization/spec.md`

## Summary

本轮修的是 `Step45 -> Step6` 的 foreign mask 边界，而不是再调 `20m` directional cut。  
策略是让 Step5 回到“RCSD 分组 / 审计”职责，不再构造 hard foreign polygon context；Step6 则只消费 road-like `1m` negative mask，并把该 mask 直接作为落盘和审计对象。  
本轮还依赖新的 Step45 upstream clarified requirement：经 `degree = 2` connector node 串接的 candidate `RCSDRoad` 会先按 road chain 合并，再参与 retained / excluded 分类。

## Technical Context

**Language/Version**: Python 3.x  
**Primary Dependencies**: geopandas, shapely, pytest  
**Storage**: File-based GIS outputs (`GPKG`, `JSON`, `PNG`, `MD`)  
**Testing**: pytest, focused synthetic Step45/Step67 tests, focused real-case validation (`698330`, `706389`, `707476`, `520394575`)  
**Target Platform**: WSL on Windows, external data root `/mnt/e/TestData/POC_Data`  
**Project Type**: GIS topology processing module / internal batch runner  
**Constraints**:
- T03 模块正式文档仍停在 Step45；本轮新口径必须通过 spec-kit 与线程交付文档显式声明
- 不新增 CLI / 执行入口
- 不回写 Step3 legal-space 与 Step45 association 业务定义
- 本轮只 normalise foreign mask，不把 `single_sided_t_mouth` 横向 `5m` 特化顺手做到位

## Constitution Check

*GATE: Must pass before implementation. Re-check after design.*

- 已读仓库治理入口：`AGENTS.md`、`docs/doc-governance/README.md`
- 本轮是中等以上结构修订，继续在分支 `codex/t03-step67-directional-cut` 上执行
- 不新增执行入口，不修改 T02 正文实现
- `specs/*` 仅作为本轮变更工件，不替代项目 / 模块级长期 source-of-truth

## Project Structure

### Documentation (this feature)

```text
specs/t03-step67-foreign-mask-normalization/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/
├── step45_foreign_filter.py    # 停掉 hard foreign polygon context
├── step67_geometry.py          # 只消费 road-like 1m mask
├── step45_writer.py            # 继续保留接口文件，但允许 context 图层为空
└── step67_writer.py            # 落盘 normalized foreign mask

tests/modules/t03_virtual_junction_anchor/
├── test_step45_foreign_filter.py
├── test_step67_case_698330_regression.py
├── test_step67_case_706389_707476_regression.py
└── test_step67_case_520394575_regression.py
```

**Structure Decision**: `step45_foreign_filter.py` 负责收缩上游 foreign context；`step67_geometry.py` 负责定义最终 hard mask 语义。writer / render 只跟随新的几何语义，不新增新的执行入口。

## Phase Plan

### Phase 0 - Requirement Freeze

- 把“Step5 不再生成 hard foreign polygon context、Step6 只保留 road-like 1m mask”写成新的 spec-kit 变更
- 显式说明 node 类 foreign 仍保留审计，但不进入本轮 hard subtract

### Phase 1 - Step45 Foreign Context Normalization

- 停掉 `foreign_swsd_context_geometry` / `foreign_rcsd_context_geometry` 的 polygon 构造
- 保留 `excluded_* / true_foreign_* / connector_*` 审计字段
- 将旧的 selected-surface protection patch 退出主口径，仅保留 audit-safe 占位字段

### Phase 2 - Step6 Mask Recomposition

- 只从 road-like carrier 构造 Step6 `foreign_mask_geometry`
- 统一把 `1m` 直接用在 mask 生成阶段，不再“先做 polygon context，再整体 `+1m`”
- 以上游 Step45 chain merge 后的 retained/excluded 结果解释 mask 来源，不再按 merge 前碎段单独解释 foreign
- 审计输出 `foreign_mask_mode / sources`

### Phase 3 - Regression

- synthetic Step45 foreign-filter tests：确认 Step5 不再输出 hard foreign polygon context
- real cases：
  - `698330`：selected surface 不再被 foreign 纵向裁短
  - `706389 / 707476`：从 node-based foreign rejection 恢复为 accepted
  - `520394575`：继续 rejected
- 最后重跑正式 58 case 批次，观察 V4 foreign failure 是否显著下降

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 暂时保留 `step45_foreign_swsd_context.gpkg` / `step45_foreign_rcsd_context.gpkg` 空文件位 | 避免 run-root 接口与 writer 一起震荡 | 直接删文件会触发模块契约与下游审计目录同步变更 |
| 本轮只把 road-like 几何作为 hard mask | 与用户确认的“只对 Roads / RCSDRoad 做 1m negative mask”保持一致 | 同时重做 node 语义会把任务扩大成 Step45/Step6 全面重构 |
