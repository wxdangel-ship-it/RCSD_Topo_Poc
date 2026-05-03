"""Print case-by-case summary of an Anchor_2 batch run."""
from __future__ import annotations

import json
import sys
from pathlib import Path


BASELINE_30 = {
    "accepted": {
        "698380","698389","699870","706347","706629","723276","724067","724081","758784","760213",
        "760230","760256","760277","760984","765050","765170","768680","785671","785675","788824",
        "824002","987998","17943587","30434673","73462878","505078921",
    },
    "rejected": {"760598","760936","857993","607602562"},
}


def main(run_id: str = "phase1_d2_v3_anchor2_full") -> None:
    path = Path(f"outputs/_work/t04_six_case_scenario_realign/{run_id}/divmerge_virtual_anchor_surface_summary.json")
    summary = json.loads(path.read_text(encoding="utf-8"))
    rows = summary["rows"]
    print(f"row_count = {summary['row_count']}  accepted = {summary['accepted_count']}  rejected = {summary['rejected_count']}")

    accepted_ids = {r["case_id"] for r in rows if r["final_state"] == "accepted"}
    rejected_ids = {r["case_id"] for r in rows if r["final_state"] == "rejected"}

    print(f"\nrejected: {sorted(rejected_ids)}")
    print()

    print("=== 30-case baseline gate check ===")
    expected_accepted = BASELINE_30["accepted"]
    expected_rejected = BASELINE_30["rejected"]
    missing_accepted = expected_accepted - accepted_ids
    extra_rejected_in_baseline = expected_accepted & rejected_ids
    accepted_baseline_violations = expected_rejected & accepted_ids
    print(f"30-case accepted but actually rejected: {sorted(extra_rejected_in_baseline)}")
    print(f"30-case rejected but actually accepted: {sorted(accepted_baseline_violations)}")

    print("\n=== Six-case checkpoint ===")
    six_cases = ["706347", "724081", "765050", "768675", "785731", "795682"]
    for cid in six_cases:
        match = [r for r in rows if r["case_id"] == cid]
        if not match:
            print(f"  {cid}: NOT IN BATCH")
            continue
        r = match[0]
        print(f"  {cid}: {r['final_state']:8s} comp={r['final_case_polygon_component_count']}  scenario={r['surface_scenario_type']}  ref={r['section_reference_source']}")

    print("\n=== All cases summary ===")
    for r in sorted(rows, key=lambda r: r["case_id"]):
        marker = ""
        cid = r["case_id"]
        state = r["final_state"]
        if cid in BASELINE_30["accepted"] and state == "rejected":
            marker = "  ← ✗ baseline expected accepted"
        elif cid in BASELINE_30["rejected"] and state == "accepted":
            marker = "  ← ✗ baseline expected rejected"
        elif cid not in BASELINE_30["accepted"] and cid not in BASELINE_30["rejected"]:
            marker = "  (new case)"
        print(f"  {cid}: {state:8s} comp={r['final_case_polygon_component_count']}  scenario={r['surface_scenario_type']:55s}  {marker}")


if __name__ == "__main__":
    run_id = sys.argv[1] if len(sys.argv) > 1 else "phase1_d2_v3_anchor2_full"
    main(run_id)
