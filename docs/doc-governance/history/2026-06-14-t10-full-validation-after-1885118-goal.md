# 2026-06-14 T10 Full Validation After 1885118 Goal

## Context

This record covers the completion audit for case `1885118` target Segment fixes and the subsequent full T10 package validation.

The baseline for comparison is the preserved beginning-of-round output:

`outputs/_work/t10_goal236_baseline_clean_{case}_e2e/t10_goal236_baseline_clean_{case}_20260614`

The current full validation output is:

`outputs/_work/t10_full_current_after_1885118_goal/t10_full_current_after_1885118_goal_20260614_115208`

## Timeline

1. The `1885118` target Segment audit was regenerated under `outputs/_work/t10_1885118_completion_audit_20260614`.
2. The current single-case full T10 output for `1885118` passed end-to-end and all 13 target Segment ids moved from retained in baseline to replaced in current output.
3. T08 Tool6 evidence confirmed nodes `505230256` and `504230665` are detected as `cross_non_cross` with reason `two_parallel_outward_angle_groups_each_has_in_and_out`.
4. T08 Tool4 evidence confirmed both nodes are repaired from `kind_2=4` to `kind_2=1`.
5. T01 evidence after Tool4 confirmed the expected merged Segment ids `1904815_503230898` and `1878456_1878458`.
6. The retained SWSD endpoint audit confirmed the remaining missing same-source endpoints are original clipping only.
7. The focused regression suite passed: `68 passed in 23.55s`.
8. A fresh full T10 package run over all four cases passed: 4 passed, 0 failed, 0 blocked, 0 skipped.

## Business Logic Verification

For the 13 `1885118` target Segment ids, the baseline had 0 Step3 replacements and 13 retained SWSD Segment relations. The current output has 13 Step2 replaceable units and 13 Step3 replacements.

Across the four T10 cases, T06 Step3 SWSD Segment replacement improved from 1022 / 4259 to 1591 / 4259. The replacement-rate delta is +0.133600.

Across the same four cases, T06 Step2 replaceable RCSD Road unique length improved from 707.072099 km to 837.830062 km. The length delta is +130.757963 km, and the length-rate delta is +0.104860.

T09 restriction output count increased from 1486 to 1672.

## Endpoint-Clipping Excluded RCSD Rate

An additional conservative clipping-excluded RCSD Road length rate was computed by removing raw RCSD roads whose `snodeid` or `enodeid` is missing from the raw `rcsdnode_slice.gpkg`. If a clipped road is already replaced, it is removed from both numerator and denominator.

Across the four T10 cases, this removes 305 raw RCSD roads and 44.791928 km from the denominator. None of these endpoint-clipped roads is currently counted in the replaceable numerator.

With this endpoint-clipping exclusion, current RCSD Road unique length replacement is 837.830062 km / 1202.185468 km = 0.696922. The same denominator applied to the beginning-of-round baseline gives 707.072099 km / 1202.185468 km = 0.588156. The clipping-excluded rate delta is +0.108767.

## Artifacts

- `outputs/_work/t10_1885118_completion_audit_20260614/summary.json`
- `outputs/_work/t10_1885118_completion_audit_20260614/target_segment_baseline_vs_current_1885118.csv`
- `outputs/_work/t10_full_current_after_1885118_goal/t10_full_current_after_1885118_goal_20260614_115208/t10_e2e_run_summary.json`
- `outputs/_work/t10_full_current_after_1885118_goal_comparison_20260614/summary.json`
- `outputs/_work/t10_full_current_after_1885118_goal_comparison_20260614/case_metrics_baseline_current.csv`
- `outputs/_work/t10_full_current_after_1885118_goal_comparison_20260614/case_metric_deltas.csv`
- `outputs/_work/t10_full_current_after_1885118_goal_comparison_20260614/aggregate_metrics.csv`
- `outputs/_work/t10_full_current_after_1885118_goal_comparison_20260614/rcsd_rate_excluding_endpoint_clipping.csv`
- `outputs/_work/t10_full_current_after_1885118_goal_comparison_20260614/compute_endpoint_clipping_adjusted_rate.py`

## Notes

The aggregate RCSD Road metrics are case-level sums from T06 Step2 summaries and are not globally de-duplicated across different T10 cases.

This validation does not introduce additional T06 case patches. It verifies the upstream T03/T05/T07 handoff fixes, the T08 Tool6/Tool4 non-cross repair, and the T06 retained SWSD endpoint preservation behavior together in the current end-to-end run.
