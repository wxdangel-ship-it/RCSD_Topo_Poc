# Feature Specification: T03 Formal Contract Cleanup

**Created**: 2026-04-27
**Status**: Draft
**Input**: User request to remove historical `Step45 / Step67` names from the formal T03 contract, scripts, tests, and current documentation.

## Context

T03 has already moved its formal documentation structure to `Step1~Step7`. The remaining inconsistency is that current code symbols, output filenames, tests, scripts, and some architecture files still expose historical `Step45 / Step67` labels.

The user has explicitly authorized a formal contract migration, not just a documentation cleanup. This means the current formal output and test names should be realigned as well.

## Naming Decisions

- `Step45*` code concepts become `Association*`.
- `Step67*` code concepts become `Finalization*`.
- `step45_state` becomes `association_state`.
- `step45_established` becomes `association_established`.
- `step45_prerequisite_issues` becomes `association_prerequisite_issues`.
- `step45_*` case outputs become `association_*` case outputs.
- `step67_final_polygon.gpkg` becomes `step7_final_polygon.gpkg`.
- `step67_review.png` becomes `step7_review.png`.
- `step67_*` Step7 reasons become `step7_*` reasons.
- Historical shell wrappers with `step67` in the script name are removed.
- Historical closeout documents are moved from `architecture/` into `history/`.

## Non-Goals

- Change Step3 / Step4 / Step5 / Step6 / Step7 business logic.
- Change accepted case geometry behavior.
- Change internal full-input concurrency.
- Preserve old wrapper scripts as official entrypoints.

## Success Criteria

- `scripts/` no longer contains `t03_*step67*` scripts.
- `architecture/` no longer contains `step45` / `step67` filenames.
- T03 test filenames no longer use `step45` / `step67`.
- Current source and tests use `Association*` / `Finalization*` code concepts.
- Current formal case outputs use `association_*` and `step7_*` names.
- Documentation and entrypoint registry reflect the removed wrappers and new names.
- T03 contract-focused regression tests pass for the renamed contract.
- Full T03 regression execution must be reported honestly if it exposes pre-existing Step6/Step7 semantic expectation failures outside this naming migration.
