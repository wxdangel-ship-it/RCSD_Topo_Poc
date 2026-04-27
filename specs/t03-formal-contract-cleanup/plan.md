# Implementation Plan: T03 Formal Contract Cleanup

**Date**: 2026-04-27
**Spec**: [spec.md](/tmp/rcsd_t03_contract_cleanup/specs/t03-formal-contract-cleanup/spec.md)

## Summary

This is a formal contract migration for T03. It removes historical `Step45 / Step67` names from current code-facing contracts and replaces them with `Association / Finalization` concepts plus explicit `Step4~Step7` output names.

## Scope

- T03 source files under `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor`.
- T03 tests under `tests/modules/t03_virtual_junction_anchor`.
- T03 scripts under `scripts/`.
- T03 module docs and repository governance docs.
- T03 architecture/history document layout.

## Safety Rules

- Keep business logic unchanged.
- Keep geometry behavior unchanged.
- Do not touch T04 dirty work from the main worktree.
- Before writing source/script files, verify file size is below the 100 KB hard limit.
- Delete ignored `__pycache__` generated artifacts.

## Validation

- Run targeted T03 pytest suites.
- Run the broader T03 suite once and report any residual semantic failures without changing business logic.
- Run `rg` for `Step45|Step67|step45|step67` and classify remaining hits.
- Run `git diff --check`.
- Confirm removed wrapper scripts are also removed from `entrypoint-registry.md`.
