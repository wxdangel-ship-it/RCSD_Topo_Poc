# 2026-06-14 T07/T05/T06 fail1 multi-RCSD consumption

## Context

This record covers the root-cause fix for case `1885118`, especially SWSD Segment `51811165_502120551`.

The raw data shows SWSD semantic junction `502120551` intersects two RCSDIntersection features: `5384375430160841` and `5384375430160848`. Both ids also exist as RCSD semantic main nodes in the raw `rcsdnode_slice.gpkg`. This is a valid SWSD 1:N RCSD semantic-junction situation, not a case-level T06 patch.

## Timeline

1. T07 Step2 classified `502120551` as `multiple_intersections_for_group`, wrote `is_anchor=fail1`, and recorded `matched_rcsdintersection_ids=5384375430160841|5384375430160848`.
2. Before this fix, T07 only wrote fail1 to `node_error_1` and relation evidence with `base_id_candidate=-1`; it did not publish a T07 surface candidate for T05.
3. T05 therefore had no relation for `502120551`, so T06 could not consume the RCSD semantic junction and rejected `51811165_502120551` before RCSD Segment construction.
4. T07 was changed to keep the fail1 audit fact, but also publish the matched RCSDIntersection surface candidates and write the real RCSD base-id list in relation evidence.
5. T05 Phase2 was changed to treat T07 `relation_state=multiple_intersections_for_group` with multiple explicit `base_id_candidate` values as a formal `group_existing_rcsd_nodes` action.
6. T06 Step1 was changed to allow only high-grade pair nodes with `has_evd=yes`, `is_anchor=fail1`, and `kind_2=4` to pass into Step2 as a probe candidate. Step2 still requires a valid T05 relation and normal RCSD topology checks.

## Business Logic Change

T07 no longer treats SWSD 1:N RCSDIntersection hit as an end-of-line failure for downstream processing. It still preserves `is_anchor=fail1` and `node_error_1` audit, but the handoff now contains enough explicit RCSD base ids for T05 to build one downstream RCSD semantic junction.

T05 does not infer RCSDNode ids from arbitrary matched-intersection text. It only groups when T07 explicitly provides multiple non-zero `base_id_candidate` values for `multiple_intersections_for_group`.

T06 does not globally accept `fail1` as a valid anchor. It only lets high-grade pair-node `fail1/kind_2=4` enter Step2, where missing or invalid T05 relation evidence still rejects the Segment.

## Evidence

New T07 output for `502120551`:

- `relation_state=multiple_intersections_for_group`
- `status_suggested=1`
- `base_id_candidate=5384375430160841|5384375430160848`

Manual T05 verification:

`outputs/_work/t10_case_1885118_manual_t05_after_t07_fail1_multi/t05_phase2/rcsd_junctionization_audit.csv`

The row for `502120551` is successful with:

- `scene=group_existing_rcsd_nodes`
- `reason=t07_multiple_intersections_for_group`
- `base_id=5384375430160841`
- `grouped_rcsdnode_ids=5384375430160841|5384375430160848`

Manual T06 verification:

`outputs/_work/t10_case_1885118_manual_t06_after_t06_fail1_pair_probe/t06/step2_extract_rcsd_segments/t06_rcsd_segment_replaceable.csv`

`51811165_502120551` is now replaceable with:

- `rcsd_pair_nodes=['5384376737277569', '5384375430160841']`
- `required_rcsd_nodes=['5384376737277569', '5384375430160841']`

Related fail1-node segments `1904829_502120551` and `502120551_613950089` now correctly enter Step2 but still fail with `rcsd_not_bidirectional_for_swsd_dual`; those are downstream topology/buffer directionality failures, not T05 relation absence.

## Verification

- `tests/modules/t07_semantic_junction_anchor/test_runner.py`: `13 passed`
- `tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py`: `28 passed`
- `tests/modules/t06_segment_fusion_precheck/test_step1_identify_fusion_units.py`: `8 passed`

## Non-goals

This change does not relax the global 50m T06 buffer, does not mark all fail1 nodes as successful anchors, and does not add a case-level replacement patch.
