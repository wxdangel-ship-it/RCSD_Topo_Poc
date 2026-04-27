# Implementation Plan: T03 Step1-Step7 Documentation Realignment

**Date**: 2026-04-27
**Spec**: [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t03-step1-step7-docs-realignment/spec.md)

## Summary

This is a documentation and source-fact realignment. It updates T03's formal documentation structure from the historical `Step3 / Step45 / Step67` framing to the formal `Step1~Step7` business chain.

The implementation deliberately preserves existing code and output compatibility names. `Step45` and `Step67` remain valid implementation-stage labels where the current repository still exposes them through files, classes, tests, CLI names, and compatibility wrappers.

## Role Coverage

- Product: confirm `Step1~Step7` is the main business narrative.
- Architecture: keep compatibility mapping separate from the main contract.
- Development: do not rename code symbols or output files in this round.
- Testing: preserve regression contracts and test fixtures that assert current output names.
- QA: verify source facts and entrypoint descriptions stay consistent.

## Update Scope

### Module source facts

- `modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md`
- `modules/t03_virtual_junction_anchor/README.md`
- `modules/t03_virtual_junction_anchor/AGENTS.md`
- `modules/t03_virtual_junction_anchor/architecture/04-solution-strategy.md`
- `modules/t03_virtual_junction_anchor/architecture/10-quality-requirements.md`
- `modules/t03_virtual_junction_anchor/architecture/11-business-steps-vs-implementation-stages.md`

### Repository source facts

- T03 rows and paragraphs in project/governance inventory docs.
- Entrypoint registry descriptions only where they need wording clarification.

## Constraints

- Do not edit T03 code, tests, scripts, or CLI signatures.
- Do not delete historical closeout documents.
- Do not change formal output contracts.
- Do not expand into T02 or T04 module contracts.

## Validation

- Inspect `git diff --stat` and changed files.
- Run `rg` against updated docs to confirm `Step45/Step67` are limited to compatibility/mapping contexts.
- Confirm no source or script file was modified by this documentation round.
