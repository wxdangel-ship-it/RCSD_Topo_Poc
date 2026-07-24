from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd

from .segment_first_skeleton import canonical_id


_CONTRACT_VERSION = "p04-target-disposition-v1"
_DEFAULT_ELIGIBILITY = "direct_build_required"
_EXCEPTION_ELIGIBILITIES = {
    "patch_data_insufficient",
    "reality_change",
}
_CONFIRMED_STATES = {"confirmed", "approved", "business_confirmed"}


def apply_target_disposition_contract(
    target_segments: gpd.GeoDataFrame,
    summary: dict[str, object],
    manifest_path: Path | None,
    *,
    run_id: str,
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    result = target_segments.copy()
    baseline_mask = result["target_required"].fillna(False).astype(bool)
    result["baseline_target"] = baseline_mask
    result["baseline_target_class"] = result["target_class"].where(
        baseline_mask,
        "",
    )
    result["direct_build_eligibility"] = ""
    result.loc[baseline_mask, "direct_build_eligibility"] = _DEFAULT_ELIGIBILITY
    result["direct_build_required"] = baseline_mask
    result["classification_reason_codes"] = ""
    result["classification_evidence_ids"] = ""
    result["classification_source"] = ""
    result["classification_reviewed_by"] = ""
    result["classification_manifest_hash"] = ""
    result["reality_change_clue_id"] = ""

    manifest_hash = ""
    manifest_applied = manifest_path is not None
    if manifest_path is not None:
        manifest, manifest_hash = _load_manifest(manifest_path)
        _validate_manifest_header(manifest, int(baseline_mask.sum()))
        baseline_ids = set(
            result.loc[baseline_mask, "segment_id"].map(canonical_id)
        )
        row_by_segment = {
            canonical_id(segment_id): index
            for index, segment_id in result["segment_id"].items()
        }
        seen: set[str] = set()
        for entry in manifest["entries"]:
            segment_id = canonical_id(entry.get("segment_id"))
            if not segment_id:
                raise ValueError(
                    "target disposition entry segment_id must be non-empty"
                )
            if segment_id in seen:
                raise ValueError(
                    f"target disposition duplicate segment_id: {segment_id}"
                )
            seen.add(segment_id)
            if segment_id not in baseline_ids:
                raise ValueError(
                    "target disposition segment is not in BaselineCohort: "
                    + segment_id
                )
            normalized = _validate_exception(entry, segment_id)
            index = row_by_segment[segment_id]
            for field, value in normalized.items():
                result.at[index, field] = value
            result.at[index, "classification_manifest_hash"] = manifest_hash

    result["direct_build_required"] = result[
        "direct_build_eligibility"
    ].eq(_DEFAULT_ELIGIBILITY) & result["baseline_target"]
    # Compatibility alias for existing P04 carrier-selection code.
    result["target_required"] = result["direct_build_required"]

    eligibility_counts = result.loc[
        result["baseline_target"],
        "direct_build_eligibility",
    ].value_counts()
    updated_summary = {
        **summary,
        "baseline_target_count": int(result["baseline_target"].sum()),
        "direct_build_required_count": int(
            result["direct_build_required"].sum()
        ),
        "patch_data_insufficient_count": int(
            eligibility_counts.get("patch_data_insufficient", 0)
        ),
        "reality_change_count": int(
            eligibility_counts.get("reality_change", 0)
        ),
        "target_disposition_manifest_applied": manifest_applied,
        "target_disposition_manifest_sha256": manifest_hash,
        "target_disposition_contract_version": (
            _CONTRACT_VERSION if manifest_applied else ""
        ),
        "run_id": run_id,
    }
    return result, updated_summary


def _load_manifest(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"invalid target disposition manifest: {path}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ValueError("target disposition manifest root must be an object")
    return manifest, hashlib.sha256(raw).hexdigest()


def _validate_manifest_header(
    manifest: dict[str, object],
    baseline_count: int,
) -> None:
    if manifest.get("contract_version") != _CONTRACT_VERSION:
        raise ValueError(
            "target disposition contract_version must be "
            + _CONTRACT_VERSION
        )
    if manifest.get("status") not in _CONFIRMED_STATES:
        raise ValueError("target disposition manifest status is not confirmed")
    if (
        manifest.get("default_direct_build_eligibility")
        != _DEFAULT_ELIGIBILITY
    ):
        raise ValueError(
            "target disposition default must be direct_build_required"
        )
    declared_count = manifest.get("baseline_cohort_count")
    if declared_count is not None and int(declared_count) != baseline_count:
        raise ValueError(
            "target disposition baseline_cohort_count does not match "
            f"computed BaselineCohort: {declared_count} != {baseline_count}"
        )
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("target disposition entries must be a list")


def _validate_exception(
    entry: object,
    segment_id: str,
) -> dict[str, str]:
    if not isinstance(entry, dict):
        raise ValueError("target disposition entry must be an object")
    eligibility = str(entry.get("direct_build_eligibility", "")).strip()
    if eligibility not in _EXCEPTION_ELIGIBILITIES:
        raise ValueError(
            "target disposition exception eligibility must be "
            "patch_data_insufficient or reality_change"
        )
    reason_codes = _non_empty_list(entry, "reason_codes", segment_id)
    evidence_ids = _non_empty_list(entry, "evidence_ids", segment_id)
    approval_state = str(entry.get("approval_state", "")).strip()
    if approval_state not in _CONFIRMED_STATES:
        raise ValueError(
            f"target disposition approval_state is not confirmed: {segment_id}"
        )
    classification_source = str(
        entry.get("classification_source", "")
    ).strip()
    reviewed_by = str(entry.get("reviewed_by", "")).strip()
    if not classification_source or not reviewed_by:
        raise ValueError(
            "target disposition classification_source/reviewed_by "
            f"must be non-empty: {segment_id}"
        )
    clue_id = str(entry.get("reality_change_clue_id", "")).strip()
    if eligibility == "reality_change" and not clue_id:
        clue_id = f"p04:reality_change:{segment_id}"
    return {
        "direct_build_eligibility": eligibility,
        "classification_reason_codes": ",".join(reason_codes),
        "classification_evidence_ids": ",".join(evidence_ids),
        "classification_source": classification_source,
        "classification_reviewed_by": reviewed_by,
        "reality_change_clue_id": clue_id,
    }


def _non_empty_list(
    entry: dict[str, object],
    field: str,
    segment_id: str,
) -> list[str]:
    value = entry.get(field)
    if (
        not isinstance(value, list)
        or not value
        or any(not str(item).strip() for item in value)
    ):
        raise ValueError(
            f"target disposition {field} must be non-empty: {segment_id}"
        )
    return [str(item).strip() for item in value]


__all__ = ["apply_target_disposition_contract"]
