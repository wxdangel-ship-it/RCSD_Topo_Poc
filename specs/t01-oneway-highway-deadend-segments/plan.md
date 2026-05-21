# Implementation Plan: T01 单向高速与断头 Segment 扩展

**Branch**: `codex/t01-oneway-highway-deadend-speckit` | **Date**: 2026-05-21 | **Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t01-oneway-highway-deadend-segments/spec.md)  
**Input**: Feature specification from `/specs/t01-oneway-highway-deadend-segments/spec.md`

## Summary

本变更把 T01 已确认的内网需求正式化：单向补段阶段放开 `road_kind=1` 封闭式/高速 road，`0-1单 / 0-2单` 纳入 `kind_2=128` 复杂分歧合流路口作为 terminate，并以独立子模式支持断头 road bundle 通过 leaf node 构成 Segment。断头 bundle 覆盖单条双向 road 与两条方向互补单向 road 两种表达。实施顺序必须先完成低风险单向补段，再处理会改变双向构段与 Step6 语义的 dead-end Segment。

## Technical Context

**Language/Version**: Python 3.10.x  
**Primary Dependencies**: GeoPandas/Shapely/Fiona stack as existing repo dependency; no new dependency expected  
**Storage**: GeoPackage/GeoJSON/CSV/JSON outputs  
**Testing**: `.venv/bin/python -m pytest ...`  
**Target Platform**: Local/innernet Python CLI on repo `.venv`  
**Project Type**: Python CLI / GIS processing module  
**Performance Goals**: No material regression in existing T01 local tests; innernet full-input must remain observable through summary and audit files  
**Constraints**: No new repo-level entrypoint; no automatic freeze baseline refresh; source facts must update with behavior changes  
**Scale/Scope**: T01 full SWSD road/node inputs; local fixture coverage plus innernet full-input validation

## Constitution Check

*GATE: Must pass before implementation.*

- **Source-of-truth conflict**: Current T01 source facts exclude `road_kind=1` and do not include `kind_2=128` in single-way phases. Implementation MUST update T01 source facts in the same round as code changes.
- **Scope control**: Dual-way `road_kind != 1` remains accepted baseline; only single-way candidate collection changes in Phase A.
- **Entrypoint governance**: No new `scripts/`, `tools/`, `Makefile`, CLI subcommand, `__main__.py`, or `run.py` entrypoint.
- **File-size governance**: Before writing any `.py` source file, confirm current byte size and do not write to files at or above `100 KB`.
- **GIS QA**: CRS, topology, geometry semantics, audit traceability, and performance evidence are mandatory completion checks.
- **Baseline governance**: Do not refresh active freeze baseline without explicit later approval.

## Project Structure

### Documentation (this feature)

```text
specs/t01-oneway-highway-deadend-segments/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
src/rcsd_topo_poc/modules/t01_data_preprocess/
├── step5_oneway_segment_completion.py
├── step6_segment_aggregation.py
├── step5_staged_residual_graph.py
├── working_layers.py
└── skill_v1.py

tests/modules/t01_data_preprocess/
├── test_step5_oneway_segment_completion.py
├── test_step6_segment_aggregation.py
├── test_step5_staged_residual_graph.py
└── test_skill_v1.py

modules/t01_data_preprocess/
├── INTERFACE_CONTRACT.md
└── architecture/
    ├── 02-constraints.md
    ├── 03-context-and-scope.md
    ├── 04-solution-strategy.md
    └── 06-accepted-baseline.md
```

**Structure Decision**: Reuse existing T01 modules and tests. This feature does not introduce a new package, new CLI command, or new permanent script.

## Phased Design

### Phase A - Single-way highway and `kind_2=128`

- Change only single-way candidate/terminate behavior.
- Candidate collection allows `road_kind=1`.
- Candidate collection still excludes existing `segmentid`, `formway=128`, right-turn-only, and non-single-way `direction`.
- `0-1单 / 0-2单` include `kind_2=128`.
- Add focused audit counters to `oneway_segment_summary.json`.

### Phase B - Dead-end leaf Segment

- Introduce explicit dead-end detection after existing dual-way stages or as a bounded sub-step before Step6.
- Leaf endpoint is a physical/semantic endpoint with one eligible incident road bundle and no competing valid continuation.
- Supported bundle forms are exactly one bidirectional road or exactly two reciprocal one-way roads between the same semantic endpoint pair.
- Segment id and Step6 fields must be deterministic.
- Do not let leaf endpoint become normal through/junction node.

### Phase C - Audit and innernet QA

- Produce enough per-road evidence to separate:
  - excluded road
  - dual-way built
  - single-way candidate built
  - single-way candidate failed
  - dead-end built
  - Step6 publish mismatch
- Run local tests and innernet latest T01 output audit.

## Risk Analysis

- **Business semantics risk**: `road_kind=1` is still excluded from dual-way accepted baseline; accidental global helper changes could silently alter Step2/4/5 behavior.
- **Field semantics risk**: `kind_2=128` is user-confirmed for complex diverge/merge; docs must record the confirmed scope and boundaries.
- **Topology risk**: Dead-end construction can overbuild stubs unless leaf rules are strict and auditable.
- **Step6 risk**: Pair/junction fields may misclassify leaf endpoints unless tested directly.
- **Performance risk**: More single-way candidates can increase trace attempts; summary must report candidate and fail counts.

## Verification Plan

- Unit tests:
  - `road_kind=1` single-way candidate builds.
  - `kind_2=128` acts as `0-1单 / 0-2单` terminate.
  - `0-0单` does not accidentally include `kind_2=128`.
  - dead-end bidirectional road builds with leaf endpoint.
  - dead-end reciprocal one-way road bundle builds with leaf endpoint and a two-node semantic junction endpoint.
  - Step6 publishes dead-end and single-way grades correctly.
- Regression tests:
  - Existing T01 single-way and Step6 tests.
  - Existing `test_skill_v1.py` routing tests.
- GIS checks:
  - CRS consistency for original SWSD vs T01 outputs.
  - No silent topology repair.
  - geometry direction audit for single-way trace.
  - per-road audit traceability.
  - performance summary for candidate/trace counts.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Update source-of-truth docs with code | Current accepted baseline conflicts with confirmed new requirements | Code-only change would violate repository governance and mislead future T01 work |
| Separate dead-end phase | Dead-end changes dual-way semantics and Step6 output fields | Folding it into existing pair validation risks overbuilding and unclear audit reasons |
