from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from rcsd_topo_poc.modules.t12_frcsd_quality_audit.inputs import LoadedInputs
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_audit import (
    JunctionAuditResult,
    audit_junction_quality,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_inputs import (
    JunctionSources,
    T03CaseEvidence,
    load_junction_sources,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.junction_outputs import (
    write_junction_outputs,
)
from rcsd_topo_poc.modules.t12_frcsd_quality_audit.models import AuditConfig


POSITIVE_IDS = {
    "520394575",
    "622700016",
    "522008569",
    "522806716",
}
NEGATIVE_IDS = {
    "40338648",
    "613826647",
    "12777955",
    "523923800",
    "991243",
    "1514722",
    "1881692",
    "507831701",
    "520691911",
    "922217",
    "54265667",
    "502058682",
    "950770",
    "994202",
    "53679574",
    "620658564",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the T12 v10 real-data QGIS audit bundle."
    )
    parser.add_argument("--t03-data", required=True, type=Path)
    parser.add_argument("--t03-error-data", required=True, type=Path)
    parser.add_argument("--t03-run", required=True, type=Path)
    parser.add_argument("--t03-error-run", required=True, type=Path)
    parser.add_argument("--segment-run-root", required=True, type=Path)
    parser.add_argument("--segment", required=True, type=Path)
    parser.add_argument("--segment-swsd-roads", required=True, type=Path)
    parser.add_argument("--segment-swsd-nodes", required=True, type=Path)
    parser.add_argument("--segment-frcsd-roads", required=True, type=Path)
    parser.add_argument("--segment-frcsd-nodes", required=True, type=Path)
    parser.add_argument("--segment-rcsd-intersection", required=True, type=Path)
    parser.add_argument("--segment-drivezone", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    return parser


def _empty(crs: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "id": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


def _load_case(case_root: Path) -> LoadedInputs:
    nodes = gpd.read_file(case_root / "nodes.gpkg")
    roads = gpd.read_file(case_root / "roads.gpkg")
    frcsd_roads = gpd.read_file(case_root / "rcsdroad.gpkg")
    frcsd_nodes = gpd.read_file(case_root / "rcsdnode.gpkg")
    drivezone = gpd.read_file(case_root / "drivezone.gpkg")
    crs = str(nodes.crs)
    return LoadedInputs(
        segments=_empty(crs),
        swsd_roads=roads,
        swsd_nodes=nodes,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        rcsd_intersections=_empty(crs),
        drivezone=drivezone,
        t05_anchor_audit=pd.DataFrame(),
        t06_cross_evidence={},
        processing_crs=crs,
        crop_inner_geometry=None,
        input_audit={},
        topology_audit={},
        evidence_audit={},
    )


def _audit_case(
    case: T03CaseEvidence,
    source: JunctionSources,
    case_root: Path,
) -> tuple[JunctionAuditResult, LoadedInputs]:
    loaded = _load_case(case_root)
    single_source = JunctionSources(
        t03_cases=(case,),
        t07_rows=(),
        t03_eligibility_nodes_path=None,
        audit=source.audit,
    )
    return (
        audit_junction_quality(
            loaded,
            single_source,
            AuditConfig(),
            run_id="t12_v10_real_junction_audit",
        ),
        loaded,
    )


def _combine_results(
    selected: dict[str, tuple[JunctionAuditResult, LoadedInputs, Path]],
) -> JunctionAuditResult:
    candidates: list[dict[str, Any]] = []
    confirmed: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    layers: dict[str, list[dict[str, Any]]] = {
        "junction_candidates": [],
        "support_roads": [],
        "target_projections": [],
        "frcsd_endpoints": [],
        "t07_conflict_links": [],
    }
    for candidate_id in sorted(selected):
        result = selected[candidate_id][0]
        candidates.extend(result.candidates)
        confirmed.extend(result.confirmed)
        exclusions.extend(result.exclusions)
        for layer_name in layers:
            layers[layer_name].extend(result.layers.get(layer_name) or [])
    counts = {
        "candidate_count": len(candidates),
        "confirmed_count": len(confirmed),
        "exclusion_count": len(exclusions),
        "t07_ignored_row_count": 0,
        "t07_step3_cardinality_import_count": 0,
    }
    return JunctionAuditResult(
        candidates=candidates,
        confirmed=confirmed,
        exclusions=exclusions,
        layers=layers,
        audit={
            "counts": counts,
            "by_issue_type": dict(
                sorted(Counter(row["issue_type"] for row in confirmed).items())
            ),
            "silent_fix": False,
        },
    )


def _with_case_id(frame: gpd.GeoDataFrame, case_id: str) -> gpd.GeoDataFrame:
    result = frame.copy()
    result["source_case_id"] = case_id
    return result


def _deduplicate(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    for field in ("id", "ID", "nodeid", "roadid"):
        if field in frame.columns:
            return frame.drop_duplicates(subset=[field], keep="first")
    return frame


def _write_gpkg(path: Path, layers: list[tuple[str, gpd.GeoDataFrame]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    for index, (layer_name, frame) in enumerate(layers):
        frame.to_file(
            path,
            layer=layer_name,
            driver="GPKG",
            mode="w" if index == 0 else "a",
        )


def _merge_original_junction_inputs(
    selected: dict[str, tuple[JunctionAuditResult, LoadedInputs, Path]],
    out_root: Path,
) -> tuple[Path, Path]:
    sources: dict[str, list[gpd.GeoDataFrame]] = {
        "original_swsd_roads": [],
        "original_swsd_nodes": [],
        "original_drivezone": [],
        "original_frcsd_rcsdroad": [],
        "original_frcsd_rcsdnode": [],
    }
    for candidate_id in sorted(selected):
        result, loaded, _ = selected[candidate_id]
        case_id = result.candidates[0]["junction_id"]
        sources["original_swsd_roads"].append(
            _with_case_id(loaded.swsd_roads, case_id)
        )
        sources["original_swsd_nodes"].append(
            _with_case_id(loaded.swsd_nodes, case_id)
        )
        sources["original_drivezone"].append(
            _with_case_id(loaded.drivezone, case_id)
        )
        sources["original_frcsd_rcsdroad"].append(
            _with_case_id(loaded.frcsd_roads, case_id)
        )
        sources["original_frcsd_rcsdnode"].append(
            _with_case_id(loaded.frcsd_nodes, case_id)
        )
    merged = {
        name: _deduplicate(
            gpd.GeoDataFrame(
                pd.concat(frames, ignore_index=True),
                geometry="geometry",
                crs=frames[0].crs,
            )
        )
        for name, frames in sources.items()
    }
    combined_path = out_root / "t12_junction_original_swsd_frcsd_inputs.gpkg"
    _write_gpkg(combined_path, list(merged.items()))
    drivezone_path = out_root / "t12_junction_original_drivezone.gpkg"
    _write_gpkg(drivezone_path, [("original_drivezone", merged["original_drivezone"])])
    return combined_path, drivezone_path


def _copy_segment_inputs(
    args: argparse.Namespace,
    out_root: Path,
) -> tuple[Path, Path, Path]:
    inputs = [
        ("original_segment", gpd.read_file(args.segment)),
        ("original_swsd_roads", gpd.read_file(args.segment_swsd_roads)),
        ("original_swsd_nodes", gpd.read_file(args.segment_swsd_nodes)),
        ("original_frcsd_rcsdroad", gpd.read_file(args.segment_frcsd_roads)),
        ("original_frcsd_rcsdnode", gpd.read_file(args.segment_frcsd_nodes)),
        (
            "original_rcsd_intersection",
            gpd.read_file(args.segment_rcsd_intersection),
        ),
        ("original_drivezone", gpd.read_file(args.segment_drivezone)),
    ]
    combined_path = out_root / "t12_segment_original_swsd_frcsd_inputs.gpkg"
    _write_gpkg(combined_path, inputs)
    drivezone_path = out_root / "t12_segment_original_drivezone.gpkg"
    _write_gpkg(drivezone_path, [("original_drivezone", inputs[-1][1])])
    segment_reference = inputs[0][1].copy()
    segment_reference.geometry = segment_reference.geometry.buffer(1.0)
    segment_reference_path = (
        out_root / "t12_segment_original_segment_1m_buffer.gpkg"
    )
    _write_gpkg(
        segment_reference_path,
        [("original_segment_1m_buffer", segment_reference)],
    )
    return combined_path, drivezone_path, segment_reference_path


def _copy_segment_outputs(segment_run_root: Path, out_root: Path) -> dict[str, Path]:
    names = (
        "t12_frcsd_quality_audit_manifest.json",
        "t12_frcsd_quality_audit_summary.json",
        "t12_frcsd_quality_candidates.csv",
        "t12_frcsd_quality_candidates.gpkg",
        "t12_frcsd_confirmed_quality_issues.csv",
        "t12_frcsd_confirmed_quality_issues.gpkg",
        "t12_frcsd_quality_review_exclusions.csv",
        "t12_frcsd_quality_manual_review_required.csv",
        "t12_frcsd_carrier_evidence.gpkg",
        "t12_frcsd_quality_report.md",
    )
    copied: dict[str, Path] = {}
    for name in names:
        source = segment_run_root / name
        target = out_root / name
        if not source.is_file():
            raise FileNotFoundError(source)
        if target.exists():
            raise FileExistsError(target)
        shutil.copy2(source, target)
        copied[name] = target
    return copied


def _fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def main() -> int:
    args = _parser().parse_args()
    out_root = args.out_root.resolve()
    if out_root.exists():
        raise FileExistsError(out_root)
    out_root.mkdir(parents=True)
    requested_ids = POSITIVE_IDS | NEGATIVE_IDS
    selected: dict[str, tuple[JunctionAuditResult, LoadedInputs, Path]] = {}
    source_records: list[dict[str, Any]] = []
    for source_name, data_root, run_root in (
        ("T03", args.t03_data.resolve(), args.t03_run.resolve()),
        (
            "T03_Error",
            args.t03_error_data.resolve(),
            args.t03_error_run.resolve(),
        ),
    ):
        source = load_junction_sources(t03_run_root=run_root)
        for case in source.t03_cases:
            if case.case_id not in requested_ids:
                continue
            case_root = data_root / case.case_id
            if not case_root.is_dir():
                raise FileNotFoundError(case_root)
            result, loaded = _audit_case(case, source, case_root)
            source_records.append(
                {
                    "source": source_name,
                    "case_id": case.case_id,
                    "candidate_count": len(result.candidates),
                    "confirmed_count": len(result.confirmed),
                    "exclusion_count": len(result.exclusions),
                }
            )
            for row in result.candidates:
                selected[row["candidate_id"]] = (result, loaded, case_root)

    combined = _combine_results(selected)
    if (
        len(combined.candidates),
        len(combined.confirmed),
        len(combined.exclusions),
    ) != (16, 4, 12):
        raise RuntimeError(
            "real Junction baseline mismatch: "
            f"{len(combined.candidates)}/"
            f"{len(combined.confirmed)}/"
            f"{len(combined.exclusions)}"
        )
    expected_types = {
        "520394575": "junction_unmatched_support_topology",
        "622700016": "junction_unmatched_support_topology",
        "522008569": "junction_required_topology_missing",
        "522806716": "junction_required_topology_missing",
    }
    actual_types = {
        row["junction_id"]: row["issue_type"] for row in combined.confirmed
    }
    if actual_types != expected_types:
        raise RuntimeError(f"real Junction type mismatch: {actual_types}")

    junction_paths = write_junction_outputs(
        run_root=out_root,
        processing_crs="EPSG:3857",
        result=combined,
    )
    junction_inputs, junction_drivezone = _merge_original_junction_inputs(
        selected,
        out_root,
    )
    segment_inputs, segment_drivezone, segment_reference = _copy_segment_inputs(
        args,
        out_root,
    )
    segment_outputs = _copy_segment_outputs(
        args.segment_run_root.resolve(),
        out_root,
    )
    segment_summary = json.loads(
        (args.segment_run_root / "t12_frcsd_quality_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    segment_counts = segment_summary["counts"]
    if (
        segment_counts["candidate_count"],
        segment_counts["confirmed_quality_issue_count"],
        segment_counts["review_exclusion_count"],
        segment_counts["manual_review_required_count"],
    ) != (63, 10, 53, 0):
        raise RuntimeError(f"Segment baseline mismatch: {segment_counts}")

    report = {
        "schema_version": "2026-08-01.t12_real_qgis_audit.v1",
        "status": "passed",
        "junction": {
            "counts": combined.audit["counts"],
            "by_issue_type": combined.audit["by_issue_type"],
            "expected_types": expected_types,
            "source_records": source_records,
            "outputs": {name: str(path) for name, path in junction_paths.items()},
        },
        "segment": {
            "source_run_root": str(args.segment_run_root.resolve()),
            "counts": {
                "candidate_count": segment_counts["candidate_count"],
                "confirmed_count": segment_counts[
                    "confirmed_quality_issue_count"
                ],
                "exclusion_count": segment_counts["review_exclusion_count"],
                "manual_count": segment_counts["manual_review_required_count"],
            },
            "copied_outputs": {
                name: _fingerprint(path) for name, path in segment_outputs.items()
            },
        },
        "inputs": {
            "junction_inputs": _fingerprint(junction_inputs),
            "junction_drivezone": _fingerprint(junction_drivezone),
            "segment_inputs": _fingerprint(segment_inputs),
            "segment_drivezone": _fingerprint(segment_drivezone),
            "segment_1m_buffer_reference": _fingerprint(segment_reference),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "geopandas": gpd.__version__,
        },
        "crs": "EPSG:3857",
        "overlay_reference_policy": {
            "junction": "original_drivezone_polygon",
            "segment": "original_swsd_segment_1m_audit_buffer",
            "segment_drivezone_role": "visual_context_only",
        },
        "silent_fix": False,
    }
    report_path = out_root / "t12_v10_real_audit_bundle_summary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "run_root": str(out_root),
                "junction": "16/4/12",
                "segment": "63/10/53/0",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
