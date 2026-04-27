# Feature Specification: T03 Step1-Step7 Documentation Realignment

**Created**: 2026-04-27
**Status**: Draft
**Input**: `T03_正式需求文档_评审稿_v2_20260427.md` and `T03_仓库文档审计与更新方案_v2_20260427.md`

## Context

T03 has accumulated stable implementation and delivery facts through the historical `Step3 / Step45 / Step67` work threads. That naming helped during staged refactoring, but it now obscures the formal business chain:

1. Step1: case intake and local context
2. Step2: template classification
3. Step3: legal-space freeze
4. Step4: RCSD association interpretation
5. Step5: foreign / excluded negative constraints
6. Step6: constrained geometry generation
7. Step7: final acceptance and publishing

The goal of this change is to realign T03 source-of-truth documentation around `Step1~Step7`, while preserving existing code symbols, output filenames, compatibility wrappers, and test contracts that still use `step45` and `step67`.

## User Scenarios

### User Story 1 - Formal requirement readers see Step1-Step7 first

As a product or QA reader, I need T03 docs to describe the formal business chain as `Step1~Step7`, so I can review each business responsibility without decoding historical implementation phases.

### User Story 2 - Engineers can still map docs to current code and outputs

As an engineer, I need the docs to preserve a clear mapping from `Step1~Step7` to current implementation modules, output filenames, CLI names, and compatibility wrappers, so the documentation update does not imply a code rename.

### User Story 3 - QA can verify compatibility and source facts

As QA, I need project and module source facts to explain that `Step45` and `Step67` are historical implementation and compatibility labels, not the formal main requirement structure.

## Requirements

- **FR-001**: T03 main contract and README MUST organize the formal business chain by `Step1~Step7`.
- **FR-002**: T03 docs MUST keep `Step3` as a formal business step and frozen prerequisite, not downgrade it with `Step45/Step67`.
- **FR-003**: `Step45` and `Step67` MUST NOT be used as main requirement section structure in rewritten main docs.
- **FR-004**: Existing code symbols, output filenames, CLI names, tests, and compatibility wrappers MAY continue to use `step45` and `step67` where they reflect current implementation or output contracts.
- **FR-005**: A dedicated implementation mapping doc MUST define `Step45 = Step4+Step5 historical implementation stage` and `Step67 = Step6+Step7 historical delivery/finalization stage`.
- **FR-006**: The docs MUST preserve current formal outputs, including `virtual_intersection_polygons.gpkg`, `nodes.gpkg`, `nodes_anchor_update_audit.*`, case-level status/audit files, and review-only PNG/index outputs.
- **FR-007**: The docs MUST preserve existing entrypoint facts; this round does not add, remove, or rename CLI commands or scripts.
- **FR-008**: QA guidance MUST distinguish formal state (`accepted / rejected / runtime_failed`) from review-only visual classes (`V1~V5`).

## Non-Goals

- Rename code classes such as `Step45Context` or `Step67Context`.
- Rename output files such as `step45_status.json` or `step67_final_polygon.gpkg`.
- Retire compatibility wrappers.
- Change geometry, association, finalization, or batch execution behavior.
- Add or remove repo official CLI commands.

## Success Criteria

- `INTERFACE_CONTRACT.md` and `README.md` present T03 as a `Step1~Step7` module.
- `Step45/Step67` references in primary docs appear only in output/entrypoint compatibility or implementation mapping contexts.
- `architecture/11-business-steps-vs-implementation-stages.md` exists and explains the mapping clearly.
- Project-level T03 inventory no longer describes T03's formal scope mainly as `Step4-7 clarified formal stage`.
- Validation includes `rg` checks and `git diff` review; no code tests are required because no code behavior changes are made.
