# Tasks: T03 Formal Contract Cleanup

## Audit

- [x] T001 Confirm user authorization for formal contract migration.
- [x] T002 Create a clean worktree from `origin/main`.
- [x] T003 Audit Association/Finalization references in architecture, scripts, tests, source, and pycache.
- [x] T004 Verify source/script file sizes before edits.

## Implementation

- [x] T010 Rename code concepts to `Association*` and `Finalization*`.
- [x] T011 Rename formal output filenames and status fields.
- [x] T012 Remove historical finalization wrapper scripts and registry entries.
- [x] T013 Move historical closeout docs into `history/`.
- [x] T014 Rename tests and helper files.
- [x] T015 Update documentation contracts.
- [x] T016 Delete ignored `__pycache__` artifacts.

## Validation

- [x] T020 Run targeted T03 contract regression tests and broader T03 suite.
- [x] T021 Run residual `rg` audit.
- [x] T022 Run `git diff --check`.
- [x] T023 Summarize modified / verified / pending.
