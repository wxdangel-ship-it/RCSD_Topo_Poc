from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
from pyproj import CRS

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


EXPECTED_EPSG = 3857
REQUIRED_INPUTS = (
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdnode.gpkg",
    "rcsdroad.gpkg",
    "drivezone.gpkg",
)
OPTIONAL_INPUTS = ("divstripzone.gpkg",)


@dataclass(frozen=True)
class JunctionGoldRoot:
    root: Path
    family: str
    source_scope: str
    label_weight: float = 1.0


DEFAULT_GOLD_ROOTS = (
    JunctionGoldRoot(Path(r"E:\TestData\POC_Data\T03"), "T03", "POC_Data"),
    JunctionGoldRoot(
        Path(r"E:\TestData\POC_Data\T03_Error"),
        "T03_Error",
        "POC_Data",
    ),
    JunctionGoldRoot(Path(r"E:\TestData\POC_Data\T04"), "T04", "POC_Data"),
    JunctionGoldRoot(
        Path(r"E:\TestData\POC_Data\T04_Error"),
        "T04_Error",
        "POC_Data",
    ),
    JunctionGoldRoot(
        Path(r"E:\TestData\POC_QA\T03_Error"),
        "T03_Error",
        "POC_QA",
    ),
)


@dataclass(frozen=True)
class JunctionGoldSource:
    source_index: int
    case_id: str
    family: str
    source_scope: str
    case_root: str
    manifest_path: str
    manifest_sha256: str
    input_fingerprint: str
    input_sha256: Mapping[str, str]
    label_weight: float
    status: str
    issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class JunctionGoldCase:
    case_id: str
    sample_group_id: str
    status: str
    selected_source_index: int | None
    selected_case_root: str | None
    input_fingerprint: str | None
    families: tuple[str, ...]
    source_scopes: tuple[str, ...]
    source_indices: tuple[int, ...]
    exact_duplicate_count: int
    distinct_input_version_count: int
    label_weight: float


@dataclass(frozen=True)
class JunctionGoldAnomaly:
    severity: str
    category: str
    case_id: str
    path: str
    detail: str


def scan_junction_gold_inventory(
    roots: Sequence[JunctionGoldRoot] = DEFAULT_GOLD_ROOTS,
    *,
    verify_declared_checksums: bool = True,
    verify_vector_crs: bool = True,
) -> tuple[
    tuple[JunctionGoldSource, ...],
    tuple[JunctionGoldCase, ...],
    tuple[JunctionGoldAnomaly, ...],
    dict[str, Any],
]:
    sources: list[JunctionGoldSource] = []
    anomalies: list[JunctionGoldAnomaly] = []
    for root_spec in roots:
        root = normalize_runtime_path(root_spec.root).resolve(strict=False)
        if not root.is_dir():
            anomalies.append(
                JunctionGoldAnomaly(
                    "error",
                    "missing_gold_root",
                    "",
                    str(root),
                    f"authorized Gold root is missing: {root_spec.family}",
                )
            )
            continue
        case_dirs = sorted(
            (
                path
                for path in root.iterdir()
                if path.is_dir() and not path.name.startswith("_")
            ),
            key=lambda path: path.name.casefold(),
        )
        for case_root in case_dirs:
            source, source_anomalies = _scan_source(
                source_index=len(sources),
                root_spec=root_spec,
                case_root=case_root,
                verify_declared_checksums=verify_declared_checksums,
                verify_vector_crs=verify_vector_crs,
            )
            sources.append(source)
            anomalies.extend(source_anomalies)

    cases, group_anomalies = _group_sources(sources)
    anomalies.extend(group_anomalies)
    sources.sort(key=lambda row: row.source_index)
    cases.sort(key=lambda row: row.case_id)
    anomalies.sort(
        key=lambda row: (row.severity, row.category, row.case_id, row.path)
    )
    summary = _inventory_summary(sources, cases, anomalies, roots)
    return tuple(sources), tuple(cases), tuple(anomalies), summary


def write_junction_gold_inventory(
    *,
    output_root: Path,
    roots: Sequence[JunctionGoldRoot] = DEFAULT_GOLD_ROOTS,
    verify_declared_checksums: bool = True,
    verify_vector_crs: bool = True,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources, cases, anomalies, summary = scan_junction_gold_inventory(
        roots,
        verify_declared_checksums=verify_declared_checksums,
        verify_vector_crs=verify_vector_crs,
    )
    artifacts = {
        "sources": output / "junction_gold_sources.jsonl",
        "cases": output / "junction_gold_cases.jsonl",
        "anomalies": output / "junction_gold_anomalies.jsonl",
    }
    _write_jsonl(artifacts["sources"], (asdict(row) for row in sources))
    _write_jsonl(artifacts["cases"], (asdict(row) for row in cases))
    _write_jsonl(artifacts["anomalies"], (asdict(row) for row in anomalies))
    result = {
        **summary,
        "artifacts": {
            role: {
                "path": str(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for role, path in artifacts.items()
        },
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _scan_source(
    *,
    source_index: int,
    root_spec: JunctionGoldRoot,
    case_root: Path,
    verify_declared_checksums: bool,
    verify_vector_crs: bool,
) -> tuple[JunctionGoldSource, list[JunctionGoldAnomaly]]:
    manifest_path = case_root / "manifest.json"
    issues: list[str] = []
    anomalies: list[JunctionGoldAnomaly] = []
    manifest: dict[str, Any] = {}
    if not manifest_path.is_file():
        issues.append("missing_manifest")
        case_id = case_root.name
        manifest_sha256 = ""
    else:
        manifest_sha256 = sha256_file(manifest_path)
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("manifest root is not an object")
            manifest = payload
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append("invalid_manifest")
            anomalies.append(
                _anomaly("error", "invalid_manifest", case_root.name, manifest_path, str(exc))
            )
        case_id = str(manifest.get("mainnodeid") or case_root.name).strip()
        if not str(manifest.get("mainnodeid") or "").strip():
            issues.append("missing_mainnodeid")
        if case_id != case_root.name:
            issues.append("case_id_directory_mismatch")

    files = {path.name.casefold(): path for path in case_root.iterdir() if path.is_file()}
    declared = {
        str(name).casefold(): str(value).lower()
        for name, value in (manifest.get("checksum") or {}).items()
        if str(value).strip()
    }
    decoded_output = (
        manifest.get("decoded_output")
        if isinstance(manifest.get("decoded_output"), dict)
        else {}
    )
    declared_checksums_are_predecode = bool(
        decoded_output.get("bundle_internal_vectors_localized")
    ) and str(decoded_output.get("vector_crs") or "") == "EPSG:3857"
    input_hashes: dict[str, str] = {}
    for filename in (*REQUIRED_INPUTS, *OPTIONAL_INPUTS):
        path = files.get(filename.casefold())
        required = filename in REQUIRED_INPUTS
        if path is None:
            if required:
                issues.append(f"missing_input:{filename}")
            continue
        digest = sha256_file(path)
        input_hashes[filename] = digest
        expected = declared.get(filename.casefold())
        if (
            verify_declared_checksums
            and not declared_checksums_are_predecode
            and expected != digest
        ):
            issues.append(f"checksum_mismatch:{filename}")
        if verify_vector_crs:
            try:
                epsg = _vector_epsg(path)
            except (OSError, RuntimeError, ValueError) as exc:
                issues.append(f"crs_unreadable:{filename}")
                anomalies.append(
                    _anomaly("error", "crs_unreadable", case_id, path, str(exc))
                )
            else:
                if epsg != EXPECTED_EPSG:
                    issues.append(f"crs_mismatch:{filename}")

    if manifest and int(manifest.get("epsg") or 0) != EXPECTED_EPSG:
        issues.append("manifest_epsg_mismatch")
    for issue in sorted(set(issues)):
        if not any(row.category == issue for row in anomalies):
            anomalies.append(
                _anomaly("error", issue, case_id, case_root, "Gold source is not consumable")
            )
    fingerprint = _input_fingerprint(input_hashes) if input_hashes else ""
    source = JunctionGoldSource(
        source_index=source_index,
        case_id=case_id,
        family=root_spec.family,
        source_scope=root_spec.source_scope,
        case_root=str(case_root.resolve()),
        manifest_path=str(manifest_path.resolve(strict=False)),
        manifest_sha256=manifest_sha256,
        input_fingerprint=fingerprint,
        input_sha256=dict(sorted(input_hashes.items())),
        label_weight=root_spec.label_weight,
        status="READY" if not issues else "SOURCE_INVALID",
        issue_codes=tuple(sorted(set(issues))),
    )
    return source, anomalies


def _group_sources(
    sources: Sequence[JunctionGoldSource],
) -> tuple[list[JunctionGoldCase], list[JunctionGoldAnomaly]]:
    by_case: dict[str, list[JunctionGoldSource]] = defaultdict(list)
    for source in sources:
        by_case[source.case_id].append(source)
    cases: list[JunctionGoldCase] = []
    anomalies: list[JunctionGoldAnomaly] = []
    for case_id, group in sorted(by_case.items()):
        valid = [row for row in group if row.status == "READY"]
        versions = sorted({row.input_fingerprint for row in valid})
        selected: JunctionGoldSource | None = None
        status = "SOURCE_INVALID"
        if len(versions) == 1:
            selected = min(valid, key=lambda row: row.source_index)
            status = "READY"
        elif len(versions) > 1:
            status = "LABEL_REVIEW"
            anomalies.append(
                JunctionGoldAnomaly(
                    "error",
                    "source_version_conflict",
                    case_id,
                    ";".join(row.case_root for row in valid),
                    f"{len(versions)} distinct raw input fingerprints share one Case ID",
                )
            )
        cases.append(
            JunctionGoldCase(
                case_id=case_id,
                sample_group_id=f"junction:{case_id}",
                status=status,
                selected_source_index=(selected.source_index if selected else None),
                selected_case_root=(selected.case_root if selected else None),
                input_fingerprint=(selected.input_fingerprint if selected else None),
                families=tuple(sorted({row.family for row in group})),
                source_scopes=tuple(sorted({row.source_scope for row in group})),
                source_indices=tuple(sorted(row.source_index for row in group)),
                exact_duplicate_count=max(0, len(valid) - len(versions)),
                distinct_input_version_count=len(versions),
                label_weight=1.0,
            )
        )
    return cases, anomalies


def _inventory_summary(
    sources: Sequence[JunctionGoldSource],
    cases: Sequence[JunctionGoldCase],
    anomalies: Sequence[JunctionGoldAnomaly],
    roots: Sequence[JunctionGoldRoot],
) -> dict[str, Any]:
    return {
        "schema_version": "p05-target-a-junction-gold-inventory-v1",
        "status": (
            "JUNCTION_GOLD_INVENTORY_GO"
            if not any(row.severity == "error" for row in anomalies)
            else "JUNCTION_GOLD_INVENTORY_REVIEW"
        ),
        "authorized_roots": [
            {
                "root": str(normalize_runtime_path(row.root).resolve(strict=False)),
                "family": row.family,
                "source_scope": row.source_scope,
                "label_weight": row.label_weight,
            }
            for row in roots
        ],
        "directory_record_count": len(sources),
        "unique_case_id_count": len(cases),
        "ready_case_count": sum(row.status == "READY" for row in cases),
        "label_review_case_count": sum(row.status == "LABEL_REVIEW" for row in cases),
        "source_invalid_case_count": sum(row.status == "SOURCE_INVALID" for row in cases),
        "exact_duplicate_source_count": sum(row.exact_duplicate_count for row in cases),
        "source_family_counts": dict(sorted(Counter(row.family for row in sources).items())),
        "case_status_counts": dict(sorted(Counter(row.status for row in cases).items())),
        "anomaly_counts": dict(sorted(Counter(row.category for row in anomalies).items())),
        "geometry_changed": False,
        "topology_changed": False,
        "silent_fix": False,
    }


def _vector_epsg(path: Path) -> int | None:
    layers = fiona.listlayers(path)
    if not layers:
        raise ValueError("GeoPackage contains no vector layer")
    epsg_values: set[int | None] = set()
    for layer in layers:
        with fiona.open(path, layer=layer) as source:
            crs_value = source.crs_wkt or source.crs
            epsg_values.add(CRS.from_user_input(crs_value).to_epsg() if crs_value else None)
    if len(epsg_values) != 1:
        raise ValueError(f"GeoPackage layers have different CRS: {sorted(epsg_values, key=str)}")
    return next(iter(epsg_values))


def _input_fingerprint(input_hashes: Mapping[str, str]) -> str:
    encoded = json.dumps(
        dict(sorted(input_hashes.items())),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _anomaly(
    severity: str,
    category: str,
    case_id: str,
    path: Path,
    detail: str,
) -> JunctionGoldAnomaly:
    return JunctionGoldAnomaly(severity, category, case_id, str(path.resolve()), detail)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            stream.write("\n")


__all__ = [
    "DEFAULT_GOLD_ROOTS",
    "EXPECTED_EPSG",
    "JunctionGoldAnomaly",
    "JunctionGoldCase",
    "JunctionGoldRoot",
    "JunctionGoldSource",
    "OPTIONAL_INPUTS",
    "REQUIRED_INPUTS",
    "scan_junction_gold_inventory",
    "write_junction_gold_inventory",
]
