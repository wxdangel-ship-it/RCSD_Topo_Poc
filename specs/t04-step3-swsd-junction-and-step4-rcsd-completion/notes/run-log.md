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
