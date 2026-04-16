# Implementation Plan: T02 Stage3 Execution-Layer Refactor

**Branch**: `001-t02-stage3-execution-refactor` | **Date**: 2026-04-13 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/001-t02-stage3-execution-refactor/spec.md)  
**Input**: Feature specification from `/specs/001-t02-stage3-execution-refactor/spec.md`

## Summary

当前 Stage3 的主要问题不是包装层不完整，而是执行层尚未完成契约化重构。`virtual_intersection_poc.py` 仍以超大单体主流程串联 Step3~7，并依赖大量 `late_*cleanup* / trim` pass 做后置修补。  
本次计划先完成执行层重构，再恢复 `Anchor 61` 的全量 case 优化与目视审查闭环。

## Technical Context

**Language/Version**: Python 3.x  
**Primary Dependencies**: geopandas, shapely, pytest, project-local T02 utilities  
**Storage**: File-based GIS artifacts (`GPKG`, `PNG`, `JSON`, `MD`)  
**Testing**: pytest, structural checks, focused case regression, later `Anchor 61` full regression  
**Target Platform**: WSL on Windows, local external data root `/mnt/e/TestData/POC_Data`  
**Project Type**: GIS topology processing module / CLI execution pipeline  
**Performance Goals**: 重构后保持当前 Stage3 可运行性，不以本轮优化吞吐量为主要目标  
**Constraints**: 不改冻结契约；默认不改测试；禁止继续以 case patch 替代执行层重构；不得破坏现有 packaging contract  
**Scale/Scope**: 仅限 T02 / Stage3 执行层、审计链、输出链；暂不扩展 Stage4 或其他模块

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- 已读仓库治理入口：`AGENTS.md`、`docs/doc-governance/README.md`、`docs/repository-metadata/README.md`
- 约束满足情况：
  - 中等及以上结构治理变更已切到 spec-kit 分支与 `specs/001-*`
  - 当前主结构债文件 [virtual_intersection_poc.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py) 约 `984 KB`，必须纳入拆分计划
  - 计划阶段不新增新的业务执行入口
  - 计划阶段不修改冻结文档契约
- 当前 gating 结论：**允许进入结构重构计划，不允许继续 case-driven patch 主线**

## Project Structure

### Documentation (this feature)

```text
specs/001-t02-stage3-execution-refactor/
├── plan.md
├── spec.md
├── research.md
├── data-model.md
├── quickstart.md
└── contracts/
    └── stage3-step-boundaries.md
```

### Source Code (repository root)

```text
src/rcsd_topo_poc/modules/t02_junction_anchor/
├── virtual_intersection_poc.py                  # 当前超大 orchestrator + 执行核心
├── virtual_intersection_full_input_poc.py       # batch / full-input 包装层
├── stage3_review_contract.py                    # 现有 review contract / package helper
└── [to be introduced in refactor]
    ├── stage3_context_builder.py
    ├── stage3_step3_legal_space.py
    ├── stage3_step4_rc_semantics.py
    ├── stage3_step5_foreign_model.py
    ├── stage3_step6_polygon_solver.py
    ├── stage3_step7_acceptance.py
    └── stage3_audit_assembler.py
```

**Structure Decision**: 保留现有入口文件，但将其缩回 orchestrator；执行层和审计层按 Step3~7 拆分到独立模块。`virtual_intersection_full_input_poc.py` 继续承担 batch 包装，但改为消费新的 Step result / audit result。

## Phase Plan

### Phase 0 - 基线冻结

- 冻结 `round_15` 为“结构未完成”的基线
- 停止继续对 `724123 / 769081 / 851884` 追加 late-pass 修补
- 保护当前已对齐锚点，避免在结构迁移前继续引入认知漂移

### Phase 1 - 契约差距建模

- 产品经理产出 Step1~7 契约差距矩阵
- 架构师产出目标执行层架构与迁移顺序
- QA 产出“何时算结构重构完成”的结构门槛
- 测试经理产出“重构期先不恢复 61-case”的测试策略
- 目视审查 Agent 产出重新介入的准入条件

### Phase 2 - 执行层 contract 抽取

- 定义 `Stage3Context`
- 定义 `Step3LegalSpaceResult`
- 定义 `Step4RCSemanticsResult`
- 定义 `Step5ForeignModelResult`
- 定义 `Step6GeometrySolveResult`
- 定义 `Step7AcceptanceResult`
- 定义 `Stage3AuditRecord`

**Gate**: 只有当上述结果对象可稳定实例化，才允许开始迁移主流程。

### Phase 3 - 迁移顺序

1. 先拆 `Step7 acceptance`  
   目标：让 Step7 成为唯一终裁层，禁止其后再改几何或 foreign 语义。
2. 再拆 `Step4 RC semantics`  
   目标：selected / required / support / excluded RC 变成显式语义对象，不再靠 late pass 临时决定。
3. 再拆 `Step5 foreign model`  
   目标：把 foreign node / road-arm-corridor / rc context 的硬排除模型前置固定。
4. 再拆 `Step6 polygon solver`  
   目标：从“先长面再修面”改成“legal space + foreign hard boundary + must-cover”的受约束生成。
5. 最后拆 `Step3 legal space` 与 orchestrator 收口  
   目标：legal activity space 成为不可回写的只读结果，并将 `virtual_intersection_poc.py` 缩回入口编排。

### Phase 4 - 审计链重构

- `root_cause_layer / root_cause_type / visual_review_class` 直接来自 Step result
- `stage3_rc_gap` 成为 Step4 原生审计信号
- `foreign` 子型成为 Step5 原生审计信号
- `late_*cleanup*` 若保留，必须降级成 bounded optimizer，并在审计中显式标注“仅优化、非主语义”

### Phase 5 - 结构验收

必须同时满足：

- Step3~7 均有显式结果对象
- Step3~7 单向依赖，后置不反写
- Step7 是唯一终裁层
- 审计链来自结构结果而非字符串推断
- 不再新增承担主语义的 late pass

### Phase 6 - 恢复 case 优化

结构验收通过后，才恢复：

1. 焦点 `V4` 桶回归  
2. `Anchor 61` 全量回归  
3. 目视审查 Agent 重新终审  

并拆成两条验证线：

- `正常准出正确性`
- `目视分类正确性`

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 保留现有入口文件并分阶段迁移 | 避免一次性重写 T02/Stage3 造成回归失控 | 直接整文件重写风险过高，且不利于保护现有 packaging contract |
| 允许短期并存 orchestrator 与新 step modules | 迁移期需要逐步切换依赖 | 一次性切换全部步骤会放大定位成本与回归范围 |
