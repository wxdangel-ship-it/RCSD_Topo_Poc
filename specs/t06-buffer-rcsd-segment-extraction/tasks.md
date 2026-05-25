# T06 Buffer-Based RCSD Segment Extraction Tasks

## Specify

- [x] Confirm buffer strategy.
- [x] Confirm RCSDRoad `intersects + threshold`.
- [x] Confirm `formway` bit7 advance-right exclusion.
- [x] Confirm `junc_kind2_exempt_nodes` are optional allowed, not required.

## Plan

- [x] Define module boundary and no new entrypoints.
- [x] Define output and audit expectations.
- [x] Define verification requirements.

## Implement

- [x] Add buffer extraction helper module.
- [x] Add Step2 review outputs and schema fields.
- [x] Update project and T06 source facts.
- [ ] Keep existing Step2 output compatibility where possible.

## Test

- [x] Add unit tests for advance-right formway bit.
- [x] Add unit tests for buffer road selection.
- [x] Add unit tests for required semantic component coverage.
- [x] Add unit tests for inner/out seed pruning.
- [ ] Run T06 pytest suite.

## QA

- [ ] Verify GIS checks in summary.
- [ ] Verify audit fields locate inputs, parameters and outputs.
- [ ] Verify no input files are modified.
- [ ] Verify no new repo entrypoint was introduced.
