# Implementation Plan: T07 Semantic Junction Anchor Step1/Step2/Step3

**Branch**: `codex/t07-semantic-junction-anchor-step12` | **Date**: 2026-05-21 | **Spec**: `specs/t07-semantic-junction-anchor-step12/spec.md`
**Input**: Feature specification from `specs/t07-semantic-junction-anchor-step12/spec.md`

## Summary

T07 will be a semantic-junction-level extraction of T02 Step1/Step2 plus an independent Step3 relation backfill. It keeps the business meaning of `has_evd / is_anchor / anchor_reason`, uses representative `kind_2` as the gate, consumes T05 `intersection_match_all.geojson` only in Step3, and removes every Segment input/output/summary path. This implementation round keeps module-local callable runners, focused tests, the Step1/Step2 wrapper `scripts/t07_run_semantic_junction_anchor_innernet.sh`, and the independent Step3 wrapper `scripts/t07_run_step3_intersection_match_innernet.sh`; no repo official CLI is added.

## Technical Context

**Language/Version**: Python 3.10.x
**Primary Dependencies**: Existing project stack: shapely, pyproj, fiona, GeoPackage writer utilities
**Storage**: File-based vector inputs/outputs, primarily GeoPackage
**Testing**: `.venv/bin/python -m pytest ...`
**Target Platform**: WSL local workspace and innernet-compatible batch environment
**Project Type**: Python geospatial processing module
**Performance Goals**: Process full `nodes` and polygon evidence without Segment scan overhead; produce timing/perf summary for full-layer runs.
**Constraints**: No Segment processing; no repo official CLI; only the approved innernet wrapper scripts; no silent geometry/CRS fix; source/script files must stay below 100 KB per repository rule.
**Scale/Scope**: Full-layer `nodes`, `DriveZone`, `RCSDIntersection`, T05 `intersection_match_all.geojson`, and input `RCSDNode`; Step3 is independent from Step1/Step2 execution.

## Product / Architecture / Development / Testing / QA Views

- **Product**: T07 answers semantic-junction-level questions: whether the semantic junction has road-surface evidence, whether it is already anchored to `RCSDIntersection`, why special anchor cases are accepted, and whether a T05 success relation can safely backfill `is_anchor = yes`.
- **Architecture**: T07 should be separate from T02 runtime code, while reusing stable shared utility concepts where doing so does not import T02 module internals as the formal implementation owner. Step3 is a separate module file and script so it does not alter Step1/Step2 execution.
- **Development**: Implement T07 as module-local callable code under `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/`; add only the approved innernet wrapper scripts, and do not add repo CLI, tools, `run.py`, or `__main__.py`.
- **Testing**: Add focused synthetic tests under `tests/modules/t07_semantic_junction_anchor/` for Step1, Step2, Step3 relation backfill, skipped `kind_2`, representative-only writes, and no Segment dependency.
- **QA**: Before closeout, explicitly report CRS correctness, topology consistency, geometry semantic explainability, audit traceability, and performance evidence.

## Constitution Check

*GATE: Must pass before implementation. Re-check after design.*

- Source facts: User has authorized T07 Active module registration and the corresponding project/module lifecycle updates.
- Entry points: This plan forbids new repo CLI and allows only the approved wrappers `scripts/t07_run_semantic_junction_anchor_innernet.sh` and `scripts/t07_run_step3_intersection_match_innernet.sh`.
- File size: Before editing any `.py` test or source file, check current byte size; do not append to files at or above 100 KB.
- Data semantics: `kind_2` is explicitly user-confirmed as the only field for this scope; no local sample-derived field semantics may be promoted.
- GIS checks: CRS, topology, geometry semantic explainability, audit traceability, and performance verifiability are mandatory completion checks.

## Project Structure

### Documentation

```text
specs/t07-semantic-junction-anchor-step12/
├── spec.md
├── plan.md
└── tasks.md
```

### Implemented Source Code

```text
src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/
├── __init__.py
├── runner.py
└── step3_intersection_match.py

scripts/
├── t07_run_semantic_junction_anchor_innernet.sh
└── t07_run_step3_intersection_match_innernet.sh

tests/modules/t07_semantic_junction_anchor/
├── test_runner.py
└── test_step3_intersection_match.py
```

### Formal Module Docs

```text
modules/t07_semantic_junction_anchor/
├── AGENTS.md
├── INTERFACE_CONTRACT.md
├── README.md
└── architecture/
    ├── 01-introduction-and-goals.md
    ├── 02-constraints.md
    ├── 03-context-and-scope.md
    ├── 04-solution-strategy.md
    ├── 05-building-block-view.md
    ├── 10-quality-requirements.md
    ├── 11-risks-and-technical-debt.md
    └── 12-glossary.md
```

**Structure Decision**: Keep Step1 / Step2 in `runner.py`; implement Step3 in `step3_intersection_match.py` and an independent shell wrapper so Step3 does not change Step1 / Step2 execution. Project-level registration and entrypoint registry are updated in this authorized round.

## Implementation Notes

- T07 should preserve T02's representative node write policy.
- T07 should not preserve T02's `segment_referenced_junction_set`; candidate groups come only from semantic junction groups derived from `nodes`.
- T07 summary should be semantic-junction-level, not `s_grade` or Segment based.
- T07 Step2 can preserve T02's `node_error_1 / node_error_2` concepts, but their rows must be expressed as semantic-junction conflicts, not Segment-linked audit.
- T07 Step3 uses T05 `target_id / base_id / status` as a published relation fact and only verifies `base_id` existence against input `RCSDNode.id/mainnodeid`; it does not infer new RCSD field semantics.

## Complexity Tracking

No constitution violation is planned after the explicit registration and script authorization.
