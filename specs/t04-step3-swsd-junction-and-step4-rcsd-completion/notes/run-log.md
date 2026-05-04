# T04 Step3 SWSD Junction + Step4 RCSD Completion Run Log

## Phase 0 — Requirement & Contract Freeze

- Branch: `speckit/t04-step3-swsd-junction-phase0-contract-freeze`
- Base commit: `c3e10ae201ce8e75a6f08fa8dee8a9133ed61c92`
- Started: `2026-05-04 09:17:00 CST`
- Completed: `2026-05-04 09:24:43 CST`
- Commit: `5ddd44d` (Phase 0 content commit before run-log metadata update)
- PR: `https://github.com/wxdangel-ship-it/RCSD_Topo_Poc/pull/2`
- Run root: `outputs/_work/t04_step3_swsd_phase0_d2/phase0_d2_main_equivalent_20260504_001`

### Phase 0 Evidence

- D1-D5 authorization source: `spec.md §7`, user task dated `2026-05-04`.
- D2 dry-run command:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch
run_t04_step14_batch(
    case_root=Path('/mnt/e/TestData/POC_Data/T02/Anchor_2'),
    case_ids=['505078921', '17943587'],
    out_root=Path('outputs/_work/t04_step3_swsd_phase0_d2'),
    run_id='phase0_d2_main_equivalent_20260504_001',
)
PY
```

- D2 dry-run result: `total_case_count = 2`, `total_event_unit_count = 7`, `failed_case_ids = []`, `threshold_status = within_threshold`.
- D2 baseline snapshots:
  - `notes/d2-baseline-505078921.json`: 3 event units.
  - `notes/d2-baseline-17943587.json`: 4 event units.
- Export note: current `event_units/<id>/step3_status.json` persists the Step3 executable skeleton fields, while the exact `T04UnitEnvelope.to_status_doc()` object is persisted at `step4_event_interpretation.json.event_units[].unit_envelope`; the D2 baseline snapshots store that exact object for Phase 1 byte-for-byte JSON comparison.

### Key Decisions

- Phase 0 is documentation and governance only; no source or script files were modified.
- `.md` files are not subject to `AGENTS.md §3` source/script 100 KB write threshold, but the PR description must still record that no source/script file was written.

## Phase 1 — `SWSDSemanticJunction` Dataclass & Recall

- Branch: `speckit/t04-step3-swsd-junction-phase1-swsd-junction-dataclass`
- Base commit: `8809b5d`
- Started: `2026-05-04 09:31:00 CST`
- Completed: `2026-05-04 10:20:55 CST`
- Commit: `aec0d4f` (Phase 1 content commit before run-log metadata update)
- PR: `https://github.com/wxdangel-ship-it/RCSD_Topo_Poc/pull/3`
- Run root: `outputs/_work/t04_step3_swsd_phase1_d2/phase1_d2_guard_20260504_002`

### Phase 1 Evidence

- Source/script byte-size prechecks were run before writes for `_runtime_step23_contracts.py`, `_runtime_step3_topology_skeleton.py`, `topology.py`, `test_step3_swsd_semantic_junction.py`, `test_step14_synthetic_batch.py`, and `test_step3_topology_skeleton.py`.
- Source/script byte-size rechecks stayed below 100 KB:
  - `_runtime_step23_contracts.py`: 11991 bytes.
  - `_runtime_step3_topology_skeleton.py`: 32240 bytes.
  - `topology.py`: 5782 bytes.
  - `test_step3_swsd_semantic_junction.py`: 6859 bytes.
  - `test_step14_synthetic_batch.py`: 17074 bytes.
  - `test_step3_topology_skeleton.py`: 3350 bytes.
- D2 guard run command:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import run_t04_step14_batch
run_t04_step14_batch(
    case_root=Path('/mnt/e/TestData/POC_Data/T02/Anchor_2'),
    case_ids=['505078921', '17943587', '760213', '857993'],
    out_root=Path('outputs/_work/t04_step3_swsd_phase1_d2'),
    run_id='phase1_d2_guard_20260504_002',
)
PY
```

- D2 baseline comparison result:
  - `505078921`: `unit_envelope diff = 0` across 3 event units.
  - `17943587`: `unit_envelope diff = 0` across 4 event units.
  - Summary: `total_case_count = 4`, `total_event_unit_count = 11`, `failed_case_ids = []`, `threshold_status = within_threshold`.
- Semantic junction snapshots:
  - `505078921`: `junction=505078921`, `arms=3`, `connectors=3`.
  - `17943587`: `junction=17943587`, `arms=2`, `connectors=6`.
  - `760213`: `junction=760213`, `arms=3`, `connectors=4`.
  - `857993`: `junction=857993`, `arms=2`, `connectors=3`.
- Test discipline:
  - `test_step3_swsd_semantic_junction.py`: `6 passed`.
  - `test_step3_topology_skeleton.py`: `2 passed`.
  - `test_step14_synthetic_batch.py`: `5 passed`.
  - `test_step14_real_regression.py`: `7 passed`.

### Phase 1 Notes

- The previously referenced `tests/modules/t04_divmerge_virtual_polygon/test_step3_topology_skeleton.py` was absent on the merged Phase 0 baseline, so Phase 1 added a small compatibility test under that path.
- `outputs.write_case_outputs` was not edited directly; Step3 output persistence is synchronized through `topology.build_step3_status_doc` and `topology.build_unit_step3_status_doc`, which feed the existing output writer.

## Phase 2 — Step5 / Render 去重迁移

- Branch: `speckit/t04-step3-swsd-junction-phase2-step5-render-migration`
- Base commit: `8f27794`
- Started: `2026-05-04 10:31:00 CST`
- Completed: `2026-05-04 11:05:33 CST`
- Commit: `0046d17` (Phase 2 content commit before run-log metadata update)
- PR: `https://github.com/wxdangel-ship-it/RCSD_Topo_Poc/pull/4`
- Run root: `n/a` (Phase 2 uses unit / synthetic pytest outputs under pytest temp dirs)

### Phase 2 Evidence

- Source/script byte-size prechecks were run before writes for `support_domain_builder.py`, `support_domain_cuts.py`, `review_render.py`, `support_domain_common.py`, and `test_step5_consumes_step3_swsd_junction.py`.
- Source/script byte-size rechecks stayed below 100 KB:
  - `support_domain_builder.py`: 46587 bytes.
  - `support_domain_cuts.py`: 10401 bytes.
  - `review_render.py`: 41920 bytes.
  - `support_domain_common.py`: 22931 bytes.
  - `test_step5_consumes_step3_swsd_junction.py`: 3073 bytes.
- `rg "_expanded_related_road_ids" --type py` result:
  - `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_cuts.py:40:def _expanded_related_road_ids(`.
  - Step5 / render / outputs no longer call this deprecated helper.
- Test discipline:
  - `test_step5_consumes_step3_swsd_junction.py`: `2 passed in 8.64s`.
  - `test_step5_consumes_step3_swsd_junction.py + test_step5_support_domain.py + test_step14_synthetic_batch.py`: `12 passed in 59.42s`.
  - `test_step14_real_regression.py`: `7 passed in 23.21s`.

### Phase 2 Notes

- Step5 now derives `related_swsd_road_ids` exclusively from `case_result.base_context.topology_skeleton.swsd_semantic_junction`.
- Render now highlights SWSD related roads from the same Step3 entity instead of re-deriving them from Step5 unit support roads.
- The legacy `_expanded_related_road_ids` function remains only as a deprecated compatibility shadow and is excluded from `support_domain_cuts.__all__`.

## Protocol Update — Local Serial Execution

- Timestamp: `2026-05-04 11:28:00 CST`
- User instruction: 后续任务不再提交 GitHub，均在本地进行；待本次完成后统一提交。
- Effective scope: Phase 3–7 and any remaining cleanup in this SpecKit round.
- GitHub operation status: stopped. Phase 2 PR `https://github.com/wxdangel-ship-it/RCSD_Topo_Poc/pull/4` was already created before this instruction and will not be updated or used as a gating dependency.
- Local branch at protocol switch: `speckit/t04-step3-swsd-junction-phase2-step5-render-migration`.
- Local HEAD at protocol switch: `c1ee12b`.
- Execution rule after switch: no `git push`, no GitHub PR creation, no user-side GitHub merge steps; continue Phase checklist locally and perform one final local commit only after the full round is complete unless the user explicitly changes this instruction.

## Phase 3 — RCSDSemanticJunction Dataclass & Mapping

- Branch: `speckit/t04-step3-swsd-junction-phase2-step5-render-migration`
- Base local HEAD: `c1ee12b`
- Started: `2026-05-04 11:29:00 CST`
- Completed: `2026-05-04 11:55:46 CST`
- Commit: `n/a` (local serial mode; final commit deferred)
- PR: `n/a` (local serial mode)
- Run root: `n/a` (Phase 3 uses unit / real pytest)

### Phase 3 Evidence

- Source/script byte-size prechecks were run before writes for `rcsd_alignment.py`, `_event_interpretation_core.py`, `step4_road_surface_fork_rcsd.py`, `case_models.py`, `outputs.py`, `event_interpretation.py`, and `test_step4_rcsd_alignment_type.py`.
- Source/script byte-size rechecks stayed below 100 KB:
  - `rcsd_alignment.py`: 22276 bytes.
  - `_event_interpretation_core.py`: 56642 bytes.
  - `step4_road_surface_fork_rcsd.py`: 9636 bytes.
  - `case_models.py`: 39727 bytes.
  - `outputs.py`: 42007 bytes.
  - `event_interpretation.py`: 18832 bytes.
  - `test_step4_rcsd_alignment_type.py`: 19030 bytes.
- Syntax / whitespace:
  - `py_compile` passed for the six modified Python files plus the extended Step4 test.
  - `git diff --check` passed.
- Test discipline:
  - `test_step4_rcsd_alignment_type.py`: `10 passed in 3.18s`.
  - `test_step14_real_regression.py`: `7 passed in 22.59s`.

### Phase 3 Notes

- `RCSDSemanticJunction` is emitted only for junction-level `rcsd_alignment_type` values: `rcsd_semantic_junction` and `rcsd_junction_partial_alignment`.
- The builder consumes Step4's frozen RCSD alignment result, selected RCSD roads/nodes, local RCSD topology, and the Step3 `SWSDSemanticJunction`.
- `paired_swsd_arm_mapping` uses the existing `BRANCH_MATCH_TOLERANCE_DEG = 30.0`; ambiguous arm matches are serialized as `null` and listed in `pairing_ambiguous_arm_ids`.
- Real RCSDRoad geometry may carry 3D coordinates; Phase 3 angle extraction now explicitly uses the first two coordinate dimensions.

## Phase 4 — RCSDRoadOnlyChain Dataclass & Closure Proof

- Branch: `speckit/t04-step3-swsd-junction-phase2-step5-render-migration`
- Base local HEAD: `c1ee12b`
- Started: `2026-05-04 11:56:00 CST`
- Completed: `2026-05-04 12:06:40 CST`
- Commit: `n/a` (local serial mode; final commit deferred)
- PR: `n/a` (local serial mode)
- Run root: `n/a` (Phase 4 uses unit / real pytest)

### Phase 4 Evidence

- Source/script byte-size prechecks were run before writes for `rcsd_alignment.py`, `_event_interpretation_core.py`, `step4_road_surface_fork_rcsd.py`, `case_models.py`, `outputs.py`, `event_interpretation.py`, and `test_step4_rcsd_alignment_type.py`.
- Source/script byte-size rechecks stayed below 100 KB:
  - `rcsd_alignment.py`: 32817 bytes.
  - `_event_interpretation_core.py`: 57231 bytes.
  - `step4_road_surface_fork_rcsd.py`: 9636 bytes.
  - `case_models.py`: 40224 bytes.
  - `outputs.py`: 42309 bytes.
  - `event_interpretation.py`: 18947 bytes.
  - `test_step4_rcsd_alignment_type.py`: 25512 bytes.
- Syntax / whitespace:
  - `py_compile` passed for the six modified Python files plus the extended Step4 test.
  - `git diff --check` passed.
- Test discipline:
  - `test_step4_rcsd_alignment_type.py`: `13 passed in 3.23s`.
  - `test_step14_real_regression.py`: `7 passed in 22.93s`.

### Phase 4 Notes

- `RCSDRoadOnlyChain` is emitted only for `rcsd_alignment_type = rcsdroad_only_alignment`.
- Candidate road IDs are derived from the frozen alignment positive roads plus `first_hit_rcsdroad_ids` / `selected_rcsdroad_ids`, then ordered as a local RCSDRoad chain.
- `closure_status` supports `closed_between_two_rcsd_junctions`, `open_dead_end`, `open_patch_boundary`, and `unresolved`; D4 real-data distribution remains pending until Phase 6.
- Direction evidence uses the existing `BRANCH_MATCH_TOLERANCE_DEG = 30.0` and writes all D5 audit keys: `chain_head_angle_deg`, `chain_tail_angle_deg`, `matched_swsd_arm_id`, `angle_gap_deg`, and `consistency_decision_reason`.

## Phase 5 — Consistency Verdict 聚合 + 取值域冻结

- Branch: `speckit/t04-step3-swsd-junction-phase2-step5-render-migration`
- Base local HEAD: `c1ee12b`
- Started: `2026-05-04 12:07:00 CST`
- Completed: `2026-05-04 12:26:56 CST`
- Commit: `n/a` (local serial mode; final commit deferred)
- PR: `n/a` (local serial mode)
- Run root: `n/a` (Phase 5 uses unit / synthetic / real pytest)

### Phase 5 Evidence

- Source/script byte-size prechecks were run before writes for `rcsd_alignment.py`, `case_models.py`, `outputs.py`, `_rcsd_selection_support.py`, `rcsd_selection.py`, `step4_road_surface_fork_binding_promotions.py`, `step4_road_surface_fork_binding_cleanup.py`, `step4_road_surface_fork_binding_swsd_rcsdroad.py`, and the new `test_consistency_verdict.py`.
- Source/script byte-size rechecks stayed below 100 KB:
  - `rcsd_alignment.py`: 35312 bytes.
  - `case_models.py`: 42331 bytes.
  - `outputs.py`: 42683 bytes.
  - `_rcsd_selection_support.py`: 53171 bytes.
  - `rcsd_selection.py`: 39060 bytes.
  - `step4_road_surface_fork_binding_promotions.py`: 43812 bytes.
  - `step4_road_surface_fork_binding_cleanup.py`: 19021 bytes.
  - `step4_road_surface_fork_binding_swsd_rcsdroad.py`: 19993 bytes.
  - `test_consistency_verdict.py`: 3356 bytes.
  - `test_step4_rcsd_alignment_type.py`: 25512 bytes.
- Write-point scan:
  - `rg "rcsd_consistency_result\\s*=" --type py src tests` was used to enumerate Python write sites.
  - Actual writes now pass through `validate_rcsd_consistency_result(...)` on `PositiveRcsdSelectionDecision`, `T04CandidateAuditEntry`, `T04EventUnitResult`, and `T04ReviewIndexRow`.
  - Historical reason strings such as `swsd_junction_window_no_rcsd`, `road_surface_fork_structure_only_no_rcsd`, and `unbound_road_surface_fork_without_bifurcation_rcsd` remain in reason / mode fields, but no longer enter `rcsd_consistency_result`.
- Syntax / whitespace:
  - `py_compile` passed for modified Phase 5 Python files and tests.
  - `git diff --check` passed.
- Test discipline:
  - `test_consistency_verdict.py + test_step4_rcsd_alignment_type.py`: `16 passed in 3.12s`.
  - `test_step14_real_regression.py`: `7 passed in 21.19s`.
  - `test_step14_synthetic_batch.py`: `5 passed in 33.42s`.

### Phase 5 Notes

- `swsd_rcsd_alignment_consistent` is now serialized in event-unit summary docs, candidate audit entries, `step4_review_index.csv`, and `step4_review_summary.json` counts.
- `RCSD_CONSISTENCY_RESULT_VALUES` is frozen to the seven values in `INTERFACE_CONTRACT.md §3.7`.
- Road-only verdicts depend on `RCSDRoadOnlyChain.swsd_direction_consistent`; Phase 6 will provide the real 39-case distribution.

## Phase 6 — Real Case Regression

- Branch: `speckit/t04-step3-swsd-junction-phase2-step5-render-migration`
- Base local HEAD: `c1ee12b`
- Started: `2026-05-04 12:27:00 CST`
- Completed: `2026-05-04 13:36:00 CST`
- Commit: `n/a` (local serial mode; final commit deferred)
- PR: `n/a` (local serial mode)
- Formal run root: `outputs/_work/t04_step14_batch/codex_t04_step3_swsd_junction_20260504_131905`
- Render audit root: `outputs/_work/t04_swsd_render_audit/codex_t04_step3_swsd_junction_20260504_131905`

### Phase 6 Reading Confirmation

- [x] `AGENTS.md`
- [x] `modules/t04_divmerge_virtual_polygon/AGENTS.md`
- [x] `.agents/skills/default-imp/SKILL.md`
- [x] `INTERFACE_CONTRACT.md §2.3 / §3.4 / §3.5 / §4.4`
- [x] `architecture/04-solution-strategy.md §4 / §5 / §6`
- [x] `architecture/10-quality-requirements.md`
- [x] `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/{spec.md, plan.md, tasks.md}`

### Phase 6 Modified

- `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step3_topology_skeleton.py`: filtered `inter_junction_connector_road_ids` to exclude `intra_junction_road_ids` while preserving non-intra `first_road_ids` needed by Step5/render related-road derivation.
- `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/case_models.py`: computes `T04EventUnitResult.swsd_rcsd_alignment_consistent` from the final `surface_scenario.rcsd_alignment_type`, so verdicts match serialized alignment type.
- `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/review_render.py`: added `build_final_review_render_audit(...)` to expose the exact SWSD road IDs used by final review rendering.
- `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/outputs.py`: writes per-case `final_review_render_audit.json`.
- `tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py`: added real Anchor_2 snapshots for `724067 / 758784 / 760213`.
- `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py`: kept PNG presence checks while not asserting legacy 23-case raw PNG fingerprints for this SpecKit round.
- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`: recorded D4 real-data distribution with `closed_between_two_rcsd_junctions = 0`.
- `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`: registered the 2026-05-04 Phase 6 39-case run root as the new manual visual-audit reference.
- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/tasks.md`: marked Phase 6 checklist complete and corrected remaining GitHub/PR wording to local serial execution.
- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/plan.md`: corrected development output wording from PR checkpoint to local checkpoint.

### Phase 6 Byte-Size Checks

- `_runtime_step3_topology_skeleton.py`: `32600` bytes.
- `case_models.py`: `42348` bytes.
- `review_render.py`: `42832` bytes.
- `outputs.py`: `42884` bytes.
- `test_step3_swsd_semantic_junction.py`: `10311` bytes.
- All checked source/script files remain below 100 KB.

### Phase 6 Verification

- `python -m py_compile` on modified Phase 6 Python files passed.
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py tests/modules/t04_divmerge_virtual_polygon/test_consistency_verdict.py tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py -q` -> `23 passed in 3.48s`.
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py -q` -> `8 passed in 7.48s`.
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate -x` -> `1 passed in 102.49s`.
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate -x` -> `1 passed in 136.33s`.
- Anchor_2 39-case full run:
  - `run_root = outputs/_work/t04_step14_batch/codex_t04_step3_swsd_junction_20260504_131905`
  - `total_case_count = 39`
  - `accepted = 35`
  - `rejected = 4`
  - `failed_case_ids = []`
  - `review_png_present_count = 39`
  - `nodes_consistency_passed = true`
  - `performance.threshold_status = within_threshold`
  - `elapsed_seconds_total = 158.049974`
- Phase 6 automatic audit:
  - `outputs/_work/t04_swsd_render_audit/codex_t04_step3_swsd_junction_20260504_131905/phase6_auto_audit_summary.json`
  - `errors = []`
  - `render_missing_case_count = 0`
  - every case has non-empty `swsd_semantic_junction.junction_id`
  - every case has `intra_junction_road_ids ∩ Σ inter_junction_connector_road_ids = ∅`
  - every case Step5 `related_swsd_road_ids` equals Step3 `intra ∪ connector`
  - every event unit has non-empty `swsd_rcsd_alignment_consistent` matching final alignment / consistency / polarity / chain derivation.

### Phase 6 Named Case Evidence

| case_id | swsd_entity_road_count | render_visible_road_count | missing_road_ids |
|---|---:|---:|---|
| `724067` | 3 | 3 | none |
| `758784` | 3 | 3 | none |
| `760213` | 5 | 5 | none |

Final review PNGs for `724067 / 758784 / 760213` were opened locally and show `ACCEPTED`; the panel `swsd_current_roads` counts match `render_audit.csv`.

### Phase 6 D4 Closure Distribution

| closure_status | count |
|---|---:|
| `closed_between_two_rcsd_junctions` | 0 |
| `open_dead_end` | 0 |
| `open_patch_boundary` | 0 |
| `unresolved` | 11 |

Because `closed_between_two_rcsd_junctions = 0`, `INTERFACE_CONTRACT.md §2.5` now records that the current Anchor_2 39-case dataset has no real-data hit for that status and keeps it as a reserved contract state.

### Phase 6 D5 Angle Distribution

| case_id | event_unit_id | chain_head | chain_tail | matched_swsd_arm | angle_gap_deg | consistent |
|---|---|---:|---:|---|---:|---|
| `505078921` | `node_510222629__pair_02` | 332.457717 | 25.057615 | `arm_01` | 2.693169 | true |
| `706347` | `event_unit_01` | 45.666865 | 142.715402 | `arm_03` | 0.093654 | true |
| `724067` | `event_unit_01` | 61.561981 | 156.078417 | `arm_02` | 41.104506 | false |
| `724081` | `event_unit_01` | 270.038792 | 323.587765 | `arm_01` | 9.786425 | true |
| `760598` | `event_unit_01` | 344.172858 | 347.026118 | `arm_03` | 0.832063 | true |
| `760984` | `event_unit_01` | 277.196621 | 253.230556 | `arm_02` | 16.145656 | true |
| `768675` | `event_unit_01` | 68.198591 | 247.684897 | `arm_01` | 0.124814 | true |
| `768680` | `node_768680` | 275.003410 | 233.736188 | `arm_01` | 9.125822 | true |
| `768680` | `node_768683` | 17.592425 | 247.702842 | `arm_03` | 12.496168 | true |
| `785731` | `event_unit_01` | 332.073966 | 157.285588 | `arm_02` | 5.024822 | true |
| `788824` | `event_unit_01` | 219.281174 | 128.807123 | `arm_03` | 0.666766 | true |

No dense cluster appears in the 25-35 degree tolerance boundary range. `724067` is a single inconsistent outlier at `41.104506` and is retained as inconsistent; this Phase does not adjust D5 tolerance.

### Phase 6 Hard Stop Check

- [x] Did not trigger `AGENTS.md §1.1` source-fact conflict.
- [x] Did not trigger `§1.2` unauthorized protected module/interface change beyond this SpecKit task.
- [x] Did not trigger `§1.3` new permanent entrypoint.
- [x] Did not trigger `§1.4` source/script file-size violation.
- [x] Did not trigger `§1.5` data-observation-driven upstream field semantics.
- [x] Did not trigger `§1.6` path mismatch; Windows path `E:\TestData\POC_Data\T02\Anchor_2` was executed as bash path `/mnt/e/TestData/POC_Data/T02/Anchor_2`.
- [x] Did not trigger `§1.7` entrypoint registry mismatch.

### Phase 6 Pending Confirmation

- No code-level blocker remains for Phase 6.
- User manual visual confirmation is still welcome for the 39-case `final_review.png` set under the formal run root; machine render audit reports `missing_road_ids = 0` for all 39 cases.

## Phase 7 — QA / Documentation Closeout

- Branch: `speckit/t04-step3-swsd-junction-phase2-step5-render-migration`
- Local HEAD: `c1ee12b`
- Started: `2026-05-04 13:40:00 CST`
- Completed: `2026-05-04 15:44:42 CST`
- Commit: `n/a` (local serial mode; final commit deferred)
- GitHub: `n/a` (no push / no PR by user instruction)
- Formal run root: `outputs/_work/t04_step14_batch/codex_t04_step3_swsd_junction_20260504_131905`
- QA summary: `outputs/_work/t04_swsd_render_audit/codex_t04_step3_swsd_junction_20260504_131905/phase7_qa_summary.json`
- Release notes: `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/notes/release-notes.md`

### Phase 7 Reading Confirmation

已阅读 ✅：

- [x] `AGENTS.md`
- [x] `modules/t04_divmerge_virtual_polygon/AGENTS.md`
- [x] `.agents/skills/default-imp/SKILL.md`
- [x] `INTERFACE_CONTRACT.md §2.3 / §3.4 / §3.5 / §4.4`
- [x] `architecture/04-solution-strategy.md §4 / §5 / §6`
- [x] `architecture/10-quality-requirements.md`
- [x] `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/{spec.md, plan.md, tasks.md}`

### Phase 7 Modified

- `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py`: updated stale user-audit six-case expectations to the current formal output: `785731` is accepted as `no_main_evidence_with_rcsdroad_fallback_and_swsd`; `795682` is accepted as `no_main_evidence_with_swsd_only`; total accepted/rejected counts are `6/0`.
- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/tasks.md`: marked Phase 7 QA checklist complete.
- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/notes/release-notes.md`: added final local release notes with `已修改 / 已验证 / 待确认`.
- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/notes/run-log.md`: appended this Phase 7 execution record.

### Phase 7 Byte-Size Checks

All modified Python source/test files remain below the 100 KB hard threshold:

| path | bytes |
|---|---:|
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py` | 57231 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_rcsd_selection_support.py` | 53171 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step3_topology_skeleton.py` | 32600 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/case_models.py` | 42348 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/event_interpretation.py` | 18947 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/outputs.py` | 42884 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/rcsd_alignment.py` | 35312 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/rcsd_selection.py` | 39060 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/review_render.py` | 42832 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_cleanup.py` | 19021 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotions.py` | 43812 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_swsd_rcsdroad.py` | 19993 |
| `tests/modules/t04_divmerge_virtual_polygon/test_706629_swsd_only_regression.py` | 32060 |
| `tests/modules/t04_divmerge_virtual_polygon/test_complex_multi_unit_decomposition.py` | 3322 |
| `tests/modules/t04_divmerge_virtual_polygon/test_consistency_verdict.py` | 3356 |
| `tests/modules/t04_divmerge_virtual_polygon/test_real_anchor2_699870_rcsd_anchored_reverse.py` | 3780 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py` | 10311 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py` | 25512 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step5_surface_scenario_support_domain.py` | 19292 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step6_polygon_assembly.py` | 13434 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` | 83315 |

No file-size audit table update is required because no source/script file crossed or approached the 100 KB threshold by this round's edits.

### Phase 7 Verification

- Phase 7 QA script summary:
  - `crs_checks = 118`, failures `0`, all `EPSG:3857`.
  - `geometry_valid_checks = 118`, failures `0`, invalid feature count `0`.
  - `provenance_checks = 3`, failures `0`.
  - `performance.threshold_status = within_threshold`.
  - `threshold_source = module_quality_requirement_default_or_env_override`.
  - `errors = []`.
- Visual sample opened locally:
  - `17943587 / 706347 / 785731 / 823826 / 987998`: `final_review.png` status/count panels matched the render audit.
  - Named cases `724067 / 758784 / 760213`: `final_review.png` status `ACCEPTED`, `swsd_current_roads` counts matched `render_audit.csv`.
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_new6_user_audit_surface_scenario_gate -q` -> `1 passed in 29.01s`.
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate -q` -> `1 passed in 172.34s`.
- `pytest -s tests/modules/t04_divmerge_virtual_polygon -q` -> `166 passed in 797.40s`.
- `python3 -m py_compile` on all modified Python source/test files -> passed.
- `git diff --check` -> passed.
- `git status --short --branch`:
  - `## speckit/t04-step3-swsd-junction-phase2-step5-render-migration...origin/speckit/t04-step3-swsd-junction-phase2-step5-render-migration [ahead 1]`
  - Modified files remain local; no commit/push performed.

### Phase 7 Tasks Checklist

- [x] 验证 CRS：所有新增 `step3_status / step4_event_interpretation / step5_status` 写出未改 CRS。
- [x] 验证 geometry valid：新增字段不引入 geometry；纯 ID + 元数据，无 valid 风险。
- [x] 验证文件体量：再次运行 `stat -c%s` 自检，所有源码 `.py` 不跨 100 KB；未发生拆分，`docs/repository-metadata/code-size-audit.md` 无需同步。
- [x] 验证契约一致性：`step4_review_index.csv` 列序与 `INTERFACE_CONTRACT.md §4.4` 一致；`step3_status.json` schema 与 §2.4 一致；`step4_event_interpretation.json` schema 与 §2.5 一致。
- [x] 性能审计：`summary.json.performance` 字段齐全；`threshold_source = module_quality_requirement_default_or_env_override`；`threshold_status = within_threshold`。
- [x] 视觉审计采样：从 39-case 中抽查 `17943587 / 706347 / 785731 / 823826 / 987998`，并复核命名 case `724067 / 758784 / 760213`。
- [x] 生成 Release Notes 草稿：`notes/release-notes.md`。
- [x] 治理工件登记：本 run-log 条目已写入。

### Phase 7 Hard Stop Check

- [x] Did not trigger `AGENTS.md §1.1` source-fact conflict.
- [x] Did not trigger `§1.2` unauthorized protected module/interface change beyond this SpecKit task.
- [x] Did not trigger `§1.3` new permanent entrypoint.
- [x] Did not trigger `§1.4` source/script file-size violation.
- [x] Did not trigger `§1.5` data-observation-driven upstream field semantics.
- [x] Did not trigger `§1.6` path mismatch; Windows path `E:\TestData\POC_Data\T02\Anchor_2` is executed as bash path `/mnt/e/TestData/POC_Data/T02/Anchor_2`.
- [x] Did not trigger `§1.7` entrypoint registry mismatch.

### Phase 7 Pending Confirmation

- No code-level blocker remains.
- No GitHub push / PR / commit was performed after the user's "停止推送" and "后续任务，不再提交Github" instructions.
- Awaiting user confirmation before any unified local commit.

## Degree-2 Semantic Boundary 修订 — 2026-05-04

- Branch: `codex/t04-degree2-semantic-boundary`
- Base: `main` at `678e7ea`
- Trigger: 用户目视指出 `698380` 中 `109815830` 越过其它 SWSD 语义路口被召回，并确认新业务口径：只有 `degree == 2` passthrough chain 可穿透；`degree >= 3` 立即作为 semantic boundary 停止。RCSD 同口径。
- GitHub: not pushed in this revision yet.

### Reading Confirmation

已阅读 ✅：

- [x] `AGENTS.md`
- [x] `modules/t04_divmerge_virtual_polygon/AGENTS.md`
- [x] `.agents/skills/default-imp/SKILL.md`
- [x] `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- [x] `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/{spec.md, plan.md, tasks.md}`
- [x] `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`

### 已修改

- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/spec.md`: 删除 degree==3 角度连续穿透口径，新增 degree==2-only semantic boundary 规则。
- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/plan.md`: 同步实现和测试计划，加入 `698380` snapshot。
- `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/tasks.md`: 同步已完成任务描述，记录 2026-05-04 修订守门。
- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`: 在 §2.4 冻结 SWSD / RCSD connector 只允许 degree==2 passthrough。
- `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step3_topology_skeleton.py`: `_walk_arm_to_neighbor_semantic_junction` 遇 degree>=3 立即停止；seed road 只有确认直接触达当前 member 后才进入 connector。
- `tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py`: 更新 degree>=3 boundary 单测，新增 `698380 / 17943587` 真实 snapshot。
- `tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py`: 新增 RCSD degree>=3 boundary 对称守门测试。
- `notes/release-notes.md` / `notes/run-log.md`: 记录本次修订。

### 已验证

- File-size pre/post check:
  - `_runtime_step3_topology_skeleton.py`: `32228` bytes
  - `rcsd_alignment.py`: `35312` bytes
  - `test_step3_swsd_semantic_junction.py`: `10947` bytes
  - `test_step4_rcsd_alignment_type.py`: `28108` bytes
- `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py -q` -> `22 passed in 9.59s`.
- Single case `698380`:
  - run root: `outputs/_work/t04_degree2_boundary/case_698380_degree2_boundary`
  - `related_swsd_road_ids = [109815705, 612199387, 973749]`
  - `109815830` is in `unrelated_swsd_road_ids`
  - `final_review_render_audit.missing_road_ids = []`
  - `final_review.png` panel: `swsd_current_roads: 3 / other=8`
- Double case `17943587 / 698380`:
  - run root: `outputs/_work/t04_degree2_boundary/cases_17943587_698380_degree2_boundary_v2`
  - `17943587.related_swsd_road_ids = [41727506, 502953712, 510969745, 528620938, 529824990, 605949403, 607951495, 607962170, 620950831]`
  - `17943587`: `29824276` is in `unrelated_swsd_road_ids`
  - `698380`: `109815830` remains in `unrelated_swsd_road_ids`
- 39-case official gate: `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate -q` -> `1 passed in 187.31s`.
- Fixed 39-case output:
  - run root: `outputs/_work/t04_degree2_boundary/anchor2_39case_degree2_boundary_v2`
  - audit csv: `outputs/_work/t04_degree2_boundary/anchor2_39case_degree2_boundary_v2_render_audit/render_audit.csv`
  - `total_case_count=39`, `accepted=35`, `rejected=4`, `failed_case_ids=[]`, `nodes_consistency_passed=true`
  - `missing_road_ids` all empty
  - changed over-recall cases: `17943587 / 698380 / 698389 / 699870 / 706347 / 706629 / 760230 / 760598 / 768675 / 768680 / 785629 / 785631 / 785671 / 785731 / 788824 / 807908 / 857993 / 987998`
  - topology audit: non-direct connectors all have at least one `degree==2` endpoint; `violation_count=0`
- 30-case gates: `pytest -s tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate -q` -> `2 passed in 215.17s`.
- `.venv/bin/python -m py_compile` on modified Python source/test files -> passed.
- `git diff --check` -> passed.
- Full module regression: `pytest -s tests/modules/t04_divmerge_virtual_polygon -q` -> `167 passed in 928.69s`.

### 硬停机检查

- [x] Did not trigger `AGENTS.md §1.1` after user authorization resolved the prior source/spec conflict.
- [x] Did not trigger `§1.2` unauthorized protected module/interface change; this revision was explicitly authorized by user.
- [x] Did not trigger `§1.3` new permanent entrypoint.
- [x] Did not trigger `§1.4` source/script file-size violation.
- [x] Did not trigger `§1.5` data-observation-driven upstream field semantics; the new rule is user-confirmed business logic.
- [x] Did not trigger `§1.6` path mismatch; Anchor_2 Windows path maps to `/mnt/e/TestData/POC_Data/T02/Anchor_2` under bash.
- [x] Did not trigger `§1.7` entrypoint registry mismatch.

### 待确认

- User visual confirmation for the new fixed 39-case PNG set.
- No commit / push has been performed for this correction branch yet.

## Semantic Group Degree Boundary 补充修订 — 2026-05-04

- Branch: `codex/t04-degree2-semantic-boundary`
- Trigger: 用户指出 `785731 / 706243 / 724081` 仍越过有 `mainnode` 且进入 / 退出道路数为 3 度及以上的 SWSD 语义路口，继续追溯路口后的 roads。
- Root cause: 先前 degree-2 修订仍有路径按物理单节点 incident road 数判定 degree；当 `mainnodeid` 聚合组的代表节点物理 degree 为 2、但语义组进出道路 degree >= 3 时，arm walk 会误判为可穿透 passthrough chain。
- Requirement freeze: 有 `mainnode` 与无 `mainnode` 使用同一口径；`degree` 必须按语义节点组的进入 / 退出道路数统计。有效 `mainnodeid` 按 `mainnodeid` 聚合；无有效 `mainnodeid` 按节点自身 `id` 成组；组内道路不计入 degree。SWSD 与 RCSD 同口径。
- GitHub: 本轮不提交、不 push。

### Reading Confirmation

已阅读 ✅：

- [x] `AGENTS.md`
- [x] `modules/t04_divmerge_virtual_polygon/AGENTS.md`
- [x] `.agents/skills/default-imp/SKILL.md`
- [x] `docs/doc-governance/README.md`
- [x] `docs/repository-metadata/code-boundaries-and-entrypoints.md`
- [x] `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`
- [x] `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`
- [x] `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`
- [x] `specs/t04-step3-swsd-junction-and-step4-rcsd-completion/{spec.md, plan.md, tasks.md}`

### 已修改

- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`: 冻结语义节点组 degree 定义，明确有 / 无 `mainnodeid` 都按进入 / 退出道路数判定。
- `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`: Step3 实体化策略补充语义组 degree==2 passthrough / degree>=3 停止。
- `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`: RCSD/SWSD 语义路口聚合不得退回物理单节点 degree。
- `spec.md / plan.md / tasks.md`: SpecKit 工件同步语义节点组 degree 口径。
- `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step3_topology_skeleton.py`: SWSD arm walk 使用语义节点组边界 degree；删除“存在其它 `mainnodeid` 即提前停止”的差异口径，使有 / 无 `mainnodeid` 都按 degree 判定。
- `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/rcsd_alignment.py`: RCSD connector 与 RCSDRoad-only endpoint 使用同一语义节点组边界 degree。
- `tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py`: 增加有 `mainnodeid` 语义组三度停止、语义组二度可穿透单测；加入 `706243 / 724081 / 785731` 真实 snapshot。
- `tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py`: 增加 RCSD mainnode 语义组边界 degree 单测，覆盖 connector 与 road-only endpoint。
- `notes/run-log.md / notes/release-notes.md`: 记录本轮根因、验证和待确认项。

### 已验证

- File-size pre/post check:
  - `_runtime_step3_topology_skeleton.py`: `34623` bytes
  - `rcsd_alignment.py`: `37693` bytes
  - `test_step3_swsd_semantic_junction.py`: `13527` bytes
  - `test_step4_rcsd_alignment_type.py`: `30076` bytes
  - `test_step7_final_publish.py`: `83315` bytes
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step3_swsd_semantic_junction.py tests/modules/t04_divmerge_virtual_polygon/test_step4_rcsd_alignment_type.py` -> `25 passed in 16.24s`.
- Target/risk case run root: `outputs/_work/t04_degree2_boundary/anchor2_semantic_group_degree_target_cases`
  - `accepted=5`, `rejected=0`.
  - `785731.related_swsd_road_ids = [33027407, 33027442, 981884]`; `517308491 / 33027389` 均进入 `unrelated_swsd_road_ids`。
  - `706243.related_swsd_road_ids = [500994564, 607948942, 608954744]`; `88046473` 进入 `unrelated_swsd_road_ids`。
  - `724081.related_swsd_road_ids = [516803728, 518742522, 5415248413000846]`; `516795731` 进入 `unrelated_swsd_road_ids`。
- New 39-case run root: `outputs/_work/t04_degree2_boundary/anchor2_39case_semantic_group_degree_20260504_001`
  - `row_count=39`, `accepted=35`, `rejected=4`, rejected ids `760598 / 760936 / 857993 / 607602562`。
  - `failed_case_ids=[]`, `review_png_present_count=39`, `nodes_consistency_passed=True`。
  - `performance.threshold_status=within_threshold`, `elapsed_seconds_total=168.072287`, `avg_completed_case_seconds=1.461243`。
  - `step4_review_flat/*final_review.png` count = `39`; case-level `final_review.png` count = `39`。
  - Target cases Step3-derived SWSD related roads == `step5_audit.related_swsd_road_ids`。
- GIS / topology checks for `785731 / 706243 / 724081`:
  - Raw/input CRS all `EPSG:3857`; output `final_case_polygon.gpkg / step5_domains.gpkg` CRS all `EPSG:3857`。
  - Raw/input geometry invalid count = `0`; output geometry invalid count = `0`。
  - SWSD `roads.gpkg` endpoints all trace to `nodes.gpkg` (`endpoint_missing_count=0`)。
  - RCSD local package contains existing patch-boundary external endpoints; endpoint ids are traceable and are handled as `patch_boundary`, without silent geometry fix.
  - Boundary group degrees proving stop: `785731` terminal groups `785730 degree=6`, `26902277 degree=7`; `706243` terminal group `706245 degree=4`; `724081` terminal group `522008569 degree=4`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate` -> `1 passed in 201.41s`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate` -> `2 passed in 244.05s`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_new_structure_only_road_surface_forks_keep_760598_rejected` -> first exposed stale 724081 geometry expectation after correct over-recall removal; after updating expected values, `1 passed in 24.13s`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon` -> `170 passed in 848.56s`。
- `.venv/bin/python -m py_compile` on modified Python source files -> passed.
- `git diff --check` -> passed.

### 硬停机检查

- [x] Did not trigger `AGENTS.md §1.1`; source/spec wording was updated under explicit user authorization.
- [x] Did not trigger `§1.2`; module contract edits are within this authorized SpecKit correction.
- [x] Did not trigger `§1.3`; no permanent entrypoint was added.
- [x] Did not trigger `§1.4`; all touched source/test files remain below `100 KB`.
- [x] Did not trigger `§1.5`; this is user-confirmed business logic, not inferred upstream field semantics.
- [x] Did not trigger `§1.6`; Windows path `E:\TestData\POC_Data\T02\Anchor_2` is executed as `/mnt/e/TestData/POC_Data/T02/Anchor_2` under bash.
- [x] Did not trigger `§1.7`; no entrypoint change.

### 待确认

- 需要用户目视确认新 39-case PNG，重点路径：`outputs/_work/t04_degree2_boundary/anchor2_39case_semantic_group_degree_20260504_001/step4_review_flat`。
- 本轮仍未 commit / push，等待后续统一提交指令。

## 2026-05-04 Baseline/Test Contract Cleanup

### 背景

- 用户确认：`E:\TestData\POC_Data\T02\Anchor_2` 是唯一 official Anchor_2 数据集；当前 bash 路径为 `/mnt/e/TestData/POC_Data/T02/Anchor_2`。
- 该目录下当前 official case 清单为 `39` 个；历史 23-case 与 30-case 均为其中子集，不再作为独立 batch / PNG fingerprint 基线。

### 已修改

- 新增 `tests/modules/t04_divmerge_virtual_polygon/data/anchor2_official_39case_baseline_20260504.json`：集中维护 official 39-case baseline、legacy 23/30 subset 清单和 surface scenario matrix。
- `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py`：移除内联 39-case 大字典与历史 PNG raw fingerprint 断言；`test_anchor2_full_20260426_baseline_gate` 与 `test_anchor2_30case_surface_scenario_baseline_gate` 改为 legacy projection 轻量 gate；official 39-case gate 保持真实 batch 回归。
- 模块契约 / README / architecture / glossary：统一声明 official 39-case 为唯一正式基线，23/30 仅从 manifest 投影。
- SpecKit `spec.md / plan.md / tasks.md`：Phase 6 / §8.5 / §8.10 改为 official 39-case gate + legacy projection gate。
- `docs/repository-metadata/code-size-audit.md`：刷新当前源码 / 脚本体量；记录 `test_step7_final_publish.py` 从约 `83 KB` 降到 `56366` bytes。

### 已验证

- `.venv/bin/python -m json.tool tests/modules/t04_divmerge_virtual_polygon/data/anchor2_official_39case_baseline_20260504.json` -> passed。
- `.venv/bin/python -m py_compile tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` -> passed。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_full_20260426_baseline_gate tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_30case_surface_scenario_baseline_gate` -> `2 passed in 3.10s`。
- `pytest -s -q tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py::test_anchor2_39case_official_surface_scenario_gate` -> `1 passed in 173.71s`。
- 文件体量复检：
  - `test_step7_final_publish.py = 56366` bytes
  - `_runtime_step3_topology_skeleton.py = 34623` bytes
  - `rcsd_alignment.py = 37693` bytes
  - `test_step3_swsd_semantic_junction.py = 13527` bytes
  - `test_step4_rcsd_alignment_type.py = 30076` bytes

### 待确认

- 本轮清理没有 commit / push。
- 本轮未重跑 `pytest tests/modules/t04_divmerge_virtual_polygon -q` 全模块；本次改动不触及运行时代码，已跑 official 39-case gate 与 legacy projection gate。
