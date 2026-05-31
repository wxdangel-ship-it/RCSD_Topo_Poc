# T09 Traffic Restriction Recovery Draft Tasks

## Draft

- [x] Capture user-provided T09 business goal.
- [x] Capture Step1 scope: SWSD `kind_2 = 4` Arm and ArmMovement.
- [x] Record that P01 is a strategy reference, not an implementation owner.
- [x] Record that T01 Segment results should be used to reduce repeated topology tracing.
- [x] Keep this round limited to `specs/` draft artifacts.

## Specify

- [x] Confirm T09 formal module name and path: `t09_traffic_restriction_recovery`.
- [ ] Confirm Step1 target junction set: representative SWSD `kind_2 = 4` only.
- [x] Confirm whether Segment `junc_nodes` target junctions must be split in Step1.
- [x] Confirm Step1 output file formats and names.
- [x] Confirm current Step1 does not define RoadNextRoad or final restriction table output.
- [ ] Confirm whether T08 Tool7 `CondType=1` is the authoritative SWSD restriction input for later stages.
- [ ] Confirm movement type coding and whether any external RCSD turn type spec exists.

## Plan

- [ ] Freeze Product / Architecture / Development / Testing / QA views in an implementation-ready plan.
- [ ] Define T09 module source facts and project source fact updates.
- [ ] Define entrypoint policy: callable runner only, or separately authorized script wrapper.
- [ ] Define Step1 schema for `Arm`, `ArmMovement`, audit rows, and summary.
- [ ] Define Segment-aware handling of `pair_nodes` and required `junc_nodes` internal split.
- [ ] Define fallback policy when Segment membership is missing or inconsistent.
- [ ] Define CRS, topology, geometry semantic, audit, and performance QA checks.

## Implement

- [ ] Update project source facts after explicit authorization.
- [ ] Create `modules/t09_traffic_restriction_recovery/` docs after explicit authorization.
- [ ] Create `src/rcsd_topo_poc/modules/t09_traffic_restriction_recovery/` after explicit authorization.
- [ ] Add semantic junction grouping.
- [ ] Add SWSD nodes / roads / segment readers.
- [ ] Add Segment index builder.
- [ ] Add `kind_2 = 4` target selector.
- [ ] Add Segment-aware Arm builder.
- [ ] Add Movement candidate builder.
- [ ] Add movement type classifier.
- [ ] Add audit and summary writers.
- [ ] Preserve P01, T01, and T08 contracts.

## Test

- [ ] Add synthetic GPKG fixtures for single-node `kind_2 = 4` junction.
- [ ] Add synthetic GPKG fixtures for multi-node `mainnodeid` junction.
- [ ] Test non-`kind_2 = 4` junction skip.
- [ ] Test Segment `pair_nodes` based Arm build.
- [ ] Test Segment `junc_nodes` required internal split.
- [ ] Test Segment `junc_nodes` split failure produces explicit reject reason.
- [ ] Test missing Segment membership fallback audit.
- [ ] Test direction-based inbound / outbound role.
- [ ] Test Movement candidate generation.
- [ ] Test Movement does not imply allowed or prohibited status.
- [ ] Test summary counts and CRS audit.

## QA

- [ ] Verify CRS and output CRS metadata.
- [ ] Verify no silent topology fix.
- [ ] Verify Arm and Movement geometry semantics are explainable.
- [ ] Verify every output row traces to input junction / road / segment evidence.
- [ ] Verify performance counters are present.
- [ ] Verify no source/script file crosses the 100 KB threshold.
- [ ] Verify entrypoint registry is unchanged unless an entrypoint task is explicitly authorized.
