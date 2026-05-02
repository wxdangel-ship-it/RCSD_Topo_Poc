# Implementation Plan: T04 Anchor_2 SWSD Window Repair

**Branch**: `codex/t04-anchor2-swsd-window-repair` | **Date**: 2026-05-02 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t04-anchor2-swsd-window-repair/spec.md)

## Summary

This change uses a documentation-first SpecKit flow:

1. Reframe T04 SWSD section-reference requirements in module source facts.
2. Preserve the current Anchor_2 30-case baseline as a hard semantic regression gate.
3. Repair Step4 classification / recovery so no-main-evidence Anchor_2 cases use SWSD or RCSD section references instead of falling to normal `no_surface_reference`.
4. Repair Step6 only where generated domains are semantically correct but rejected by component/hole artifacts.
5. Add regression coverage for the six user-audited cases.

## Role Inputs

- **Product**: Existing 30-case business behavior must not regress; six new cases follow user visual-audit semantics.
- **Architecture**: `no_surface_reference` must be defensive abnormal fallback, not a normal valid Anchor_2 branch.
- **Development**: Primary implementation paths are `surface_scenario.py`, `case_models.py`, `step4_road_surface_fork_binding.py`, `polygon_assembly.py`; avoid editing `support_domain.py` unless split because it is near 100 KB.
- **Testing**: Strengthen 30-case semantic assertions and add six-case regression.
- **QA**: Compare final state and key semantic fields, not only accepted/rejected counts.
- **Visual Audit**: Use `final_review.png`, `step4_review.png`, Step4/5/6 JSON, and final geometry to verify the corrected interpretation.

## Technical Context

**Language/Version**: Python 3.10
**Primary Dependencies**: `shapely`, `geopandas`/`fiona`, repo `.venv`
**Data Root**: `/mnt/e/TestData/POC_Data/T02/Anchor_2`
**Testing**: `pytest` real-case regression and selected unit tests
**Constraints**:

- No new official CLI or script entrypoint.
- Do not modify `support_domain.py` unless the same round handles the 100 KB file-size governance requirement.
- Do not weaken Step6 guard semantics; bridge/fill changes must pass existing post-cleanup checks.
- Existing Anchor_2 30-case baseline must pass before closeout.

## Planned Changes

### Documentation

- Update `INTERFACE_CONTRACT.md` section 3.5.
- Update `architecture/04-solution-strategy.md`.
- Update `architecture/10-quality-requirements.md`.

### Implementation

- Treat valid T04 case inputs as SWSD-context-bearing unless explicitly marked as abnormal/missing context.
- Prevent no-main-evidence recovery paths from creating `fact_reference_point`.
- Convert unbound road-surface fork cases that are valid SWSD candidates into SWSD section-reference scenarios instead of clearing to normal no-surface.
- Reclassify RCSD-anchored reverse cases without main evidence as `no_main_evidence_with_rcsd_junction`.
- For Step6, handle multi-component and small algorithm-hole artifacts only when all post-cleanup guards remain true.

### Tests

- Update surface scenario classifier expectations.
- Add six-case real regression test.
- Strengthen Anchor_2 30-case semantic gate.

## Verification

Required commands:

```bash
.venv/bin/python -m py_compile src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/*.py
.venv/bin/python -m pytest -q -s tests/modules/t04_divmerge_virtual_polygon/test_step4_surface_scenario_classification.py
.venv/bin/python -m pytest -q -s tests/modules/t04_divmerge_virtual_polygon/test_706629_swsd_only_regression.py
.venv/bin/python -m pytest -q -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate
```

Plus a six-case batch run over:

```text
785629 785631 785731 795682 807908 823826
```

## Risks

- Step4 recovery changes can accidentally change known rejected cases such as `760598`.
- Step6 multi-component repair can hide real topology errors if not guarded by allowed/forbidden/terminal/lateral checks.
- `support_domain.py` is near the 100 KB threshold, so direct Step5 changes may require a split plan.
