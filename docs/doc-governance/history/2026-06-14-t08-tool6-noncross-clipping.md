# 2026-06-14 T08 Tool6/Tool4 Non-Cross and Clipping Fix

## Context

This record covers the T10 audit around case `1885118` for `505230256` and `504230665`.

The business issue is that Tool6 did not identify two cross-like SWSD nodes as `kind_2=1` non-cross candidates. T01 therefore kept adjacent one-way segments split around these nodes, and downstream T06 had to consume fragmented Segment endpoints.

## Timeline

1. Raw T01 topology showed that `505230256` and `504230665` each have two outgoing angle groups with one in-leg and one out-leg per group, which is the intended non-cross pattern.
2. Initial Tool6 execution failed before reaching the targets because clipped road `524164705` referenced missing endpoint node `610668108`.
3. Source fix made Tool6 tolerate spatial-clipping endpoint loss by skipping roads whose endpoint node is absent and recording the skipped roads in summary output.
4. After clipping tolerance, Tool6 still missed the targets because `_angle_groups_are_parallel()` compared only the first leg of each angle group. For same-remote semantic return branches, the first leg is not necessarily the group axis.
5. Source fix changed Tool6 to compare a normalized vector sum for each angle group.
6. Tool6 then emitted `错误交叉路口_非交叉路口` for both `505230256` and `504230665`.
7. Tool4 had the same spatial-clipping endpoint failure and was updated to tolerate and report skipped clipped roads before consuming Tool6 QC output.
8. Tool4 repaired both target nodes to `kind_2=1`.
9. T01 was rerun with Tool4 repaired nodes and the current worktree source. Step6 completed with spatial-clipping missing-endpoint segments recorded as non-fatal errors.
10. T01 then merged the previously split target roads into complete segments across the repaired non-cross nodes.

## Business Logic Change

Tool6 now treats missing endpoint nodes caused by spatial clipping as recoverable input incompleteness. The affected road is excluded from local topology classification and reported in the module summary, instead of aborting the whole case.

Tool6 now evaluates whether two angle groups are parallel using the group axis vector, not the first incident leg. This keeps branch-return geometry from hiding a non-cross pattern.

Tool4 now applies the same spatial-clipping tolerance while consuming Tool6 QC output, so Tool6 repairs can be applied even when unrelated clipped roads have missing endpoints.

## Evidence

After the fix, Tool6 on case `1885118` reported:

- `topology_road_count=4012`
- `skipped_missing_node_road_count=133`
- `error_count_by_type`: `错误交叉路口_分歧路口=3`, `错误交叉路口_非交叉路口=31`

Target Tool6 results:

- `504230665`: `error_type=错误交叉路口_非交叉路口`, `reason=two_parallel_outward_angle_groups_each_has_in_and_out`, related roads `45455429,506371919,606370052`
- `505230256`: `error_type=错误交叉路口_非交叉路口`, `reason=two_parallel_outward_angle_groups_each_has_in_and_out`, related roads `504369942,508370936,527716405`

After Tool4 consumed Tool6 output:

- `504230665`: `kind_2=1`, `grade_2=1`
- `505230256`: `kind_2=1`, `grade_2=1`

After T01 consumed the repaired nodes:

- Formal T01 had `1878456_504230665` on road `45455429` and `1878458_504230665` on roads `506371919,606370052`.
- T01 after Tool4 repair has one segment `1878456_1878458` on roads `45455429,506371919,606370052`.
- Formal T01 had `1904815_505230256` on road `504369942` and `503230898_505230256` on roads `508370936,527716405`.
- T01 after Tool4 repair has one segment `1904815_503230898` on roads `504369942,508370936,527716405`.

Targeted tests passed:

- `tests/modules/t08_preprocess/test_tool6_nodes_type_qc.py`
- `tests/modules/t08_preprocess/test_tool4_junction_type_repair.py`

## Non-goals

This change does not alter T10 v1 orchestration. T08 remains an independent pre-processing and quality-repair module, and T10 consumes prepared external inputs.
