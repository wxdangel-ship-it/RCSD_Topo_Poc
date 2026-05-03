# T04 RCSD Alignment and Surface Rules Tasks

## Phase 0 - Requirement and Baseline Readiness

- [x] Record RCSD/SWSD semantic junction baseline rules in module source facts.
- [x] Record RCSD positive recall / no semantic junction / no RCSD definitions.
- [x] Record negative mask sources including unrelated SWSD and RCSD.
- [x] Record six surface scenario boundary rules.
- [x] Complete independent Product/Architecture/Development/Testing/QA gap audits.
- [x] Confirm official 39-case case list: `E:\TestData\POC_Data\T02\Anchor_2` / `/mnt/e/TestData/POC_Data/T02/Anchor_2`.
- [x] Confirm `RCSD_Topo_Poc_T04_REQUIREMENT.md` is not a higher-priority requirement input.
- [x] Extract expected semantic fields for all 39 cases from current audit/baseline artifacts.

## Phase 1 - Alignment Model

- [x] Pre-write byte-size check for every touched `.py` / test / script file.
- [x] Add `RcsdAlignmentType` enum or constants.
- [x] Add Step4 alignment result model with positive ids, unrelated ids, candidate ids, ambiguity reasons.
- [x] Add `rcsd_semantic_junction` classification.
- [x] Add `rcsd_junction_partial_alignment` classification.
- [x] Add `rcsdroad_only_alignment` classification.
- [x] Add `no_rcsd_alignment` classification.
- [x] Add `ambiguous_rcsd_alignment` classification and block accepted state.
- [x] Preserve `rcsd_match_type` as derived compatibility field.

## Phase 2 - Step4 Outputs and Step5 Input Contract

- [x] Add `rcsd_alignment_type` to `PositiveRcsdSelectionDecision`.
- [x] Add `rcsd_alignment_type` to `T04EventUnitResult`.
- [x] Add alignment fields to `step4_candidates.json`.
- [x] Add alignment fields to event evidence audit.
- [x] Add alignment fields to review index / summary rows.
- [x] Change Step5 to consume frozen alignment result.
- [x] Remove or quarantine Step5 inference from `required_rcsd_node / selected_rcsdroad_ids / fallback_rcsdroad_ids`.

## Phase 3 - Surface Scenario Mapping

- [x] Refactor `surface_scenario.py` to map from `has_main_evidence + rcsd_alignment_type + swsd_context`.
- [x] Implement scenario 1: main evidence + semantic junction.
- [x] Implement scenario 2a: main evidence + partial junction.
- [x] Implement scenario 2b: main evidence + road-only alignment.
- [x] Implement scenario 3: main evidence + no RCSD.
- [x] Implement scenario 4: no main evidence + semantic junction.
- [x] Implement scenario 5a: no main evidence + partial junction.
- [x] Implement scenario 5b: no main evidence + road-only alignment.
- [x] Implement scenario 6: no main evidence + no RCSD + SWSD.
- [x] Keep `no_surface_reference` defensive-only and audited.

## Phase 4 - Negative Mask and Support Domain

- [x] Add SWSD node/road unrelated mask inputs.
- [x] Add RCSDNode/RCSDRoad unrelated mask inputs.
- [x] Add divstrip body and void as separate mask sources.
- [x] Keep forbidden domain and terminal cut as separate mask sources.
- [x] Emit mask source ids and geometries in Step5 audit.
- [x] Ensure positive growth cannot invade negative masks; positive objects are excluded by id only, never by geometry-erasing unrelated masks with corridor / allowed growth.
- [x] Add post-cleanup overlap audit per mask channel.
- [x] Allow `barrier_separated_case_surface_ok` only when negative masks split an otherwise valid result and all post-cleanup checks pass.

## Phase 5 - Complex Case-Level Alignment

- [x] Add unit-level alignment audit export.
- [x] Add case-level alignment aggregate.
- [x] Detect cross-unit conflict across unrelated RCSD semantic objects.
- [x] Detect bridge growth crossing unrelated SWSD/RCSD masks.
- [x] Reject or review ambiguous case-level alignment instead of silent merge.

## Phase 6 - Step6 Constraint Discipline and Split

- [x] Pre-write byte-size check for `polygon_assembly.py` and new split files.
- [x] Split Step6 guard context from `polygon_assembly.py`.
- [x] Split Step6 result dataclass/model helpers.
- [x] Split Step6 relief helpers.
- [x] Ensure relief cannot expand allowed or weaken forbidden/cut without Step5 audit.
- [x] Update `docs/repository-metadata/code-size-audit.md` if size table changes.

## Phase 6A - Current Complex Surface Correction

- [x] Record that complex / multi normal output must be a single connected case surface after inter-unit section bridge.
- [ ] Remove generic `barrier_separated_case_surface_ok` accepted pass for scenario 5b / ordinary MultiPolygon results.
- [ ] Ensure simple SWSD + RCSDRoad fallback cases such as `706347` do not regress from complex bridge changes.
- [ ] Add or adjust regression assertions for `765050` so accepted output requires inter-unit bridge and single connected final surface; real negative mask blocker must be audited as rejected / exception, not accepted MultiPolygon.
- [ ] Re-run targeted real cases `706347 / 724081 / 765050 / 768675`.

## Phase 7 - Tests

- [x] Add `test_step4_rcsd_alignment_type.py`.
- [x] Extend `test_step4_surface_scenario_classification.py` for `rcsd_alignment_type`.
- [x] Extend `test_step5_surface_scenario_support_domain.py` for partial vs road-only boundaries.
- [x] Add Step5 negative mask tests.
- [x] Add Step6 negative mask and forbidden overlap tests.
- [x] Add ambiguous alignment rejected test.
- [x] Add complex case-level conflict tests.
- [x] Add unified Anchor_2 39-case baseline gate.
- [x] Preserve original 30-case gate semantics.
- [x] Preserve new6 gate semantics.

## Phase 8 - QA and Visual Audit

- [x] Verify accepted outputs never contain `no_surface_reference`.
- [x] Verify rejected/runtime/formal missing map to `fail4`.
- [x] Verify GPKG/GeoJSON CRS is `EPSG:3857`.
- [x] Verify all final geometries valid and non-empty when accepted.
- [x] Verify summary/audit/feature count consistency.
- [x] Generate visual audit index for 39-case run.
- [x] Record perf audit summary and threshold.
- [x] Confirm final review PNG renders RCSD/SWSD current/other roads/nodes without blocking visual inspection.
- [x] Confirm final review PNG labels each case `surface_scenario_type`.
- [x] Confirm final review PNG highlights the unique positive RCSD alignment RCSDRoad in thick red for semantic junction, partial junction, and road-only alignment.
- [x] Confirm final review PNG does not draw thick red RCSDRoad for `no_rcsd_alignment`; the no-RCSD meaning is expressed by the scenario label.
- [x] Confirm final review PNG marks section-boundary reference objects.

## Phase 9 - Required Commands

The exact commands may be adjusted to the active environment, but formal implementation must include equivalent checks:

```bash
.venv/bin/python -m pytest -q tests/modules/t04_divmerge_virtual_polygon/test_step4_surface_scenario_classification.py
.venv/bin/python -m pytest -q tests/modules/t04_divmerge_virtual_polygon/test_step5_surface_scenario_support_domain.py
.venv/bin/python -m pytest -q tests/modules/t04_divmerge_virtual_polygon/test_step6_surface_scenario_guards.py
.venv/bin/python -m pytest -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate
.venv/bin/python -m pytest -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_new6_user_audit_surface_scenario_gate
.venv/bin/python -m pytest -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate
```
