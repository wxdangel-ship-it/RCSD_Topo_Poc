from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_target_disposition import (
    apply_target_disposition_contract,
)


def test_target_disposition_defaults_every_baseline_target_to_direct_build() -> None:
    segments, summary = apply_target_disposition_contract(
        _baseline(),
        {"contract_enabled": True},
        None,
        run_id="default",
    )

    baseline = segments[segments["baseline_target"]]
    assert len(baseline) == 3
    assert baseline["direct_build_required"].all()
    assert set(baseline["direct_build_eligibility"]) == {"direct_build_required"}
    assert summary["baseline_target_count"] == 3
    assert summary["direct_build_required_count"] == 3
    assert summary["target_disposition_manifest_applied"] is False


def test_target_disposition_keeps_baseline_but_reduces_direct_build_denominator(
    tmp_path: Path,
) -> None:
    manifest = _write_manifest(
        tmp_path,
        [
            _entry("core-b", "patch_data_insufficient"),
            _entry("right", "reality_change"),
        ],
    )

    segments, summary = apply_target_disposition_contract(
        _baseline(),
        {"contract_enabled": True},
        manifest,
        run_id="overlay",
    )

    rows = segments.set_index("segment_id")
    assert int(segments["baseline_target"].sum()) == 3
    assert bool(rows.loc["core-a", "direct_build_required"])
    assert not bool(rows.loc["core-b", "direct_build_required"])
    assert not bool(rows.loc["right", "direct_build_required"])
    assert summary["baseline_target_count"] == 3
    assert summary["direct_build_required_count"] == 1
    assert summary["patch_data_insufficient_count"] == 1
    assert summary["reality_change_count"] == 1
    assert len(summary["target_disposition_manifest_sha256"]) == 64


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            [
                {
                    "segment_id": "outside",
                    "direct_build_eligibility": "patch_data_insufficient",
                    "reason_codes": ["confirmed_exception"],
                    "evidence_ids": ["audit:outside"],
                    "approval_state": "confirmed",
                    "classification_source": "business_review",
                    "reviewed_by": "user",
                }
            ],
            "not in BaselineCohort",
        ),
        (
            [
                {
                    "segment_id": "core-a",
                    "direct_build_eligibility": "patch_data_insufficient",
                    "reason_codes": ["confirmed_exception"],
                    "evidence_ids": ["audit:core-a"],
                    "approval_state": "confirmed",
                    "classification_source": "business_review",
                    "reviewed_by": "user",
                },
                {
                    "segment_id": "core-a",
                    "direct_build_eligibility": "reality_change",
                    "reason_codes": ["confirmed_exception"],
                    "evidence_ids": ["audit:core-a"],
                    "approval_state": "confirmed",
                    "classification_source": "business_review",
                    "reviewed_by": "user",
                },
            ],
            "duplicate segment_id",
        ),
        (
            [
                {
                    "segment_id": "core-a",
                    "direct_build_eligibility": "patch_data_insufficient",
                    "reason_codes": ["confirmed_exception"],
                    "evidence_ids": [],
                    "approval_state": "confirmed",
                    "classification_source": "business_review",
                    "reviewed_by": "user",
                }
            ],
            "evidence_ids",
        ),
    ],
)
def test_target_disposition_rejects_unreviewable_exceptions(
    tmp_path: Path,
    entries: list[dict[str, object]],
    message: str,
) -> None:
    manifest = _write_manifest(tmp_path, entries)

    with pytest.raises(ValueError, match=message):
        apply_target_disposition_contract(
            _baseline(),
            {"contract_enabled": True},
            manifest,
            run_id="invalid",
        )


def _baseline() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            _target("core-a", "core_trunk", True, 0),
            _target("core-b", "core_trunk", True, 10),
            _target("right", "advance_right", True, 20),
            _target("other", "not_target", False, 30),
        ],
        crs="EPSG:32650",
    )


def _target(
    segment_id: str,
    target_class: str,
    target_required: bool,
    x: float,
) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "target_class": target_class,
        "target_required": target_required,
        "geometry": LineString([(x, 0), (x + 5, 0)]),
    }


def _entry(segment_id: str, eligibility: str) -> dict[str, object]:
    return {
        "segment_id": segment_id,
        "direct_build_eligibility": eligibility,
        "reason_codes": ["confirmed_exception"],
        "evidence_ids": [f"audit:{segment_id}"],
        "approval_state": "confirmed",
        "classification_source": "business_review",
        "reviewed_by": "user",
    }


def _write_manifest(
    tmp_path: Path,
    entries: list[dict[str, object]],
) -> Path:
    path = tmp_path / "target-disposition.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": "p04-target-disposition-v1",
                "status": "confirmed",
                "default_direct_build_eligibility": "direct_build_required",
                "baseline_cohort_count": 3,
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )
    return path
