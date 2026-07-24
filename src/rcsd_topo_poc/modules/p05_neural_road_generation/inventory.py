from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    DataAnomaly,
    EXPECTED_POC_DATA_ROOT,
    M0Config,
    REGISTERED_FAMILIES,
    TrainingSample,
    sha256_file,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _canonical_path(path: Path) -> Path:
    return normalize_runtime_path(path).resolve(strict=False)


def _same_path(first: Path, second: Path) -> bool:
    return str(_canonical_path(first)).casefold() == str(_canonical_path(second)).casefold()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _sample_id(family: str, business_id: str, manifest_hash: str) -> str:
    family_token = family.casefold().replace("-", "_")
    return f"{family_token}:{business_id}:{manifest_hash[:12]}"


def _stable_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _single_point_sample(family: str, case_root: Path, manifest_path: Path) -> TrainingSample:
    manifest = _read_json(manifest_path)
    business_id = str(manifest.get("mainnodeid") or "").strip()
    if not business_id:
        raise ValueError("manifest.mainnodeid is required")
    manifest_hash = sha256_file(manifest_path)
    return TrainingSample(
        sample_id=_sample_id(family, business_id, manifest_hash),
        family=family,
        business_id=business_id,
        sample_group_id=f"junction:{business_id}",
        scope_type="single_junction_object",
        case_root=str(case_root.resolve()),
        manifest_path=str(manifest_path.resolve()),
        manifest_sha256=manifest_hash,
        target_weight=1.0,
        context_weight=0.3,
        task_mask={"object_scene": True, "road_graph": False},
        task_mask_reasons={
            "object_scene": "target object manually confirmed or corrected",
            "road_graph": "no traceable historical T06 Road/Node artifact in the single-point package",
        },
        source_metadata={
            "bundle_mode": manifest.get("bundle_mode", "single_case"),
            "epsg": manifest.get("epsg"),
            "feature_counts": manifest.get("feature_counts", {}),
            "declared_checksums": manifest.get("checksum", {}),
        },
    )


def _organization_records(root: Path) -> tuple[dict[str, dict[str, Any]], Path | None]:
    path = root / "_t10_case_organization_manifest.json"
    if not path.is_file():
        return {}, None
    payload = _read_json(path)
    records: dict[str, dict[str, Any]] = {}
    for item in payload.get("cases", []):
        if isinstance(item, dict) and item.get("case_id") is not None:
            records[str(item["case_id"])] = item
    return records, path


def _t10_case_sample(
    family: str,
    case_root: Path,
    organization: dict[str, dict[str, Any]],
    organization_path: Path | None,
) -> tuple[TrainingSample, DataAnomaly | None]:
    manifest_path = case_root / "t10_case_evidence_manifest.json"
    fallback_anomaly: DataAnomaly | None = None
    if manifest_path.is_file():
        payload = _read_json(manifest_path)
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        business_id = str(scope.get("case_id") or scope.get("swsd_semantic_junction_id") or case_root.name)
        manifest_hash = sha256_file(manifest_path)
        source_metadata = {
            "package_id": payload.get("package_id"),
            "package_type": payload.get("package_type") or "t10_case_evidence",
            "scope": scope,
        }
    else:
        record = organization.get(case_root.name)
        if record is None or organization_path is None:
            raise ValueError("case evidence manifest and organization record are both missing")
        business_id = str(record.get("case_id") or case_root.name)
        manifest_path = organization_path
        manifest_hash = _stable_json_sha256(record)
        source_metadata = {"organization_record": record, "package_type": "t10_case_organization_fallback"}
        fallback_anomaly = DataAnomaly(
            severity="warning",
            category="organization_manifest_fallback",
            detail="directory-level evidence manifest is missing; the explicit organization record is used",
            family=family,
            business_id=business_id,
            path=str(case_root.resolve()),
        )
    return (
        TrainingSample(
            sample_id=_sample_id(family, business_id, manifest_hash),
            family=family,
            business_id=business_id,
            sample_group_id=f"case:{business_id}",
            scope_type="t10_case",
            case_root=str(case_root.resolve()),
            manifest_path=str(manifest_path.resolve()),
            manifest_sha256=manifest_hash,
            target_weight=0.7,
            context_weight=0.7,
            task_mask={"object_scene": True, "road_graph": False},
            task_mask_reasons={
                "object_scene": "whole Case manually checked",
                "road_graph": "pending canonical T06 Road/Node lineage",
            },
            source_metadata=source_metadata,
        ),
        fallback_anomaly,
    )


def _t10_segment_sample(family: str, case_root: Path, manifest_path: Path) -> TrainingSample:
    payload = _read_json(manifest_path)
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    segment_properties = scope.get("segment_properties") if isinstance(scope.get("segment_properties"), dict) else {}
    business_id = str(scope.get("swsd_segment_id") or segment_properties.get("id") or "").strip()
    if not business_id:
        raise ValueError("scope.swsd_segment_id is required")
    if str(scope.get("scope_type") or "") != "swsd_segment":
        raise ValueError("scope.scope_type must be swsd_segment")
    manifest_hash = sha256_file(manifest_path)
    return TrainingSample(
        sample_id=_sample_id(family, business_id, manifest_hash),
        family=family,
        business_id=business_id,
        sample_group_id=f"segment:{business_id}",
        scope_type="t10_segment",
        case_root=str(case_root.resolve()),
        manifest_path=str(manifest_path.resolve()),
        manifest_sha256=manifest_hash,
        target_weight=0.7,
        context_weight=0.3,
        task_mask={"object_scene": True, "road_graph": False},
        task_mask_reasons={
            "object_scene": "specified Segment Case manually checked",
            "road_graph": "pending canonical T06 Road/Node lineage",
        },
        source_metadata={
            "package_id": payload.get("package_id"),
            "package_type": payload.get("package_type"),
            "scope": scope,
        },
    )


def scan_training_samples(config: M0Config) -> tuple[list[TrainingSample], list[DataAnomaly]]:
    root = _canonical_path(config.poc_data_root)
    if config.enforce_poc_scope and not _same_path(root, EXPECTED_POC_DATA_ROOT):
        raise ValueError(f"P05 M0 scope violation: expected {EXPECTED_POC_DATA_ROOT}, got {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"POC data root does not exist: {root}")

    samples: list[TrainingSample] = []
    anomalies: list[DataAnomaly] = []
    for family in REGISTERED_FAMILIES:
        family_root = root / family
        if not family_root.is_dir():
            anomalies.append(DataAnomaly("error", "missing_family_root", "registered family root is missing", family, path=str(family_root)))
            continue
        case_dirs = sorted(
            (path for path in family_root.iterdir() if path.is_dir() and not path.name.startswith("_")),
            key=lambda path: path.name.casefold(),
        )
        organization, organization_path = _organization_records(family_root) if family == "T10" else ({}, None)
        for case_root in case_dirs:
            try:
                if family.startswith("T03") or family.startswith("T04"):
                    manifest_path = case_root / "manifest.json"
                    if not manifest_path.is_file():
                        raise FileNotFoundError("manifest.json is missing")
                    samples.append(_single_point_sample(family, case_root, manifest_path))
                elif family == "T10":
                    sample, anomaly = _t10_case_sample(family, case_root, organization, organization_path)
                    samples.append(sample)
                    if anomaly is not None:
                        anomalies.append(anomaly)
                else:
                    manifest_path = case_root / "t10_case_evidence_manifest.json"
                    if not manifest_path.is_file():
                        raise FileNotFoundError("t10_case_evidence_manifest.json is missing")
                    samples.append(_t10_segment_sample(family, case_root, manifest_path))
            except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                anomalies.append(
                    DataAnomaly(
                        severity="error",
                        category="invalid_case_manifest",
                        detail=str(exc),
                        family=family,
                        business_id=case_root.name,
                        path=str(case_root.resolve()),
                    )
                )

    by_group: dict[str, list[TrainingSample]] = defaultdict(list)
    for sample in samples:
        by_group[sample.sample_group_id].append(sample)
    for group_id, versions in sorted(by_group.items()):
        hashes = {sample.manifest_sha256 for sample in versions}
        if len(versions) > 1 and len(hashes) > 1:
            anomalies.append(
                DataAnomaly(
                    severity="warning",
                    category="multiple_archived_versions",
                    detail=f"{len(versions)} versions with {len(hashes)} distinct manifest hashes share {group_id}",
                    business_id=group_id.split(":", 1)[-1],
                    path=";".join(sample.case_root for sample in versions),
                )
            )
    samples.sort(key=lambda sample: (sample.family.casefold(), sample.business_id, sample.sample_id))
    anomalies.sort(key=lambda item: (item.severity, item.category, item.family, item.business_id, item.path))
    return samples, anomalies


__all__ = ["scan_training_samples"]
