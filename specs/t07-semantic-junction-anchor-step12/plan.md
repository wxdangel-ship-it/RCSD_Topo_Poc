# Implementation Plan: T07 Semantic Junction Anchor Step1/Step2

**Branch**: `codex/t07-semantic-junction-anchor-step12` | **Date**: 2026-05-21 | **Spec**: `specs/t07-semantic-junction-anchor-step12/spec.md`
**Input**: Feature specification from `specs/t07-semantic-junction-anchor-step12/spec.md`

## Summary

T07 will be a semantic-junction-level extraction of T02 Step1/Step2. It keeps the business meaning of `has_evd / is_anchor / anchor_reason`, uses representative `kind_2` as the gate, and removes every Segment input/output/summary path. The first implementation round should create a module-local callable runner and tests only; no repo official CLI or persistent script entrypoint is allowed without explicit follow-up authorization.

## Technical Context

**Language/Version**: Python 3.10.x
**Primary Dependencies**: Existing project stack: shapely, pyproj, fiona, GeoPackage writer utilities
**Storage**: File-based vector inputs/outputs, primarily GeoPackage
**Testing**: `.venv/bin/python -m pytest ...`
**Target Platform**: WSL local workspace and innernet-compatible batch environment
**Project Type**: Python geospatial processing module
**Performance Goals**: Process full `nodes` and polygon evidence without Segment scan overhead; produce timing/perf summary for full-layer runs.
**Constraints**: No Segment processing; no repo official entrypoint; no silent geometry/CRS fix; source/script files must stay below 100 KB per repository rule.
**Scale/Scope**: Full-layer `nodes`, `DriveZone`, and `RCSDIntersection` inputs; Step1/Step2 only.

## Product / Architecture / Development / Testing / QA Views

- **Product**: T07 answers only three semantic-junction-level questions: whether the semantic junction has road-surface evidence, whether it is already anchored to `RCSDIntersection`, and why special anchor cases are accepted.
- **Architecture**: T07 should be separate from T02 runtime code, while reusing stable shared utility concepts where doing so does not import T02 module internals as the formal implementation owner.
- **Development**: Implement T07 as module-local callable code under `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/`; do not add CLI, scripts, tools, `run.py`, or `__main__.py` in the first implementation round.
- **Testing**: Add focused synthetic tests under `tests/modules/t07_semantic_junction_anchor/` for Step1, Step2, skipped `kind_2`, representative-only writes, and no Segment dependency.
- **QA**: Before closeout, explicitly report CRS correctness, topology consistency, geometry semantic explainability, audit traceability, and performance evidence.

## Constitution Check

*GATE: Must pass before implementation. Re-check after design.*

- Source facts: T07 is not yet registered as an Active module. Implementation must either remain an unregistered draft module or include explicit user authorization to update project/module lifecycle docs.
- Entry points: This plan forbids new repo CLI and persistent scripts in the first implementation round.
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

### Proposed Source Code

```text
src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/
├── __init__.py
├── semantic_junctions.py
├── step1_has_evd.py
├── step2_anchor_recognition.py
└── outputs.py

tests/modules/t07_semantic_junction_anchor/
├── test_step1_has_evd.py
├── test_step2_anchor_recognition.py
└── test_no_segment_dependency.py
```

### Formal Module Docs, If User Authorizes Registration

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

**Structure Decision**: Start with SpecKit artifacts and module-local callable implementation. Project-level registration docs remain a separate authorized step.

## Implementation Notes

- T07 should preserve T02's representative node write policy.
- T07 should not preserve T02's `segment_referenced_junction_set`; candidate groups come only from semantic junction groups derived from `nodes`.
- T07 summary should be semantic-junction-level, not `s_grade` or Segment based.
- T07 Step2 can preserve T02's `node_error_1 / node_error_2` concepts, but their rows must be expressed as semantic-junction conflicts, not Segment-linked audit.

## Complexity Tracking

No constitution violation is planned.
