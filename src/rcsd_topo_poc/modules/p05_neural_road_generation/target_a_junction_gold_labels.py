from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
from shapely.geometry import shape
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file


@dataclass(frozen=True)
class JunctionGoldReplayRoots:
    poc_data_t03: Path
    poc_data_t03_explicit_excluded: Path
    poc_data_t03_error: Path
    poc_qa_t03_error: Path
    poc_data_t04: Path
    poc_data_t04_error: Path


@dataclass(frozen=True)
class JunctionGoldLabel:
    sample_id: str
    sample_group_id: str
    case_id: str
    family: str
    source_scope: str
    source_index: int
    case_root: str
    input_fingerprint: str
    label_weight: float
    label_status: str
    t07_step1_has_evd: str
    t07_step2_is_anchor: str
    t07_step2_input_terminal_value: str
    t07_step2_gold_status: str
    surface_state: str
    surface_geometry_path: str
    surface_geometry_sha256: str
    surface_area_m2: float | None
    surface_component_count: int | None
    relation_state: str
    anchor_business_state: str
    selected_rcsd_node_ids: tuple[str, ...]
    selected_rcsd_road_ids: tuple[str, ...]
    support_rcsd_node_ids: tuple[str, ...]
    support_rcsd_road_ids: tuple[str, ...]
    route_class: str
    replay_reason: str
    replay_exception_type: str
    replay_status_path: str
    replay_audit_path: str
    terminal_business_signature: str


@dataclass(frozen=True)
class JunctionGoldVersionReview:
    case_id: str
    source_version_count: int
    terminal_signature_count: int
    status: str
    sample_ids: tuple[str, ...]
    terminal_business_signatures: tuple[str, ...]


def build_junction_gold_labels(
    *,
    inventory_sources_path: Path,
    replay_roots: JunctionGoldReplayRoots,
) -> tuple[
    tuple[JunctionGoldLabel, ...],
    tuple[JunctionGoldVersionReview, ...],
    dict[str, Any],
]:
    source_rows = tuple(_read_jsonl(Path(inventory_sources_path)))
    t04_relations = {
        ("POC_Data", "T04"): _read_relation_rows(
            replay_roots.poc_data_t04 / "t04_swsd_rcsd_relation_evidence.json"
        ),
        ("POC_Data", "T04_Error"): _read_relation_rows(
            replay_roots.poc_data_t04_error
            / "t04_swsd_rcsd_relation_evidence.json"
        ),
    }
    labels = tuple(
        sorted(
            (
                _label_for_source(
                    source,
                    replay_roots=replay_roots,
                    t04_relations=t04_relations,
                )
                for source in source_rows
            ),
            key=lambda row: (row.case_id, row.source_index),
        )
    )
    version_reviews = _version_reviews(labels)
    summary = {
        "schema_version": "p05-target-a-junction-gold-labels-v2",
        "status": (
            "JUNCTION_GOLD_LABELS_GO"
            if all(row.label_status == "READY" for row in labels)
            else "JUNCTION_GOLD_LABELS_REVIEW"
        ),
        "source_record_count": len(labels),
        "unique_case_id_count": len({row.case_id for row in labels}),
        "label_status_counts": dict(
            sorted(Counter(row.label_status for row in labels).items())
        ),
        "surface_state_counts": dict(
            sorted(Counter(row.surface_state for row in labels).items())
        ),
        "anchor_business_state_counts": dict(
            sorted(Counter(row.anchor_business_state for row in labels).items())
        ),
        "relation_state_counts": dict(
            sorted(Counter(row.relation_state for row in labels).items())
        ),
        "route_class_counts": dict(
            sorted(Counter(row.route_class for row in labels).items())
        ),
        "t07_step2_gold_status_counts": dict(
            sorted(Counter(row.t07_step2_gold_status for row in labels).items())
        ),
        "source_version_review_count": len(version_reviews),
        "source_version_same_terminal_count": sum(
            row.status == "SAME_TERMINAL_BUSINESS" for row in version_reviews
        ),
        "source_version_conflicting_terminal_count": sum(
            row.status == "TERMINAL_BUSINESS_CONFLICT" for row in version_reviews
        ),
        "geometry_changed": False,
        "topology_changed": False,
        "silent_fix": False,
    }
    return labels, version_reviews, summary


def write_junction_gold_labels(
    *,
    inventory_sources_path: Path,
    replay_roots: JunctionGoldReplayRoots,
    output_root: Path,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    labels, reviews, summary = build_junction_gold_labels(
        inventory_sources_path=inventory_sources_path,
        replay_roots=replay_roots,
    )
    labels_path = output / "junction_gold_labels.jsonl"
    reviews_path = output / "junction_gold_version_reviews.jsonl"
    _write_jsonl(labels_path, (asdict(row) for row in labels))
    _write_jsonl(reviews_path, (asdict(row) for row in reviews))
    result = {
        **summary,
        "artifacts": {
            "labels": _artifact(labels_path),
            "version_reviews": _artifact(reviews_path),
        },
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _label_for_source(
    source: Mapping[str, Any],
    *,
    replay_roots: JunctionGoldReplayRoots,
    t04_relations: Mapping[tuple[str, str], Mapping[str, Mapping[str, Any]]],
) -> JunctionGoldLabel:
    case_id = str(source["case_id"])
    family = str(source["family"])
    source_scope = str(source["source_scope"])
    source_index = int(source["source_index"])
    fingerprint = str(source.get("input_fingerprint") or "")
    sample_id = (
        f"junction-gold:{source_scope}:{family}:{case_id}:"
        f"{fingerprint[:16] or source_index}"
    )
    base = {
        "sample_id": sample_id,
        "sample_group_id": f"junction:{case_id}",
        "case_id": case_id,
        "family": family,
        "source_scope": source_scope,
        "source_index": source_index,
        "case_root": str(source["case_root"]),
        "input_fingerprint": fingerprint,
        "label_weight": float(source.get("label_weight") or 1.0),
    }
    if str(source.get("status")) != "READY":
        return _unusable_label(base, label_status="SOURCE_INVALID")

    try:
        step1, input_terminal_step2 = _read_target_t07_labels(
            Path(str(source["case_root"])) / "nodes.gpkg",
            case_id,
        )
        # T03/T04 single-case inputs contain no formal RCSDIntersection Step2
        # evidence. Their nodes.is_anchor value is a terminal field, not a
        # reproducible T07 Step2 Gold label for the replacement model.
        step2 = ""
        if family in {"T03", "T03_Error"}:
            replay = _read_t03_replay(
                source_scope=source_scope,
                family=family,
                case_id=case_id,
                roots=replay_roots,
            )
        elif family in {"T04", "T04_Error"}:
            replay = _read_t04_replay(
                source_scope=source_scope,
                family=family,
                case_id=case_id,
                roots=replay_roots,
                relations=t04_relations.get((source_scope, family), {}),
            )
        else:
            raise ValueError(f"unsupported junction Gold family: {family}")
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return _unusable_label(
            base,
            label_status="LABEL_REVIEW",
            replay_reason=str(exc),
            replay_exception_type=type(exc).__name__,
        )

    signature_payload = {
        "t07_step1_has_evd": step1,
        "t07_step2_is_anchor": step2,
        "t07_step2_gold_status": "MASKED_TERMINAL_ONLY",
        "surface_state": replay["surface_state"],
        "relation_state": replay["relation_state"],
        "anchor_business_state": replay["anchor_business_state"],
        "selected_rcsd_node_ids": replay["selected_rcsd_node_ids"],
        "selected_rcsd_road_ids": replay["selected_rcsd_road_ids"],
        "support_rcsd_node_ids": replay["support_rcsd_node_ids"],
        "support_rcsd_road_ids": replay["support_rcsd_road_ids"],
        "route_class": replay["route_class"],
    }
    signature = hashlib.sha256(
        json.dumps(
            signature_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return JunctionGoldLabel(
        **base,
        label_status="READY",
        t07_step1_has_evd=step1,
        t07_step2_is_anchor=step2,
        t07_step2_input_terminal_value=input_terminal_step2,
        t07_step2_gold_status="MASKED_TERMINAL_ONLY",
        terminal_business_signature=signature,
        **replay,
    )


def _read_t03_replay(
    *,
    source_scope: str,
    family: str,
    case_id: str,
    roots: JunctionGoldReplayRoots,
) -> dict[str, Any]:
    if (source_scope, family) == ("POC_Data", "T03"):
        primary = roots.poc_data_t03
        supplement = roots.poc_data_t03_explicit_excluded
        case_dir = primary / "cases" / case_id
        if not case_dir.is_dir():
            case_dir = supplement / "cases" / case_id
    elif (source_scope, family) == ("POC_Data", "T03_Error"):
        case_dir = roots.poc_data_t03_error / "cases" / case_id
    elif (source_scope, family) == ("POC_QA", "T03_Error"):
        case_dir = roots.poc_qa_t03_error / "cases" / case_id
    else:
        raise ValueError(f"unsupported T03 replay source: {source_scope}/{family}")
    status_path = case_dir / "step7_status.json"
    audit_path = case_dir / "step6_audit.json"
    status = _read_json(status_path)
    audit = _read_json(audit_path)
    inputs = dict(audit.get("inputs") or {})
    step7_state = str(status.get("step7_state") or "")
    association_class = str(status.get("association_class") or "")
    selected_nodes = _split_ids(inputs.get("required_rcsdnode_ids"))
    selected_roads = _split_ids(inputs.get("required_rcsdroad_ids"))
    if step7_state != "accepted":
        relation_state = "geometry_not_accepted"
    elif association_class == "A" and selected_nodes:
        relation_state = "success_required_rcsd_junction"
    elif association_class == "B":
        relation_state = "rcsd_present_not_junction"
    elif association_class == "C":
        relation_state = "no_related_rcsd"
    else:
        relation_state = "ambiguous_review"
    surface_path = case_dir / "step7_final_polygon.gpkg"
    geometry = _geometry_audit(surface_path) if step7_state == "accepted" else _empty_geometry_audit()
    return {
        "surface_state": step7_state or "formal_result_missing",
        "relation_state": relation_state,
        "anchor_business_state": _anchor_business_state(relation_state),
        "selected_rcsd_node_ids": selected_nodes,
        "selected_rcsd_road_ids": selected_roads,
        "support_rcsd_node_ids": _split_ids(inputs.get("support_rcsdnode_ids")),
        "support_rcsd_road_ids": _split_ids(inputs.get("support_rcsdroad_ids")),
        "route_class": "T03",
        "replay_reason": str(status.get("reason") or relation_state),
        "replay_exception_type": "",
        "replay_status_path": str(status_path.resolve()),
        "replay_audit_path": str(audit_path.resolve()),
        **geometry,
    }


def _read_t04_replay(
    *,
    source_scope: str,
    family: str,
    case_id: str,
    roots: JunctionGoldReplayRoots,
    relations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if source_scope != "POC_Data":
        raise ValueError(f"unsupported T04 source scope: {source_scope}")
    run_root = roots.poc_data_t04 if family == "T04" else roots.poc_data_t04_error
    case_dir = run_root / "cases" / case_id
    status_path = case_dir / "step7_status.json"
    audit_path = case_dir / "step7_audit.json"
    failure_path = run_root / "failures" / f"{case_id}.failure.json"
    if failure_path.is_file():
        failure = _read_json(failure_path)
        return {
            "surface_state": "runtime_failed",
            "surface_geometry_path": "",
            "surface_geometry_sha256": "",
            "surface_area_m2": None,
            "surface_component_count": None,
            "relation_state": "runtime_failed",
            "anchor_business_state": "QUALITY_ISSUE",
            "selected_rcsd_node_ids": (),
            "selected_rcsd_road_ids": (),
            "support_rcsd_node_ids": (),
            "support_rcsd_road_ids": (),
            "route_class": "T04",
            "replay_reason": str(failure.get("message") or "runtime_failed"),
            "replay_exception_type": str(failure.get("exception_type") or ""),
            "replay_status_path": str(failure_path.resolve()),
            "replay_audit_path": "",
        }
    status = _read_json(status_path)
    relation = dict(relations.get(case_id) or {})
    if not relation:
        raise ValueError(f"T04 relation evidence missing for case {case_id}")
    final_state = str(status.get("final_state") or "")
    relation_state = str(relation.get("relation_state") or "ambiguous_review")
    surface_path = case_dir / "final_case_polygon.gpkg"
    geometry = _geometry_audit(surface_path) if final_state == "accepted" else _empty_geometry_audit()
    return {
        "surface_state": final_state or "formal_result_missing",
        "relation_state": relation_state,
        "anchor_business_state": _anchor_business_state(relation_state),
        "selected_rcsd_node_ids": _split_ids(relation.get("selected_rcsdnode_ids")),
        "selected_rcsd_road_ids": _split_ids(relation.get("selected_rcsdroad_ids")),
        "support_rcsd_node_ids": (),
        "support_rcsd_road_ids": (),
        "route_class": "T04",
        "replay_reason": str(relation.get("reason") or relation_state),
        "replay_exception_type": "",
        "replay_status_path": str(status_path.resolve()),
        "replay_audit_path": str(audit_path.resolve()),
        **geometry,
    }


def _read_target_t07_labels(nodes_path: Path, case_id: str) -> tuple[str, str]:
    layers = fiona.listlayers(nodes_path)
    if not layers:
        raise ValueError(f"nodes GeoPackage has no layer: {nodes_path}")
    target_rows: list[Mapping[str, Any]] = []
    with fiona.open(nodes_path, layer=layers[0]) as source:
        for feature in source:
            properties = dict(feature["properties"])
            if _normalize_id(properties.get("id")) == case_id:
                target_rows.append(properties)
    if len(target_rows) != 1:
        raise ValueError(
            f"expected one exact SWSD target node for {case_id}, found {len(target_rows)}"
        )
    step1 = str(target_rows[0].get("has_evd") or "").strip()
    step2 = str(target_rows[0].get("is_anchor") or "").strip()
    if not step1 or not step2:
        raise ValueError(f"target T07 labels are incomplete for {case_id}")
    return step1, step2


def _read_relation_rows(path: Path) -> Mapping[str, Mapping[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("rows") or []
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or row.get("target_id") or "")
        if not case_id:
            continue
        if case_id in result:
            raise ValueError(f"duplicate T04 relation evidence for case {case_id}")
        result[case_id] = dict(row)
    return result


def _anchor_business_state(relation_state: str) -> str:
    if relation_state.startswith("success_"):
        return "SUCCESS"
    if relation_state == "no_related_rcsd":
        return "NO_RCSD_EVIDENCE"
    if relation_state in {
        "geometry_not_accepted",
        "rcsd_present_not_junction",
        "runtime_failed",
    }:
        return "QUALITY_ISSUE"
    return "AMBIGUOUS"


def _geometry_audit(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"accepted surface geometry is missing: {path}")
    layers = fiona.listlayers(path)
    geometries = []
    for layer in layers:
        with fiona.open(path, layer=layer) as source:
            geometries.extend(
                shape(feature["geometry"])
                for feature in source
                if feature.get("geometry") is not None
            )
    if not geometries:
        raise ValueError(f"accepted surface has no geometry: {path}")
    geometry = unary_union(geometries)
    normalized = geometry.normalize()
    component_count = (
        len(getattr(normalized, "geoms", ()))
        if normalized.geom_type.startswith("Multi")
        else 1
    )
    return {
        "surface_geometry_path": str(path.resolve()),
        "surface_geometry_sha256": hashlib.sha256(normalized.wkb).hexdigest(),
        "surface_area_m2": round(float(normalized.area), 6),
        "surface_component_count": component_count,
    }


def _empty_geometry_audit() -> dict[str, Any]:
    return {
        "surface_geometry_path": "",
        "surface_geometry_sha256": "",
        "surface_area_m2": None,
        "surface_component_count": None,
    }


def _version_reviews(
    labels: Sequence[JunctionGoldLabel],
) -> tuple[JunctionGoldVersionReview, ...]:
    grouped: dict[str, list[JunctionGoldLabel]] = defaultdict(list)
    for label in labels:
        grouped[label.case_id].append(label)
    reviews: list[JunctionGoldVersionReview] = []
    for case_id, rows in sorted(grouped.items()):
        fingerprints = {row.input_fingerprint for row in rows if row.input_fingerprint}
        if len(fingerprints) <= 1:
            continue
        signatures = tuple(sorted({row.terminal_business_signature for row in rows}))
        reviews.append(
            JunctionGoldVersionReview(
                case_id=case_id,
                source_version_count=len(fingerprints),
                terminal_signature_count=len(signatures),
                status=(
                    "SAME_TERMINAL_BUSINESS"
                    if len(signatures) == 1 and signatures[0]
                    else "TERMINAL_BUSINESS_CONFLICT"
                ),
                sample_ids=tuple(sorted(row.sample_id for row in rows)),
                terminal_business_signatures=signatures,
            )
        )
    return tuple(reviews)


def _unusable_label(
    base: Mapping[str, Any],
    *,
    label_status: str,
    replay_reason: str = "",
    replay_exception_type: str = "",
) -> JunctionGoldLabel:
    return JunctionGoldLabel(
        **base,
        label_status=label_status,
        t07_step1_has_evd="",
        t07_step2_is_anchor="",
        t07_step2_input_terminal_value="",
        t07_step2_gold_status="UNAVAILABLE",
        surface_state="",
        surface_geometry_path="",
        surface_geometry_sha256="",
        surface_area_m2=None,
        surface_component_count=None,
        relation_state="",
        anchor_business_state="",
        selected_rcsd_node_ids=(),
        selected_rcsd_road_ids=(),
        support_rcsd_node_ids=(),
        support_rcsd_road_ids=(),
        route_class="",
        replay_reason=replay_reason,
        replay_exception_type=replay_exception_type,
        replay_status_path="",
        replay_audit_path="",
        terminal_business_signature="",
    )


def _normalize_id(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _split_ids(value: Any) -> tuple[str, ...]:
    if value in (None, "", (), [], {}):
        return ()
    parts = value if isinstance(value, (list, tuple, set)) else str(value).replace(",", "|").split("|")
    return tuple(
        sorted(
            {
                normalized
                for item in parts
                if (normalized := _normalize_id(item)) not in {"", "0", "-1"}
            }
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8-sig")))


def _read_jsonl(path: Path) -> Iterable[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield dict(json.loads(line))


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
                + "\n"
            )


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


__all__ = [
    "JunctionGoldLabel",
    "JunctionGoldReplayRoots",
    "JunctionGoldVersionReview",
    "build_junction_gold_labels",
    "write_junction_gold_labels",
]
