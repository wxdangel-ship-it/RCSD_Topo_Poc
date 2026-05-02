# Feature Specification: T04 Anchor_2 SWSD Window Repair

**Feature Branch**: `codex/t04-anchor2-swsd-window-repair`
**Created**: 2026-05-02
**Status**: Implemented; pending user visual sign-off
**Input**: User request to use SpecKit with product / architecture / development / testing / QA / visual-audit roles, protect the existing Anchor_2 30-case baseline, and repair six newly reviewed Anchor_2 cases.

## Context

T04 now covers Step1-7 for divmerge virtual anchor surface generation. The existing Anchor_2 30-case baseline is a formal guard: its accepted/rejected states, evidence semantics, RCSD recall semantics, section-reference semantics, Step6 guard behavior, review outputs, and downstream `nodes.gpkg` writeback must not regress.

The user added six Anchor_2 cases and manually audited their business semantics:

- `785629`: main evidence exists; main evidence is `divstrip`; no RCSD semantic junction.
- `785631`: main evidence exists; main evidence is `divstrip`; RCSD semantic junction exists.
- `785731`: no main evidence, no RCSD semantic junction.
- `795682`: no main evidence, no RCSD semantic junction.
- `807908`: main evidence exists; main evidence is `divstrip`; RCSD semantic junction exists, but recall must not include other RCSD junction branches outside the semantic junction.
- `823826`: main evidence exists; main evidence is `divstrip`; RCSD semantic junction exists; complex junction.

The current module source facts incorrectly allow readers to interpret `no_surface_reference` as a normal business branch for "no main evidence + no RCSD semantic junction + no SWSD semantic junction". The user clarified that a valid T04 input is already based on a SWSD semantic junction / SWSD divmerge candidate, so a normal Anchor_2 case cannot lack SWSD semantic context. Therefore, `no_surface_reference` must be treated as a defensive abnormal state, not a normal T04 business scenario.

The 2026-05-02 follow-up visual audit added eleven targeted case findings:

- `698380 / 698389 / 760277 / 807908`: `divstrip` or road-surface main evidence plus RCSD semantic junction. The surface must follow `Reference Point + RCSD semantic junction` section-reference rules, and final review rendering must show the active RCSDRoad/RCSDNode set.
- `768675`: no main evidence plus RCSD semantic junction. The surface may use RCSD junction section reference, but active RCSDRoad publication must be limited to the recalled semantic junction.
- `765050`: complex junction whose units have no main evidence and no RCSD semantic junction. Since valid T04 inputs still have SWSD semantic context, this must render SWSD current roads and use SWSD section windows, not `no_surface_reference`.
- `785629`: complex junction with mixed units. At least one unit has `divstrip` main evidence without RCSD semantic junction; other units may be SWSD-only. The case-level scenario may be `mixed`, but active RCSDRoad publication must remain empty when no RCSD semantic junction is confirmed.
- `785731`: no main evidence and no RCSD semantic junction. Far or weak RCSDRoad proximity is trace-only; it must not be rendered as current RCSDRoad or used as an RCSD semantic junction.
- `765170 / 768680 / 823826`: final surfaces are semantically correct but must avoid visually abnormal small concavities or slit-like artifacts. Relief may only run when it preserves must-cover, allowed-growth, forbidden, and terminal-cut guards.

## Product Requirements

### PR-001 Existing 30-case Baseline Protection

The existing `E:\TestData\POC_Data\T02\Anchor_2` 30-case baseline MUST not regress.

Regression scope includes:

- `final_state`, `publish_target`, accepted/rejected counts.
- `surface_scenario_type`, `section_reference_source`, `surface_generation_mode`.
- `has_main_evidence`, `main_evidence_type`, `reference_point_present`, `reference_point_source`.
- `evidence_source`, `selected_evidence`, `rcsd_match_type`, `rcsd_selection_mode`.
- `required_rcsd_node`, `positive_rcsd_present`, selected RCSD road/node ids.
- Step5 support domain modes and must-cover components.
- Step6 guards: connectedness, holes, allowed growth, forbidden, terminal cut, lateral limit, B-node gate.
- Step7 consistency report, rejected index, review PNG presence, and `nodes.gpkg` / `nodes_anchor_update_audit.*` writeback.

### PR-002 New 6-case Business Outcomes

The six new cases SHOULD become accepted when their geometry satisfies existing Step5/Step6 safety guards.

Expected semantic classifications:

| Case | Expected business semantics | Expected T04 scenario |
| --- | --- | --- |
| `785629` | complex mixed case; at least one `divstrip` main-evidence unit + no RCSD semantic junction | case-level `mixed`, with no active RCSDRoad |
| `785631` | `divstrip` main evidence + RCSD semantic junction | `main_evidence_with_rcsd_junction` |
| `785731` | no main evidence, no RCSD semantic junction | `no_main_evidence_with_swsd_only` |
| `795682` | no main evidence, no RCSD semantic junction | `no_main_evidence_with_swsd_only` |
| `807908` | `divstrip` main evidence + RCSD semantic junction, with RCSD recall limited to the semantic junction chain | `main_evidence_with_rcsd_junction` |
| `823826` | `divstrip` main evidence + RCSD semantic junction, complex; no visual slit holes, matching the `824002` smooth-fill class | `main_evidence_with_rcsd_junction` |

### PR-003 No Virtual Reference Point

When `has_main_evidence = false`, T04 MUST NOT create a virtual Reference Point. The section reference may be SWSD or RCSD, but:

- `reference_point_present = false`
- `reference_point_source = none`
- `fact_reference_point = null`

### PR-004 no_surface_reference Reframing

`no_surface_reference` MUST be documented and implemented as a defensive abnormal state. It is allowed only when the case cannot materialize any valid section reference after Step4 recovery, and it must be audited as an abnormal missing-reference condition rather than a normal T04 business scenario.

### PR-005 RCSD Publication and Full-Fill Guards

`main_evidence_with_rcsd_junction` MUST use `Reference Point + RCSD semantic junction` semantics even when the Step4 evidence source is a recovered or promoted form of `divstrip`/road-surface evidence. Step5 may enable `junction_full_road_fill` for this scenario, but continuous-chain review cases keep their legacy `standard` fill unless the visual audit explicitly requires full-fill.

Weak road-surface-fork RCSD binding is valid only when the required RCSD node is local to the representative/SWSD section. A far required RCSD node is trace-only and must not activate `rcsd_junction`, current RCSDRoad rendering, or RCSD-driven publication.

### PR-006 Review Rendering

Final review PNGs MUST distinguish:

- SWSD current roads vs SWSD other roads.
- RCSD current roads/nodes vs RCSD other roads.
- Section window geometry.

This is required so visual audit can detect false RCSD downgrade, over-recall, or missing SWSD section context without opening raw vector layers first.

## Non-Goals

- Do not add repo-level CLI commands or scripts.
- Do not weaken Step7 final states; they remain `accepted / rejected`.
- Do not import or call T03 runtime code from T04.
- Do not relax forbidden-domain, terminal-cut, lateral-limit, or allowed-growth guards to raise accepted count.
- Do not change existing rejected baseline cases into accepted unless the current task explicitly names them.

## Success Criteria

- **SC-001**: Documentation source facts state that valid T04 inputs carry SWSD semantic context and that `no_surface_reference` is abnormal defensive fallback.
- **SC-002**: The original Anchor_2 30-case gate passes with no regression in states and key semantic fields.
- **SC-003**: The six new cases produce expected Step4 scenario semantics and no virtual Reference Point in no-main-evidence cases.
- **SC-004**: The eleven follow-up visual-audit cases pass Step5/Step6 geometry guards or provide a precise audited reason if a geometry guard blocks acceptance.
- **SC-005**: New/updated tests cover the six cases, the original 30-case semantic guard, and targeted Step4/Step5 edge conditions.
- **SC-006**: Verification explicitly covers CRS/coordinate assumptions, topology consistency, geometry semantics, audit traceability, and performance impact.
