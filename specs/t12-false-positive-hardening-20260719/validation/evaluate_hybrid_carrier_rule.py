#!/usr/bin/env python3
"""Prototype a portal-constrained semantic carrier decision rule."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


def _truth(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _float(value: Any) -> float | None:
    text = str(value or "").strip()
    return float(text) if text else None


def _endpoint_trusted(
    row: pd.Series,
    *,
    endpoint: str,
    anchor_module: str,
    portal_radius_m: float,
) -> tuple[bool, str]:
    if _truth(row[f"{endpoint}_portal_exact"]):
        return True, "exact_raw_portal"
    if anchor_module == "T07":
        if _truth(row[f"{endpoint}_portal_shared_surface"]):
            return True, "t07_shared_standard_surface_alias"
        return False, "t07_alias_outside_standard_surface"
    gap = _float(row[f"{endpoint}_portal_min_gap_m"])
    if gap is not None and gap <= portal_radius_m:
        return True, "non_t07_nearby_group_alias"
    return False, "non_t07_alias_outside_portal_radius"


def _evaluate_candidate(
    source: pd.Series,
    direction_rows: pd.DataFrame,
    *,
    candidate_id_field: str,
    field_prefix: str,
    portal_radius_m: float,
) -> dict[str, Any]:
    candidate_id = str(source[candidate_id_field])
    failed = [
        item
        for item in str(source[f"{field_prefix}failed_directions"] or "").split("|")
        if item
    ]
    anchors = [
        item
        for item in str(source[f"{field_prefix}anchor_modules"] or "").split("|")
        if item
    ]
    if len(anchors) != 2:
        return {
            "candidate_id": candidate_id,
            "prototype_status": "not_assessable",
            "prototype_reason": "invalid_anchor_pair",
        }

    unresolved: list[str] = []
    evidence: list[dict[str, Any]] = []
    for direction in failed:
        matches = direction_rows.loc[
            (direction_rows["candidate_id"] == candidate_id)
            & (direction_rows["direction"] == direction)
            & (direction_rows["path_kind"] == "semantic_local_directed")
        ]
        if len(matches) != 1:
            unresolved.append(direction)
            evidence.append(
                {"direction": direction, "equivalent": False, "reason": "path_row_missing"}
            )
            continue
        row = matches.iloc[0]
        source_index, target_index = (
            (0, 1) if direction == "pair0_to_pair1" else (1, 0)
        )
        start_ok, start_reason = _endpoint_trusted(
            row,
            endpoint="start",
            anchor_module=anchors[source_index],
            portal_radius_m=portal_radius_m,
        )
        end_ok, end_reason = _endpoint_trusted(
            row,
            endpoint="end",
            anchor_module=anchors[target_index],
            portal_radius_m=portal_radius_m,
        )
        semantic_ok = _truth(row["path_accepted"])
        alias_gap = _float(row["max_alias_gap_m"]) or 0.0
        internal_ok = alias_gap <= portal_radius_m
        equivalent = semantic_ok and start_ok and end_ok and internal_ok
        if not equivalent:
            unresolved.append(direction)
        evidence.append(
            {
                "direction": direction,
                "equivalent": equivalent,
                "semantic_path_accepted": semantic_ok,
                "start_portal_trusted": start_ok,
                "start_reason": start_reason,
                "end_portal_trusted": end_ok,
                "end_reason": end_reason,
                "internal_alias_gap_m": alias_gap,
                "internal_alias_gap_trusted": internal_ok,
            }
        )

    if not failed or not unresolved:
        status = "excluded_false_positive"
        reason = "all_raw_failed_directions_have_portal_constrained_semantic_carrier"
    else:
        status = "confirmed_quality_issue"
        reason = "required_direction_still_lacks_trusted_semantic_carrier"
    return {
        "candidate_id": candidate_id,
        "prototype_status": status,
        "prototype_reason": reason,
        "original_issue_type": str(source.get(f"{field_prefix}issue_type", "")),
        "failed_directions": "|".join(failed),
        "unresolved_directions": "|".join(unresolved),
        "direction_evidence_json": json.dumps(evidence, ensure_ascii=False),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-csv", required=True, type=Path)
    parser.add_argument("--direction-summary", required=True, type=Path)
    parser.add_argument("--out-csv", required=True, type=Path)
    parser.add_argument("--candidate-id-field", default="candidate_id")
    parser.add_argument("--field-prefix", default="")
    parser.add_argument("--portal-radius-m", type=float, default=50.0)
    args = parser.parse_args(argv)

    candidates = pd.read_csv(args.candidate_csv, dtype=str).fillna("")
    directions = pd.read_csv(args.direction_summary, dtype=str).fillna("")
    rows = [
        _evaluate_candidate(
            row,
            directions,
            candidate_id_field=args.candidate_id_field,
            field_prefix=args.field_prefix,
            portal_radius_m=args.portal_radius_m,
        )
        for _, row in candidates.iterrows()
    ]
    out_csv = args.out_csv.resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_csv, index=False, encoding="utf-8-sig")
    payload = {
        "candidate_count": len(rows),
        "confirmed_count": sum(
            row["prototype_status"] == "confirmed_quality_issue" for row in rows
        ),
        "excluded_count": sum(
            row["prototype_status"] == "excluded_false_positive" for row in rows
        ),
        "not_assessable_count": sum(
            row["prototype_status"] == "not_assessable" for row in rows
        ),
        "portal_radius_m": args.portal_radius_m,
        "out_csv": str(out_csv),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
