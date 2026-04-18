# Implementation Plan: T03 Step67 Contract Formalization

**Branch**: `codex/t03-step67-directional-cut` | **Date**: 2026-04-18 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t03-step67-contract-formalization/spec.md)  
**Input**: Feature specification from `/specs/t03-step67-contract-formalization/spec.md`

## Summary

本轮做的是**正式文档收口**，不是新的算法开发。  
策略是把当前已经稳定的 T03 Step4-7 业务边界、状态语义、输出组织和 closeout 结果正式写回 repo source-of-truth，同时明确哪些仍属于实现参数或未关闭限制，不将其误写成长期契约。

## Technical Context

**Language/Version**: Markdown 文档治理，Python 代码仅用于事实核对  
**Primary Dependencies**: 本地 repo 文档、Step45/Step67 当前实现、pytest/real-case 回归证据  
**Storage**: repo docs + thread deliverables (`MD/JSON/CSV/PNG`)  
**Testing**: 文档与代码事实对照审计；不以新增算法测试为主  
**Target Platform**: WSL on Windows  
**Project Type**: GIS topology processing module / documentation governance  
**Constraints**:
- 不新增 CLI / entrypoint
- 正式文档可以升级到 Step67 clarified formal stage，但不冻结 solver 参数
- 项目级治理文档与模块级 source-of-truth 必须同步更新
- 手工确认的输入数据错误只记入 closeout / thread deliverables，不发明新的正式机器状态字段

## Constitution Check

*GATE: Must pass before implementation. Re-check after design.*

- 已遵守仓库治理入口与 source-of-truth 优先级
- 本轮属于中等以上结构化文档治理，继续使用 spec-kit
- 不新增执行入口，不修改 T02 正文实现
- 不把 `outputs/*` 当作 source-of-truth，只把其结果摘要正式写回 closeout/documents

## Project Structure

### Documentation (this feature)

```text
specs/t03-step67-contract-formalization/
├── spec.md
├── plan.md
└── tasks.md
```

### Source-of-Truth Docs To Update

```text
docs/
├── PROJECT_BRIEF.md
└── doc-governance/
    ├── README.md
    ├── module-lifecycle.md
    ├── current-module-inventory.md
    └── current-doc-inventory.md

modules/t03_virtual_junction_anchor/
├── AGENTS.md
├── README.md
├── INTERFACE_CONTRACT.md
└── architecture/
    ├── 01-introduction-and-goals.md
    ├── 02-constraints.md
    ├── 03-context-and-scope.md
    ├── 04-solution-strategy.md
    ├── 06-step45-closeout.md
    ├── 07-step6-readiness-prep.md
    ├── 08-step67-closeout.md
    └── 10-quality-requirements.md
```

**Structure Decision**: 以 `INTERFACE_CONTRACT.md` 承载正式契约，`README.md` 承载操作者入口，`architecture/*` 承载长期设计与 closeout；项目级治理索引同步更新，不改 entrypoint registry。

## Phase Plan

### Phase 0 - Requirement Audit

- 复核当前 repo/project/module source-of-truth
- 对照 Step45/Step67 代码与回归，区分：
  - 可以正式回写的稳定事实
  - 仍应保留为实现参数 / 限制项的部分

### Phase 1 - Project-Level Sync

- 更新 `docs/PROJECT_BRIEF.md`
- 更新 `docs/doc-governance/README.md`
- 更新 `module-lifecycle.md / current-module-inventory.md / current-doc-inventory.md`

### Phase 2 - Module-Level Contract Formalization

- 更新 `modules/t03_virtual_junction_anchor/AGENTS.md`
- 更新 `README.md`
- 更新 `INTERFACE_CONTRACT.md`
- 更新 `architecture/01/02/03/04/10`
- 修正文档冲突点：
  - `06-step45-closeout.md` 中 run reference 不一致
  - `07-step6-readiness-prep.md` 与正式 Step67 范围冲突
- 新增 `08-step67-closeout.md`

### Phase 3 - Thread Deliverables

- 更新线程 `SUMMARY / TO_GPT / PROPOSED_UPDATE / RUN_EVIDENCE`
- 输出给 GPT 的正式回报，说明：
  - 本轮已正式回写哪些 source-of-truth
  - 哪些仍未冻结为契约
  - remaining data-error cases 的治理口径

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 正式文档升级到 Step67 clarified formal stage，但不新增 CLI | 业务范围已经到 Step67，入口治理尚未批准新 CLI | 保持 Step45-only 会继续让 source-of-truth 与代码/验收结果脱节 |
| 在 architecture 中同时保留 `07-step6-readiness-prep` 与新增 `08-step67-closeout` | 既要保留准备阶段历史，又要新增当前正式 closeout | 直接覆盖/删除 `07` 会损失历史准备记录 |
