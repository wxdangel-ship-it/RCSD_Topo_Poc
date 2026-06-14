# 2026-06-14 T03/T05 RCSD Semantic Handoff Fix

## Context

This record covers the T10 audit around `600668000_610666729` and `974921_39546710`.

The business issue is that T03 accepted T-shaped SWSD semantic junctions and identified RCSD required nodes, but T05 did not consume those nodes as successful RCSD semantic junction relations. T06 therefore received incomplete pair-node relations and had to compensate downstream.

## Timeline

1. Root-cause audit found that T03 case output `step6_status.json` contains `required_rcsdnode_ids` and `support_rcsdroad_ids`, while `t03_swsd_rcsd_relation_evidence.csv` drops them.
2. Code audit found `write_t03_relation_evidence()` only read legacy `association_status.json`; current T03 case directories produce `step6_status.json`.
3. T05 backfill experiment showed that restoring T03 required nodes makes T05 consume T03 evidence, but raw RCSD member ids can be selected as base ids before semantic main-node normalization.
4. Source fix added T03 handoff status fallback from `association_status.json` to `step6_status.json`.
5. Source fix added T05 canonical RCSD node handling before direct relation and existing-node grouping, using existing `mainnodeid` semantics.
6. Source fix changed the T05 innernet script default T03 backfill mode to `auto` for old outputs that still lack handoff fields.
7. Follow-up audit on `26162599_26162601` found that T05 produced a successful T03/T05 relation for SWSD node `26162601`, but T07 Step3 did not backfill `is_anchor=yes` because `kind_2=2048` was outside the T05 relation backfill scope.
8. Source fix added `kind_2=2048` to T07 Step3 T05-relation backfill scope. T07 still does not independently create 2048 relations; it only consumes a successful T05 `intersection_match_all` relation with an existing RCSD base id.

## Business Logic Change

T03 now publishes accepted A-class T-shaped semantic junctions as successful relation evidence when `step6_status.json` has required RCSD nodes.

T05 now canonicalizes RCSD member nodes to existing RCSD semantic main nodes before choosing a base id. When multiple semantic RCSD nodes need to be merged, T05 groups both the raw member nodes and the canonical main nodes so downstream topology sees one consistent semantic junction.

T07 Step3 now treats `kind_2=2048` as eligible for T05 relation backfill when `has_evd=yes`, `is_anchor=no`, and T05 has already emitted `status=0` with a non-zero RCSD `base_id` present in `RCSDNode`. This lets T06 Step1 consume T03/T05-confirmed T-shaped semantic junction anchors without asking T07 to perform a new independent 2048 match.

## Evidence

For `600668000`, T03 `step6_status.json` contains raw required nodes `5396526629984361|5396526629984380`. Raw data shows `5396526629984361.mainnodeid = 5396526629984448`, so T05 must treat this as semantic nodes `5396526629984448` and `5396526629984380`.

For `610666729`, T03 `step6_status.json` contains `5396501766485050|5396501766485051`; raw data shows `5396501766485050.mainnodeid = 5396501766485051`, so T05 should expose `5396501766485051` as the semantic base.

For `974921`, T03 `step6_status.json` contains `5396513947461792|5396513947461793`; raw data shows `5396513947461792.mainnodeid = 5396513947461793`, so T05 should expose `5396513947461793` as the semantic base.

## 991176 Deep Audit Addendum

The baseline run `outputs/_work/t10_goal236_baseline_clean_991176_e2e/t10_goal236_baseline_clean_991176_20260614` shows the failure chain for the target segments:

1. T03 accepted `600668000`, `610666729`, `974921`, and `39546710`, but `t03_swsd_rcsd_relation_evidence.csv` did not publish `required_rcsdnode_ids`, `required_rcsdroad_ids`, or `support_rcsdroad_ids`.
2. Baseline T05 therefore handled these T-shaped surfaces through the T07 fallback path and emitted `failure_relation` with `reason=t_junction_deferred_to_t03` and `geometry_mode=zero_length_no_rcsd`.
3. Baseline T06 Step2 rejected `974921_39546710` with `invalid_pair_relation_status` and rejected `600668000_610666729` with `retained_road_buffer_overlap_insufficient`; both were retained in Step3.
4. After the T03 evidence fallback, T05 canonical main-node handling, and T07 `kind_2=2048` backfill were applied, `974921_39546710` and `600668000_610666729` both entered T06 Step2 buffer segment output and were replaced in Step3.

Across case `991176`, this was a systematic handoff issue rather than a case patch:

- 76 accepted T03 nodes had empty baseline relation fields while their per-case Step6 status contained RCSD relation evidence.
- 36 of them became `success_required_rcsd_junction` after backfill.
- 40 of them became `rcsd_present_not_junction` and were consumed by T05 as road-only support.
- Baseline T05 reasons for these 76 nodes were `t_junction_deferred_to_t03` for 62 nodes and `no_existing_rcsdintersection` for 14 nodes.
- Fixed T05 consumed them as `success_required_rcsd_junction` for 31 nodes, `t03_b2_road_only_support` for 32 nodes, `road_only_projection_near_endpoint_reuse_rcsdnode` for 8 nodes, and `multiple_base_id_merged` for 5 nodes.
- 30 SWSD segments that touched these T03 nodes changed from retained or mixed retained/replaced status in baseline to `replaced` in the fixed run.

## 991176 Current E2E Verification Addendum

After the source fixes were present in the active worktree, a fresh single-case end-to-end rerun was executed for case `991176`:

`outputs/_work/t10_991176_t03_t05_handoff_current_e2e/t10_991176_t03_t05_handoff_current_20260614`

The rerun passed end-to-end. In this current output, T03 publishes relation evidence for `600668000`, `610666729`, `974921`, and `39546710`; T05 consumes the four surfaces from source module `T03`; T06 Step2 marks both `600668000_610666729` and `974921_39546710` as replaceable; T06 Step3 marks both as `replaced`.

For `600668000`, current T05 emits `reason=multiple_base_id_merged`, `base_id=5396526629984380`, and `grouped_rcsdnode_ids=5396526629984361|5396526629984380|5396526629984448`. This confirms that the RCSD member node `5396526629984361`, its raw semantic main node `5396526629984448`, and the adjacent semantic junction node `5396526629984380` are materialized as one downstream RCSD junction for T06 consumption.

A cross-case scan of old baseline-clean outputs found the same historical T03 handoff evidence-loss pattern in four old baseline cases:

- `1885118`: 691 accepted T03 nodes had Step6 evidence that was not published in baseline relation evidence.
- `609214532`: 501 accepted T03 nodes had the same pattern.
- `74155468`: 42 accepted T03 nodes had the same pattern.
- `991176`: 76 accepted T03 nodes had the same pattern.

The same scan on the fresh current `991176` rerun found zero missing T03 handoff evidence rows. The cross-case baseline count is therefore an old-output rerun/backfill scope, not evidence that the current code still emits the defect.

For this case, the target segments are not T04-origin failures. In the fresh current `991176` rerun, T05 consumes 22 T04 relations and all 22 have `status=0`; the historical failure for `600668000_610666729` and `974921_39546710` remains attributable to T03 evidence handoff plus T05 RCSD semantic-node canonicalization.

## 991176 Raw Trace Audit Addendum

After the user questioned whether `600668000` should have been resolved earlier by T03/T04 before T06 consumption, a raw-data trace audit was added under `outputs/_work/t10_991176_t03_t05_raw_trace_20260614`.

The audit confirms that T03 did build accepted virtual surfaces for `600668000`, `610666729`, `974921`, and `39546710`; the missing behavior in the old baseline was the handoff from T03 Step6 evidence into `t03_swsd_rcsd_relation_evidence.csv`, followed by T05 RCSD semantic main-node canonicalization. For `600668000`, raw RCSD node `5396526629984361` has `mainnodeid=5396526629984448`; T05 must group `5396526629984361|5396526629984448|5396526629984380` so downstream modules consume one RCSD junction. For `974921`, raw RCSD node `5396513947461792` has `mainnodeid=5396513947461793`; `39546710` is a B-class road-only support endpoint and must be resolved by T05 as near-endpoint reuse from T03 support evidence, not as a T04 split/merge relation.

The compact T06 comparison in the same audit package shows baseline `600668000_610666729` rejected at Step2 with `retained_road_buffer_overlap_insufficient`, baseline `974921_39546710` rejected with `invalid_pair_relation_status`, and both current segments are Step2 `replaceable` and Step3 `replaced`.

## Non-goals

This change does not relax T06 buffer thresholds and does not add case-specific segment replacement patches.
