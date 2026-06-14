# 2026-06-14 T06 Retained SWSD Endpoint Preservation

## Context

This record covers the case `1885118` audit around `47115450_622630806` and its retained side segment `513348884_613345278`.

The target segment `47115450_622630806` was already replaceable after the T03/T05/T07 handoff fixes, but T06 Step3 still removed SWSD node `613345278` because it was an endpoint of replaced SWSD roads. Another retained SWSD road, `528921747`, still referenced `613345278`, so the final `t06_frcsd_road` contained a road endpoint that was missing from `t06_frcsd_node`.

## Timeline

1. Audit found `47115450_622630806` had `isolated_attach_loss_count=1` and `junc_attach_loss_reason=junc_relation_missing_or_invalid`.
2. T07 evidence showed `613345278` remained `t_junction_deferred_to_t03`; T03 had not produced a valid RCSD junction relation for it.
3. T06 Step3 output showed retained SWSD road `528921747` with `snodeid=613345278`, while `613345278` was absent from `t06_frcsd_node`.
4. Code audit found T06 Step3 removed all endpoints of replaced SWSD roads, without checking whether the same SWSD node was still referenced by retained SWSD roads from another segment.
5. Source fix preserves any SWSD node that is still an endpoint of a retained SWSD road.

## Business Logic Change

T06 Step3 now treats retained SWSD roads as topology carriers. If a SWSD node is an endpoint of any retained SWSD road, Step3 must keep that node in `FRCSDNode` even when the same node is also an endpoint of replaced SWSD roads.

This fix does not synthesize a new RCSD anchor relation for a failed T03/T05 junction. In `613345278`, the retained side road remains SWSD-sourced because upstream modules have not established a valid RCSD junction mapping for that node.

## Evidence

Before the fix, `528921747` was retained with `snodeid=613345278`, but `613345278` was not present in `t06_frcsd_node`.

After the fix:

- `613345278` is present in `t06_frcsd_node` with `source=2`.
- `528921747` remains present in `t06_frcsd_road` as retained SWSD geometry.
- `47115450_622630806` remains `replaced`.
- `513348884_613345278` remains `retained_swsd`.
- The target audit package is `outputs/_work/t10_1885118_retained_node_topology_audit_20260614`.

Whole-output endpoint comparison on `1885118`:

- Old Step3 had 1478 same-source road endpoint references missing from `FRCSDNode`.
- New Step3 has 134 same-source endpoint references missing from `FRCSDNode`.
- The remaining 134 are already present in the T01/T07 input as spatial clipping missing endpoints, not introduced by Step3.

## Verification

Regression command:

`$env:PYTHONPATH=(Resolve-Path src).Path; pytest tests\modules\t06_segment_fusion_precheck\test_step3_segment_replacement.py tests\modules\t01_data_preprocess\test_step6_segment_aggregation.py tests\modules\t08_preprocess\test_tool6_nodes_type_qc.py tests\modules\t08_preprocess\test_tool4_junction_type_repair.py tests\modules\t05_junction_surface_fusion\test_phase2_rcsd_junctionization.py tests\modules\t05_junction_surface_fusion\test_t03_relation_evidence_backfill.py tests\modules\t07_semantic_junction_anchor\test_step3_intersection_match.py -q`

Result: `68 passed in 26.50s`.

## Non-goals

This change does not infer a new RCSD junction for `613345278` and does not alter T03/T05 semantic matching thresholds.
