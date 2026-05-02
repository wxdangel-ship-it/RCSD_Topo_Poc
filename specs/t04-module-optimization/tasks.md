# T04 Module Optimization Tasks

## Audit

- [x] Product audit: demand reasonableness, visual audit alignment, baseline semantics.
- [x] Architecture audit: module cohesion, file-size risks, entrypoint/document gaps.
- [x] Development audit: code complexity, duplicate logic, safe refactor sequence.
- [x] Testing audit: branch coverage, real baseline gates, runtime risk.
- [x] QA audit: CRS/topology/geometry/audit/performance final checklist.

## Slice 1 - Implemented

- [x] Pre-write byte-size check for touched Python files.
- [x] Extract Step5 surface window constants/config to `support_domain_scenario.py`.
- [x] Keep `support_domain.py` public re-export surface stable.
- [x] Update T04 building-block view.
- [x] Update repository code-size audit with current T04 file sizes.
- [x] Set T04 Step4/5/6/7 vector outputs to explicit `EPSG:3857` CRS metadata.
- [x] Run syntax verification for modified Python files.

## Slice 1 - Verification

- [x] Run Step5 support-domain tests.
- [x] Run Step6 polygon assembly tests.
- [x] Run Step4 surface scenario classification tests.
- [x] Run Anchor_2 new 6 baseline gate.
- [x] Run Anchor_2 original 30 baseline gate.
- [x] Run 39-case visual audit batch and CRS metadata check.

## Follow-Up Slices

- [x] Split `step4_road_surface_fork_binding.py` into binding policy/window/recovery/cleanup/divstrip helpers.
- [x] Split Step5 result models/vector export, terminal/window/cut/bridge helpers from `support_domain.py`.
- [ ] Split Step6 guard/relief/result helpers from `polygon_assembly.py`.
- [ ] Add unified Anchor_2 39-case baseline gate.
- [ ] Split heavy `test_step7_final_publish.py` fixtures/constants without weakening assertions.

## Slice 2 - Implemented

- [x] Pre-write byte-size check for both target files and new split modules.
- [x] Reduce `step4_road_surface_fork_binding.py` from `99035` bytes to `4970` bytes.
- [x] Reduce `support_domain.py` from `95639` bytes to `569` bytes.
- [x] Keep split implementation modules below `50 KB` each.
- [x] Update T04 building-block view and repository code-size audit.
