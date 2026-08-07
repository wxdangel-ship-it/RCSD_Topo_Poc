from __future__ import annotations

import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping

import fiona
from shapely.geometry import shape


T04_KIND_BY_JUNCTION_TYPE = {
    "merge": 8,
    "diverge": 16,
    "complex_divmerge": 128,
}
T03_KIND_BY_TEMPLATE_CLASS = {
    "center_junction": 4,
    "single_sided_t_mouth": 2048,
}
VALID_REPLAY_STATUSES = {"SUCCESS", "NO_RCSD_EVIDENCE"}


@dataclass(frozen=True)
class JunctionGoldT05ReplayInputs:
    labels_path: Path
    poc_data_t04_relation_path: Path
    poc_data_t04_error_relation_path: Path


@dataclass(frozen=True)
class JunctionGoldT05ReplayRow:
    sample_id: str
    sample_group_id: str
    case_id: str
    family: str
    source_scope: str
    input_fingerprint: str
    status: str
    reason: str
    phase1_published_surface_count: int
    phase1_conflict_count: int
    phase1_skipped_count: int
    phase2_relation_count: int
    phase2_success_count: int
    phase2_failure_count: int
    scene: str
    action: str
    selected_main_rcsdnode_id: str
    original_rcsdroad_ids: tuple[str, ...]
    new_rcsdroad_ids: tuple[str, ...]
    original_rcsdnode_ids: tuple[str, ...]
    new_rcsdnode_ids: tuple[str, ...]
    grouped_rcsdnode_ids: tuple[str, ...]
    source_surface_path: str
    phase1_surface_path: str
    phase1_audit_path: str
    phase2_audit_path: str
    phase2_relation_path: str
    phase2_rcsdroad_path: str
    phase2_rcsdnode_path: str
    geometry_changed: bool
    topology_changed: bool
    silent_fix: bool
    elapsed_seconds: float


def write_junction_gold_t05_replay(
    *,
    inputs: JunctionGoldT05ReplayInputs,
    output_root: Path,
    workers: int = 4,
    progress_callback: Callable[[int, int, JunctionGoldT05ReplayRow], None]
    | None = None,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    labels = tuple(_read_jsonl(Path(inputs.labels_path)))
    accepted = tuple(
        row
        for row in labels
        if str(row.get("label_status")) == "READY"
        and str(row.get("surface_state")) == "accepted"
    )
    t04_relations = {
        ("POC_Data", "T04"): _relation_rows_by_target(
            inputs.poc_data_t04_relation_path
        ),
        ("POC_Data", "T04_Error"): _relation_rows_by_target(
            inputs.poc_data_t04_error_relation_path
        ),
    }
    empty_surface_path, empty_evidence_path = _write_empty_inputs(output)

    started = perf_counter()
    rows: list[JunctionGoldT05ReplayRow] = []
    max_workers = max(1, int(workers))
    if max_workers == 1:
        for label in accepted:
            row = _replay_one(
                label,
                output_root=output,
                empty_surface_path=empty_surface_path,
                empty_evidence_path=empty_evidence_path,
                t04_relations=t04_relations,
            )
            rows.append(row)
            _persist_case_row(output, row)
            if progress_callback is not None:
                progress_callback(len(rows), len(accepted), row)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _replay_one,
                    label,
                    output_root=output,
                    empty_surface_path=empty_surface_path,
                    empty_evidence_path=empty_evidence_path,
                    t04_relations=t04_relations,
                ): label
                for label in accepted
            }
            for future in as_completed(futures):
                label = futures[future]
                try:
                    row = future.result()
                except Exception as exc:  # per-Case quarantine is intentional
                    row = _failure_row(
                        label,
                        reason=f"{type(exc).__name__}: {exc}",
                        elapsed_seconds=0.0,
                    )
                rows.append(row)
                _persist_case_row(output, row)
                if progress_callback is not None:
                    progress_callback(len(rows), len(accepted), row)

    ordered = tuple(
        sorted(rows, key=lambda row: (row.case_id, row.family, row.sample_id))
    )
    ledger_path = output / "junction_gold_t05_replay.jsonl"
    _write_jsonl(ledger_path, (asdict(row) for row in ordered))
    status_counts = dict(sorted(Counter(row.status for row in ordered).items()))
    scene_counts = dict(
        sorted(Counter(row.scene for row in ordered if row.scene).items())
    )
    action_counts = dict(
        sorted(Counter(row.action for row in ordered if row.action).items())
    )
    summary = {
        "schema_version": "p05-target-a-junction-gold-t05-replay-v1",
        "status": (
            "JUNCTION_GOLD_T05_REPLAY_GO"
            if len(ordered) == len(accepted)
            and all(row.status in VALID_REPLAY_STATUSES for row in ordered)
            else "JUNCTION_GOLD_T05_REPLAY_REVIEW"
        ),
        "input_label_count": len(labels),
        "accepted_surface_count": len(accepted),
        "replay_row_count": len(ordered),
        "status_counts": status_counts,
        "scene_counts": scene_counts,
        "action_counts": action_counts,
        "phase2_relation_count": sum(row.phase2_relation_count for row in ordered),
        "phase2_success_count": sum(row.phase2_success_count for row in ordered),
        "phase2_failure_count": sum(row.phase2_failure_count for row in ordered),
        "geometry_changed_count": sum(row.geometry_changed for row in ordered),
        "silent_fix_count": sum(row.silent_fix for row in ordered),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "workers": max_workers,
        "artifacts": {
            "replay_ledger": _artifact(ledger_path),
            "empty_surface": _artifact(empty_surface_path),
            "empty_evidence": _artifact(empty_evidence_path),
        },
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def adapt_t03_surface_for_t05(
    *,
    source_surface_path: Path,
    case_id: str,
    output_path: Path,
) -> dict[str, Any]:
    source_path = Path(source_surface_path)
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_fingerprints: list[str] = []
    template_classes: set[str] = set()
    with fiona.open(source_path) as source:
        if source.crs.to_epsg() != 3857:
            raise ValueError(f"T03 surface CRS must be EPSG:3857: {source.crs}")
        schema = dict(source.schema)
        schema["properties"] = dict(schema["properties"])
        schema["properties"].update({"mainnodeid": "str", "kind_2": "int"})
        with fiona.open(
            target_path,
            "w",
            driver="GPKG",
            layer="t03_surface",
            schema=schema,
            crs=source.crs,
        ) as target:
            for feature in source:
                geometry = shape(feature["geometry"])
                if geometry.is_empty or not geometry.is_valid:
                    raise ValueError("T03 accepted surface geometry must be non-empty and valid")
                properties = dict(feature["properties"])
                acceptance = str(
                    properties.get("step7_state")
                    or properties.get("final_state")
                    or ""
                ).strip().lower()
                if acceptance and acceptance != "accepted":
                    raise ValueError(f"T03 surface is not formally accepted: {acceptance}")
                template_class = str(properties.get("template_class") or "").strip()
                kind_2 = T03_KIND_BY_TEMPLATE_CLASS.get(template_class)
                if kind_2 is None:
                    raise ValueError(
                        f"unsupported formal T03 template_class: {template_class or 'missing'}"
                    )
                source_fingerprints.append(_geometry_fingerprint(geometry))
                template_classes.add(template_class)
                properties.update({"mainnodeid": str(case_id), "kind_2": kind_2})
                target.write(
                    {
                        "type": "Feature",
                        "geometry": feature["geometry"],
                        "properties": properties,
                    }
                )

    output_fingerprints = _surface_geometry_fingerprints(target_path)
    if source_fingerprints != output_fingerprints:
        raise RuntimeError("T03 T05 adapter changed surface geometry")
    return {
        "source_surface_path": str(source_path),
        "output_surface_path": str(target_path),
        "feature_count": len(source_fingerprints),
        "template_classes": sorted(template_classes),
        "geometry_changed": False,
        "silent_fix": False,
        "mainnodeid": str(case_id),
    }


def adapt_t04_surface_for_t05(
    *,
    source_surface_path: Path,
    step7_status_path: Path,
    relation_row: Mapping[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    status_doc = _read_json(Path(step7_status_path))
    final_state = str(status_doc.get("final_state") or "").strip().lower()
    if final_state != "accepted":
        raise ValueError(f"T04 surface is not formally accepted: {final_state or 'missing'}")

    case_id = str(relation_row.get("target_id") or relation_row.get("case_id") or "").strip()
    junction_type = str(
        relation_row.get("junction_type") or relation_row.get("scene_type") or ""
    ).strip()
    kind_2 = T04_KIND_BY_JUNCTION_TYPE.get(junction_type)
    if not case_id or kind_2 is None:
        raise ValueError(
            "T04 relation evidence must provide target_id and a formal junction_type"
        )

    source_path = Path(source_surface_path)
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_fingerprints: list[str] = []
    with fiona.open(source_path) as source:
        if source.crs.to_epsg() != 3857:
            raise ValueError(f"T04 surface CRS must be EPSG:3857: {source.crs}")
        schema = dict(source.schema)
        schema["properties"] = dict(schema["properties"])
        schema["properties"].update(
            {
                "final_state": "str",
                "mainnodeid": "str",
                "patch_id": "str",
                "kind_2": "int",
            }
        )
        with fiona.open(
            target_path,
            "w",
            driver="GPKG",
            layer="t04_surface",
            schema=schema,
            crs=source.crs,
        ) as target:
            for feature in source:
                geometry = shape(feature["geometry"])
                if geometry.is_empty or not geometry.is_valid:
                    raise ValueError("T04 accepted surface geometry must be non-empty and valid")
                source_fingerprints.append(_geometry_fingerprint(geometry))
                properties = dict(feature["properties"])
                properties.update(
                    {
                        "final_state": final_state,
                        "mainnodeid": case_id,
                        "patch_id": str(relation_row.get("patch_id") or ""),
                        "kind_2": kind_2,
                    }
                )
                target.write(
                    {
                        "type": "Feature",
                        "geometry": feature["geometry"],
                        "properties": properties,
                    }
                )

    output_fingerprints = _surface_geometry_fingerprints(target_path)
    geometry_changed = source_fingerprints != output_fingerprints
    if geometry_changed:
        raise RuntimeError("T04 T05 adapter changed surface geometry")
    return {
        "source_surface_path": str(source_path),
        "output_surface_path": str(target_path),
        "feature_count": len(source_fingerprints),
        "geometry_changed": False,
        "silent_fix": False,
        "final_state": final_state,
        "mainnodeid": case_id,
        "patch_id": str(relation_row.get("patch_id") or ""),
        "kind_2": kind_2,
    }


def build_t03_relation_evidence(label: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "target_id": str(label["case_id"]),
        "case_id": str(label["case_id"]),
        "relation_state": str(label.get("relation_state") or ""),
        "status_suggested": (
            0 if str(label.get("anchor_business_state")) == "SUCCESS" else 1
        ),
        "base_id_candidate": _join_ids(label.get("selected_rcsd_node_ids")),
        "required_rcsdnode_ids": _join_ids(label.get("selected_rcsd_node_ids")),
        "selected_rcsdnode_ids": _join_ids(label.get("selected_rcsd_node_ids")),
        "required_rcsdroad_ids": _join_ids(label.get("selected_rcsd_road_ids")),
        "selected_rcsdroad_ids": _join_ids(label.get("selected_rcsd_road_ids")),
        "support_rcsdroad_ids": _join_ids(label.get("support_rcsd_road_ids")),
        "junction_type": "virtual_junction",
    }


def _replay_one(
    label: Mapping[str, Any],
    *,
    output_root: Path,
    empty_surface_path: Path,
    empty_evidence_path: Path,
    t04_relations: Mapping[tuple[str, str], Mapping[str, Mapping[str, Any]]],
) -> JunctionGoldT05ReplayRow:
    started = perf_counter()
    sample_root = output_root / "cases" / _sample_directory_name(label)
    sample_root.mkdir(parents=True, exist_ok=True)
    family = str(label["family"])
    case_id = str(label["case_id"])
    case_root = Path(str(label["case_root"]))
    source_surface_path = Path(str(label["surface_geometry_path"]))
    _validate_accepted_surface(source_surface_path)
    nodes_path = _required_case_file(case_root, "nodes.gpkg")
    rcsdroad_path = _required_case_file(case_root, "rcsdroad.gpkg")
    rcsdnode_path = _required_case_file(case_root, "rcsdnode.gpkg")

    t03_surface_path: Path | None = None
    t04_surface_path: Path | None = None
    t03_evidence_path = empty_evidence_path
    t04_evidence_path = empty_evidence_path
    if family in {"T03", "T03_Error"}:
        t03_surface_path = sample_root / "t03_surface.gpkg"
        adapt_t03_surface_for_t05(
            source_surface_path=source_surface_path,
            case_id=case_id,
            output_path=t03_surface_path,
        )
        t03_evidence_path = sample_root / "t03_relation_evidence.json"
        _write_json_rows(t03_evidence_path, [build_t03_relation_evidence(label)])
    elif family in {"T04", "T04_Error"}:
        relation = t04_relations.get(
            (str(label["source_scope"]), family), {}
        ).get(case_id)
        if relation is None:
            raise ValueError(f"missing formal T04 relation evidence for {case_id}")
        t04_surface_path = sample_root / "t04_surface.gpkg"
        adapt_t04_surface_for_t05(
            source_surface_path=source_surface_path,
            step7_status_path=Path(str(label["replay_status_path"])),
            relation_row=relation,
            output_path=t04_surface_path,
        )
        t04_evidence_path = sample_root / "t04_relation_evidence.json"
        _write_json_rows(t04_evidence_path, [relation])
    else:
        raise ValueError(f"unsupported Gold family for T05 replay: {family}")

    phase1 = _run_phase1(
        t02_rcsdintersection_path=empty_surface_path,
        t03_surface_path=t03_surface_path,
        t04_surface_path=t04_surface_path,
        nodes_path=nodes_path,
        out_root=sample_root / "phase1",
        run_id="run",
    )
    if (
        phase1.published_surface_count != 1
        or phase1.conflict_count != 0
        or phase1.skipped_count != 0
    ):
        return _failure_row(
            label,
            reason=(
                "phase1_not_single_conflict_free_surface:"
                f"published={phase1.published_surface_count},"
                f"conflict={phase1.conflict_count},skipped={phase1.skipped_count}"
            ),
            elapsed_seconds=perf_counter() - started,
            source_surface_path=source_surface_path,
            phase1=phase1,
        )

    phase2 = _run_phase2(
        junction_surface_path=phase1.surface_path,
        fusion_audit_path=phase1.audit_json_path,
        nodes_path=nodes_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        t02_relation_evidence_path=empty_evidence_path,
        t03_relation_evidence_path=t03_evidence_path,
        t04_relation_evidence_path=t04_evidence_path,
        out_root=sample_root / "phase2",
        run_id="run",
        progress=False,
    )
    phase2_summary = _read_json(Path(phase2.summary_path))
    audit_rows = _read_rows(Path(phase2.rcsd_junctionization_audit_json_path))
    audit = audit_rows[0] if len(audit_rows) == 1 else {}
    phase2_consistent = bool(phase2_summary.get("passed"))
    exact_success = (
        phase2_consistent
        and phase2.relation_count == 1
        and phase2.success_count == 1
        and phase2.failure_count == 0
        and len(audit_rows) == 1
        and int(audit.get("blocking_error") or 0) == 0
    )
    no_rcsd_evidence = (
        phase2_consistent
        and phase2.relation_count == 1
        and phase2.success_count == 0
        and phase2.failure_count == 1
        and len(audit_rows) == 1
        and str(audit.get("scene")) == "no_related_rcsd"
        and str(label.get("relation_state")) == "no_related_rcsd"
        and int(audit.get("blocking_error") or 0) == 0
    )
    replay_status = (
        "SUCCESS"
        if exact_success
        else "NO_RCSD_EVIDENCE"
        if no_rcsd_evidence
        else "QUALITY_ISSUE"
    )
    return JunctionGoldT05ReplayRow(
        sample_id=str(label["sample_id"]),
        sample_group_id=str(label["sample_group_id"]),
        case_id=case_id,
        family=family,
        source_scope=str(label["source_scope"]),
        input_fingerprint=str(label.get("input_fingerprint") or ""),
        status=replay_status,
        reason=str(
            audit.get("reason")
            or ("success" if replay_status in VALID_REPLAY_STATUSES else "phase2_not_exact")
        ),
        phase1_published_surface_count=int(phase1.published_surface_count),
        phase1_conflict_count=int(phase1.conflict_count),
        phase1_skipped_count=int(phase1.skipped_count),
        phase2_relation_count=int(phase2.relation_count),
        phase2_success_count=int(phase2.success_count),
        phase2_failure_count=int(phase2.failure_count),
        scene=str(audit.get("scene") or ""),
        action=str(audit.get("action") or ""),
        selected_main_rcsdnode_id=str(audit.get("selected_main_rcsdnode_id") or ""),
        original_rcsdroad_ids=_split_ids(audit.get("original_rcsdroad_ids")),
        new_rcsdroad_ids=_split_ids(audit.get("new_rcsdroad_ids")),
        original_rcsdnode_ids=_split_ids(audit.get("original_rcsdnode_ids")),
        new_rcsdnode_ids=_split_ids(audit.get("new_rcsdnode_ids")),
        grouped_rcsdnode_ids=_split_ids(audit.get("grouped_rcsdnode_ids")),
        source_surface_path=str(source_surface_path),
        phase1_surface_path=str(phase1.surface_path),
        phase1_audit_path=str(phase1.audit_json_path),
        phase2_audit_path=str(phase2.rcsd_junctionization_audit_json_path),
        phase2_relation_path=str(phase2.relation_geojson_path),
        phase2_rcsdroad_path=str(phase2.rcsdroad_out_path),
        phase2_rcsdnode_path=str(phase2.rcsdnode_out_path),
        geometry_changed=False,
        topology_changed=bool(
            _split_ids(audit.get("new_rcsdroad_ids"))
            or _split_ids(audit.get("new_rcsdnode_ids"))
            or _split_ids(audit.get("grouped_rcsdnode_ids"))
        ),
        silent_fix=False,
        elapsed_seconds=round(perf_counter() - started, 3),
    )


def _run_phase1(**kwargs: Any) -> Any:
    from rcsd_topo_poc.modules.t05_junction_surface_fusion.runner import (
        run_t05_junction_surface_fusion,
    )

    return run_t05_junction_surface_fusion(**kwargs)


def _run_phase2(**kwargs: Any) -> Any:
    from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner import (
        run_t05_phase2_rcsd_junctionization_and_relation,
    )

    return run_t05_phase2_rcsd_junctionization_and_relation(**kwargs)


def _failure_row(
    label: Mapping[str, Any],
    *,
    reason: str,
    elapsed_seconds: float,
    source_surface_path: Path | None = None,
    phase1: Any | None = None,
) -> JunctionGoldT05ReplayRow:
    return JunctionGoldT05ReplayRow(
        sample_id=str(label["sample_id"]),
        sample_group_id=str(label["sample_group_id"]),
        case_id=str(label["case_id"]),
        family=str(label["family"]),
        source_scope=str(label["source_scope"]),
        input_fingerprint=str(label.get("input_fingerprint") or ""),
        status="QUALITY_ISSUE",
        reason=reason,
        phase1_published_surface_count=int(
            getattr(phase1, "published_surface_count", 0)
        ),
        phase1_conflict_count=int(getattr(phase1, "conflict_count", 0)),
        phase1_skipped_count=int(getattr(phase1, "skipped_count", 0)),
        phase2_relation_count=0,
        phase2_success_count=0,
        phase2_failure_count=0,
        scene="",
        action="",
        selected_main_rcsdnode_id="",
        original_rcsdroad_ids=(),
        new_rcsdroad_ids=(),
        original_rcsdnode_ids=(),
        new_rcsdnode_ids=(),
        grouped_rcsdnode_ids=(),
        source_surface_path=str(source_surface_path or label.get("surface_geometry_path") or ""),
        phase1_surface_path=str(getattr(phase1, "surface_path", "")),
        phase1_audit_path=str(getattr(phase1, "audit_json_path", "")),
        phase2_audit_path="",
        phase2_relation_path="",
        phase2_rcsdroad_path="",
        phase2_rcsdnode_path="",
        geometry_changed=False,
        topology_changed=False,
        silent_fix=False,
        elapsed_seconds=round(elapsed_seconds, 3),
    )


def _validate_accepted_surface(path: Path) -> None:
    fingerprints = _surface_geometry_fingerprints(path)
    if not fingerprints:
        raise ValueError(f"accepted surface contains no features: {path}")


def _surface_geometry_fingerprints(path: Path) -> list[str]:
    fingerprints: list[str] = []
    with fiona.open(path) as source:
        if source.crs.to_epsg() != 3857:
            raise ValueError(f"surface CRS must be EPSG:3857: {source.crs}")
        for feature in source:
            geometry = shape(feature["geometry"])
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError(f"surface geometry must be non-empty and valid: {path}")
            fingerprints.append(_geometry_fingerprint(geometry))
    return fingerprints


def _geometry_fingerprint(geometry: Any) -> str:
    return hashlib.sha256(geometry.wkb).hexdigest()


def _required_case_file(case_root: Path, name: str) -> Path:
    path = case_root / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _write_empty_inputs(output_root: Path) -> tuple[Path, Path]:
    surface_path = output_root / "empty_t02.gpkg"
    evidence_path = output_root / "empty_evidence.json"
    if not surface_path.exists():
        with fiona.open(
            surface_path,
            "w",
            driver="GPKG",
            layer="empty_t02",
            schema={"geometry": "Polygon", "properties": {"id": "str"}},
            crs="EPSG:3857",
        ):
            pass
    _write_json_rows(evidence_path, [])
    return surface_path, evidence_path


def _relation_rows_by_target(path: Path) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("target_id") or row.get("case_id")): row
        for row in _read_rows(Path(path))
        if row.get("target_id") is not None or row.get("case_id") is not None
    }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"JSON table must contain rows: {path}")
    return [dict(row) for row in rows]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_json_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"rows": list(rows)}, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def _sample_directory_name(label: Mapping[str, Any]) -> str:
    family = str(label["family"]).lower()
    case_id = str(label["case_id"])
    fingerprint = str(label.get("input_fingerprint") or "")[:12]
    return f"{family}_{case_id}_{fingerprint}"


def _persist_case_row(output_root: Path, row: JunctionGoldT05ReplayRow) -> None:
    sample_root = (
        output_root
        / "cases"
        / f"{row.family.lower()}_{row.case_id}_{row.input_fingerprint[:12]}"
    )
    sample_root.mkdir(parents=True, exist_ok=True)
    (sample_root / "replay_row.json").write_text(
        json.dumps(asdict(row), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _join_ids(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, str):
        return "|".join(_split_ids(values))
    return "|".join(str(value) for value in values if str(value).strip())


def _split_ids(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = str(value).replace(",", "|").split("|")
    return tuple(sorted({str(item).strip() for item in raw if str(item).strip()}))


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
