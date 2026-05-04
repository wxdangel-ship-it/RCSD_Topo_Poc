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
