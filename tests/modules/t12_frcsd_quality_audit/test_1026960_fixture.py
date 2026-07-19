from __future__ import annotations

from pathlib import Path

import pandas as pd


EXPECTED_CONFIRMED = {
    "1001432_1019757",
    "1019779_1026330",
    "1039319_1049250",
    "504597284_603597212",
    "612408195_991266",
    "84975803_1023802",
    "953923_953936",
    "991145_991164",
    "997356_1029576",
    "998051_501667982",
}

SUSPECTED_FALSE_POSITIVE_AUDIT_IDS = {
    "1520811_25466551",
    "1623512_508276240",
    "1629816_1643047",
    "1878482_1881808",
    "1881810_1898171",
    "1888260_1921768",
    "1908169_1921764",
    "1921739_1921764",
    "500636195_505415445",
    "722528_722529",
    "722569_12927873",
}


def test_1026960_review_fixture_is_complete_and_frozen() -> None:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "t12"
        / "1026960_review_decisions.csv"
    )
    frame = pd.read_csv(fixture, dtype=str).fillna("")

    assert len(frame) == 35
    assert frame["candidate_id"].is_unique
    assert set(
        frame.loc[
            frame["review_status"] == "confirmed_frcsd_quality_issue",
            "candidate_id",
        ]
    ) == EXPECTED_CONFIRMED
    assert (frame["review_status"] == "excluded_false_positive").sum() == 25
    assert (frame["review_status"] == "manual_review_required").sum() == 0
    confirmed = frame[frame["review_status"] == "confirmed_frcsd_quality_issue"]
    assert confirmed["issue_type"].value_counts().to_dict() == {
        "directed_carrier_missing": 8,
        "required_local_connectivity_missing": 2,
    }


def test_focus_ids_are_not_hardcoded_in_production_source() -> None:
    source_root = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "rcsd_topo_poc"
        / "modules"
        / "t12_frcsd_quality_audit"
    )
    production_text = "\n".join(
        path.read_text(encoding="utf-8") for path in source_root.rglob("*.py")
    )

    forbidden = set(EXPECTED_CONFIRMED) | SUSPECTED_FALSE_POSITIVE_AUDIT_IDS | {
        "1026960",
        "1001716_1010487",
        "1039488_1039490",
    }
    assert forbidden.isdisjoint(production_text.split())
    for object_id in forbidden:
        assert object_id not in production_text
