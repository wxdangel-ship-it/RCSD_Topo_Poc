# Implementation Plan: T04 Step1-4 Speckit Refactor

**Branch**: `codex/t04-step14-speckit-refactor` | **Date**: 2026-04-20 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t04-step14-speckit-refactor/spec.md)

## Summary

本轮采用 `doc-first + brownfield reuse + modular orchestration` 策略：

- 文档面先创建 `t04_divmerge_virtual_polygon`
- 算法内核优先复用 T02 Stage4 的 Step2/3/4 核心能力
- 输出与审计组织优先复用 T03 的 case/batch/review 模式
- 不新增 repo 官方 CLI，只提供模块内 runner 与测试调用

## Technical Context

**Language/Version**: Python 3.10, Markdown  
**Primary Dependencies**: `shapely`, `fiona`, `Pillow`, repo `.venv`  
**Storage**: repo docs + `outputs/_work/t04_step14_batch` + thread handoff  
**Testing**: `pytest` unit/smoke + selected real-case batch run  
**Target Platform**: WSL on Windows  
**Project Type**: GIS topology processing module / brownfield refactor  
**Constraints**:

- 只做 Step1-4
- 不新增 repo 官方 CLI / shell 入口
- 文档必须先于代码
- Step4 review 使用 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL`
- 内核可复用 T02 Stage4，但 T04 模块结构必须按领域能力分层

## Constitution Check

- 已遵守 `AGENTS.md -> docs/doc-governance/README.md -> SPEC.md -> module docs` 的主阅读链
- 本轮属于 brownfield 结构化变更，使用 spec-kit 产物承接 specify / plan / tasks
- 不把 `outputs/*` 当 source-of-truth，只把正式规则写入模块文档
- 不新增 repo 官方入口，避免违反入口治理

## Project Structure

### SpecKit

```text
specs/t04-step14-speckit-refactor/
├── spec.md
├── plan.md
└── tasks.md
```

### Module Docs

```text
modules/t04_divmerge_virtual_polygon/
├── AGENTS.md
├── README.md
├── INTERFACE_CONTRACT.md
└── architecture/
    ├── 01-introduction-and-goals.md
    ├── 02-constraints.md
    ├── 03-context-and-scope.md
    ├── 04-solution-strategy.md
    ├── 05-building-block-view.md
    └── 10-quality-requirements.md
```

### Source Layout

```text
src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/
├── __init__.py
├── case_models.py
├── case_loader.py
├── admission.py
├── local_context.py
├── topology.py
├── event_units.py
├── event_interpretation.py
├── review_render.py
├── outputs.py
└── batch_runner.py
```

### Tests

```text
tests/modules/t04_divmerge_virtual_polygon/
├── test_batch_runner.py
├── test_outputs.py
└── test_step14_pipeline.py
```

## Design Decisions

1. **模块 ID 采用 `t04_divmerge_virtual_polygon`**  
   对齐 T02 Stage4 已冻结的业务语义，同时用 T04 模块目录承接正式长期维护面，避免继续沿用 `stage4_*` 作为正式模块名。

2. **T04 输入固定为 case-package 风格目录**  
   本轮先承接本地 case 模式；full-input 与 candidate discovery 只在文档中说明边界，不在本轮新增官方入口。

3. **T04 算法内核采用“复用 + 包装 + 定向改造”**  
   Step2/3 主要复用 T02；Step4 需要在 T02 的基础上增加 event-unit 输出和 T03 风格 review 物化。

4. **Step4 review 直接沿用 T03 render helper**  
   复用 `legal_space_render.py` 的绘制底层能力，避免另起一套渲染框架。

## Phase Plan

### Phase 1 - Specify

- 创建 spec/plan/tasks
- 创建 T04 模块文档面
- 同步 project-level inventory / lifecycle / doc inventory / brief / spec

### Phase 2 - Plan

- 固化 T04 代码结构
- 定义 batch run root、case outputs、flat mirror、index、summary
- 明确复用 T02/T03 的代码边界

### Phase 3 - Tasks

- 拆成文档、实现、测试、handoff 四段任务
- 每段附带验收口径

### Phase 4 - Implement

- 实现 T04 case loader / Step1-4 runner / outputs / render
- 补测试
- 跑 synthetic smoke 与 selected real cases
- 输出 handoff
