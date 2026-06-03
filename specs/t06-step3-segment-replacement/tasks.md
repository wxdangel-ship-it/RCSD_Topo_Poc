# T06 Step3 Segment Replacement and Junction Rebuild Tasks

## Specify

- [x] Confirm Step3 belongs to T06 module.
- [x] Confirm Step3 consumes Step2 replaceable RCSDSegment.
- [x] Confirm C is built from replaceable Segment `pair_nodes + junc_nodes`.
- [x] Confirm SWSDRoad in replaced Segment is removed.
- [x] Confirm SWSDNode removal is limited to removed SWSDRoad endpoint nodes.
- [x] Confirm RCSDRoad / RCSDNode from retained RCSDSegment is added.
- [x] Confirm F-RCSD `source` values: RCSD = `1`, SWSD = `2`.
- [x] Confirm C mainnode rebuild inherits original mainnode attributes.
- [x] Confirm F-RCSD output file names.
- [x] Confirm id collision policy.
- [x] Confirm new main node selection priority.
- [x] Confirm Step3 should be opt-in or part of default T06 end-to-end runner.

## Plan

- [x] Define Step3 module boundary.
- [x] Define copy-on-write replacement strategy.
- [x] Define expected outputs and audit categories.
- [x] Define testing and QA requirements.
- [x] Freeze source fact updates.
- [x] Freeze entrypoint behavior.

## Implement

- [x] Update T06 and project source facts to include Step3.
- [x] Add Step3 schemas / constants.
- [x] Add Step3 replacement unit parser.
- [x] Add removed SWSD road/node calculation.
- [x] Add added RCSD road/node calculation.
- [x] Add Junction C builder and C-to-Segment relation.
- [x] Add C mainnode rebuild logic.
- [x] Add F-RCSD road/node writer.
- [x] Add Step3 summary and audit outputs.
- [x] Wire Step3 callable runner.
- [x] Preserve Step1 / Step2 compatibility.
- [x] Add `t06_step3_swsd_frcsd_segment_relation.gpkg/csv/json` for downstream T09 Step3.
- [x] Add relation summary counts for `replaced / retained_swsd / failed`.

## Test

- [x] Add unit tests for endpoint-only SWSDNode removal.
- [x] Add unit tests for source field assignment.
- [x] Add unit tests for duplicate replacement unit road/node dedupe.
- [x] Add unit tests for C-to-Segment relation.
- [x] Add unit tests for original mainnode retained.
- [x] Add unit tests for original mainnode removed and new mainnode selected.
- [x] Add unit tests for inherited `kind / grade / kind_2 / grade_2 / closed_con`.
- [x] Add unit tests for replaced Segment relation output.
- [x] Add unit tests for retained_swsd Segment relation output.
- [x] Run T06 pytest suite.

## QA

- [x] Verify CRS handling in summary.
- [x] Verify topology edits are explicit and auditable.
- [x] Verify no input file is modified.
- [x] Verify F-RCSD output has complete `source` values.
- [x] Verify replacement counts and output counts are reproducible from summary.
- [x] Verify relation output can locate FRCSD roads by `id + source`.
- [x] Verify XS1 relation output covers T09 Step3 Arm segment inputs.
- [x] Verify entrypoint registry remains consistent if any script behavior changes.
