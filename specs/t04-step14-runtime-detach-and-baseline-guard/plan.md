# Implementation Plan: T04 Step1-4 Runtime Detach And Baseline Guard

**Branch**: `codex/t04-step14-runtime-detach-and-baseline-guard` | **Date**: 2026-04-22 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t04-step14-runtime-detach-and-baseline-guard/spec.md)

## Summary

本轮采用 `freeze-first + private-port + no-semantic-change split + regression-gated handoff` 策略：

- 先冻结 `Anchor_2` 当前关键 baseline
- 再把 T04 所需 runtime 闭包迁入 T04 私有实现
- 再做 `event_interpretation / rcsd_selection / tests` 的职责拆分
- 最后用 pytest + frozen cases 对比验证没有回退

## Technical Context

**Language/Version**: Python 3.10, Markdown  
**Primary Dependencies**: repo `.venv`, `shapely`, `fiona`, `Pillow`  
**Storage**: repo source/docs + `outputs/_work/t04_step14_batch/*` + thread handoff  
**Testing**: `pytest` + `Anchor_2` frozen-case regression  
**Target Platform**: WSL `bash`  
**Project Type**: GIS topology processing module / brownfield detach refactor  

## Constitution Check

- 已按 `AGENTS.md -> docs/doc-governance/README.md -> SPEC.md -> module docs` 完成主阅读链。
- 本轮属于跨模块重构 + 影响正式业务口径的治理型任务，使用 SpecKit 主流程。
- 不新增 repo 官方 CLI / shell 入口，因此不触碰 `entrypoint-registry.md` 的事实面。
- 所有源码改动遵守 `100 KB` 体量约束；对即将写入的源码文件已先做当前字节数自检。

## Workstreams

### 1. Specify

- 固化本轮新增硬边界
- 固化“修什么 / 不修什么 / 暂缓什么”
- 固化 QA 裁决问题清单

### 2. Plan

- 建立 T04 对 T02 的 runtime dependency inventory
- 设计 T04 私有 runtime 闭包：
  - `types/shared`
  - `contracts`
  - `io parsing / layer loading`
  - `step2 local context`
  - `step3 topology`
  - `step4 legacy core`
- 设计拆分：
  - `event_interpretation` -> pair-local / candidates / materialize / case orchestrator / facade
  - `rcsd_selection` -> local unit / aggregated unit / decision facade / shared helper
  - `test_step14_pipeline` -> smoke / selector / real-case baseline / pair-space regression

### 3. Baseline Freeze

- 以当前代码对 `Anchor_2` 重点 case 生成 `before` 快照
- 基线来源优先使用：
  - `step4_event_interpretation.json`
  - `step4_review_index.csv`
  - `step4_review_summary.json`
- 重点守门字段：
  - `primary_candidate_id`
  - `primary_candidate_layer`
  - `selected_evidence_state`
  - `review_state`
  - `positive_rcsd_present`

### 4. Implement

迁移顺序固定如下：

1. 私有化 `normalize_id / LoadedFeature / ParsedNode / ParsedRoad / BranchEvidence / parser / group resolver`
2. 私有化 `Stage4` contracts
3. 私有化 `Step1 admission`
4. 私有化 `Step2 local context`
5. 私有化 `Step3 topology skeleton`
6. 私有化 `Step4 legacy interpretation core`
7. 切换 T04 全部 imports 到本地私有实现
8. 拆分 `event_interpretation.py`
9. 拆分 `rcsd_selection.py`
10. 拆分 T04 测试文件
11. 最小文档同步

## Risk Management

- 最大风险不是逻辑重写，而是“看似去依赖，实际通过 façade 继续调 T02”。本轮禁止该路径。
- 第二大风险是 `event_interpretation.py` 在迁移过程中继续膨胀，因此 Step4 私有化优先采用多文件切分，不拷贝单个超大文件。
- `17943587` 是回归闸门，不是专项修复目标。只接受通用稳态修复带来的自然改善。

## Validation Strategy

### Structural Regression

- 搜索 T04 runtime 代码，不得再出现 `t02_junction_anchor` import
- T04 仍能完整执行 `Step1-4`

### Baseline Regression

- 对 frozen cases 生成 `after` 快照
- 产出 `baseline_compare.csv`
- 若发生变化，必须显式解释 `change_reason`

### Output Stability

- review PNG、flat mirror、index、summary、case JSON、GPKG 工件仍能稳定产出

## Handoff Plan

- repo 内落盘：
  - `specs/t04-step14-runtime-detach-and-baseline-guard/*`
- sync 目录落盘：
  - `codex_report.md`
  - `codex_oneclick.md`
  - `baseline_compare.csv`
  - `t02_runtime_dependency_inventory.md`
  - `regression_summary.json`（如需要）
  - `file_split_map.md`（如需要）
