# Implementation Plan: T03 RCSD semantic node classification

## Scope

Revise T03 RCSDNode semantics so `mainnodeid` is a grouping/candidate signal only. Effective degree and final u-turn filtering decide whether a node/group is semantic evidence or connector evidence.

## Design

1. Update module contract documents to state the candidate-vs-semantic distinction.
2. In Step4, allow effective-degree-2 nodes/groups with `mainnodeid` to participate as connector nodes.
3. In Step4 related group expansion, prevent effective-degree-2 groups from being promoted to `related_rcsdnode_ids`.
4. In Step5, classify effective-degree-2 retained-incident nodes as nonsemantic connectors regardless of `mainnodeid`.
5. In Step6 single-sided tracing, filter terminal endpoint nodes using Step4's connector audit fields.
6. Add regression tests for synthetic and real cases.

## Risks

- Existing real-case expectations may change where prior logic stopped at `mainnodeid` representatives.
- Step6 tracing can become more conservative if a previous terminal endpoint was actually a degree-2 connector.
- Dirty worktree contains prior T03 changes; this round must avoid reverting unrelated files.
