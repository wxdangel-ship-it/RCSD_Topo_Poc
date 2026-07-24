from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


@dataclass(frozen=True)
class HistoricalTarget:
    sample_id: str
    task_name: str
    target_kind: str
    artifact_path: str
    artifact_sha256: str
    crs: str
    source_run: str
    target_selector: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _canonical(path: Path | str) -> Path:
    return normalize_runtime_path(path).resolve(strict=False)


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_stem(value: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")[:64] or "sample"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{readable}_{digest}"


def _selected_case_ids(preflight: dict[str, Any]) -> list[str]:
    for field in ("selected_case_ids", "effective_case_ids", "formal_full_batch_case_ids"):
        value = preflight.get(field)
        if isinstance(value, list):
            return [str(item) for item in value]
    return []


def _detect_module(run_root: Path, case_ids: list[str]) -> str:
    for case_id in case_ids:
        case_root = run_root / "cases" / case_id
        status_path = case_root / "step7_status.json"
        if status_path.is_file():
            status = _read_json(status_path)
            if "step7_state" in status:
                return "T03"
            if "final_state" in status:
                return "T04"
        if (case_root / "case_meta.json").is_file() or (case_root / "final_case_polygon.gpkg").is_file():
            return "T04"
        if (case_root / "step7_final_polygon.gpkg").is_file():
            return "T03"
    return ""


def _terminal_state(path: Path, module: str) -> str:
    status = _read_json(path)
    field = "step7_state" if module == "T03" else "final_state"
    state = str(status.get(field) or "").casefold()
    return state if state in {"accepted", "rejected"} else ""


def _t04_relation_rows(run_root: Path) -> dict[str, dict[str, Any]]:
    path = run_root / "t04_swsd_rcsd_relation_evidence.json"
    if not path.is_file():
        return {}
    rows = _read_json(path).get("rows")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        case_id = str(row.get("case_id") or row.get("target_id") or "")
        if case_id and case_id not in result:
            result[case_id] = row
    return result


def _relation_evidence(module: str, status: dict[str, Any], t04_row: dict[str, Any] | None) -> dict[str, Any] | None:
    if module == "T03":
        relation_class = str(status.get("association_class") or "").upper()
        if relation_class not in {"A", "B", "C"}:
            return None
        return {
            "label": {"association_class": relation_class, "class_index": {"A": 0, "B": 1, "C": 2}[relation_class]},
            "association_state": str(status.get("association_state") or ""),
            "association_reason": str(status.get("association_reason") or ""),
            "template_class": str(status.get("template_class") or ""),
        }
    if not t04_row:
        return None
    try:
        status_suggested = int(t04_row.get("status_suggested"))
    except (TypeError, ValueError):
        return None
    if status_suggested not in {0, 1}:
        return None
    return {
        "label": {"status_suggested": status_suggested, "class_index": status_suggested},
        "relation_state": str(t04_row.get("relation_state") or ""),
        "reason": str(t04_row.get("reason") or ""),
        "base_id_candidate": str(t04_row.get("base_id_candidate") or ""),
        "selected_rcsdnode_ids": str(t04_row.get("selected_rcsdnode_ids") or ""),
        "selected_rcsdroad_ids": str(t04_row.get("selected_rcsdroad_ids") or ""),
        "scene_type": str(t04_row.get("scene_type") or ""),
    }


def _sample_candidates(samples: Iterable[dict[str, str]], module: str) -> dict[str, list[dict[str, str]]]:
    by_id: dict[str, list[dict[str, str]]] = {}
    for sample in samples:
        family = str(sample.get("family") or "")
        if not family.startswith(module):
            continue
        by_id.setdefault(str(sample.get("business_id") or ""), []).append(sample)
    return by_id


def audit_historical_surface_outputs(
    samples: list[dict[str, str]],
    historical_output_roots: Iterable[Path],
    *,
    label_root: Path,
    user_confirmed_strategy_replay: bool,
) -> tuple[list[HistoricalTarget], list[dict[str, str]], dict[Path, bytes], dict[str, Any]]:
    """Accept only exact-input, formal-terminal T03/T04 surface/relation evidence.

    The returned label documents are normalized lineage wrappers.  Their bytes are
    prepared in memory so callers can preserve immutable-run creation semantics.
    """

    targets: list[HistoricalTarget] = []
    anomalies: list[dict[str, str]] = []
    documents: dict[Path, bytes] = {}
    run_audits: list[dict[str, Any]] = []

    for configured_root in historical_output_roots:
        run_root = _canonical(configured_root)
        audit: dict[str, Any] = {
            "run_root": str(run_root),
            "module": "",
            "selected_case_count": 0,
            "accepted_label_count": 0,
            "unmatched_case_count": 0,
            "invalid_terminal_count": 0,
            "status": "rejected",
            "reason": "",
        }
        if not user_confirmed_strategy_replay:
            audit["reason"] = "strategy_replay_not_user_authorized"
            anomalies.append(
                {
                    "severity": "warning",
                    "category": "historical_strategy_replay_not_authorized",
                    "detail": "explicit user authorization is required before strategy replay output becomes truth",
                    "path": str(run_root),
                }
            )
            run_audits.append(audit)
            continue
        preflight_path = run_root / "preflight.json"
        if not preflight_path.is_file():
            audit["reason"] = "preflight_missing"
            anomalies.append(
                {
                    "severity": "warning",
                    "category": "historical_preflight_missing",
                    "detail": "historical run has no preflight.json",
                    "path": str(run_root),
                }
            )
            run_audits.append(audit)
            continue

        preflight = _read_json(preflight_path)
        case_ids = _selected_case_ids(preflight)
        audit["selected_case_count"] = len(case_ids)
        module = _detect_module(run_root, case_ids)
        audit["module"] = module
        if module not in {"T03", "T04"}:
            audit["reason"] = "unsupported_or_unidentifiable_run"
            anomalies.append(
                {
                    "severity": "warning",
                    "category": "historical_run_unidentifiable",
                    "detail": "only T03/T04 case-level terminal surface runs are supported",
                    "path": str(run_root),
                }
            )
            run_audits.append(audit)
            continue

        case_root_text = str(preflight.get("case_root") or "")
        source_case_root = _canonical(case_root_text) if case_root_text else Path()
        if not case_root_text or not source_case_root.is_dir():
            audit["reason"] = "source_case_root_missing"
            anomalies.append(
                {
                    "severity": "warning",
                    "category": "historical_source_case_root_missing",
                    "detail": "historical output cannot be content-matched because its source Case root is unavailable",
                    "path": str(source_case_root) if case_root_text else str(run_root),
                }
            )
            run_audits.append(audit)
            continue

        candidates = _sample_candidates(samples, module)
        t04_relation_rows = _t04_relation_rows(run_root) if module == "T04" else {}
        unmatched: list[str] = []
        invalid_terminal: list[str] = []
        for case_id in case_ids:
            source_manifest = source_case_root / case_id / "manifest.json"
            if not source_manifest.is_file():
                unmatched.append(case_id)
                continue
            source_manifest_sha256 = sha256_file(source_manifest)
            matched = [
                sample
                for sample in candidates.get(case_id, [])
                if str(sample.get("manifest_sha256") or "") == source_manifest_sha256
            ]
            if len(matched) != 1:
                unmatched.append(case_id)
                continue

            case_output_root = run_root / "cases" / case_id
            status_path = case_output_root / "step7_status.json"
            if not status_path.is_file():
                invalid_terminal.append(case_id)
                continue
            state = _terminal_state(status_path, module)
            if not state:
                invalid_terminal.append(case_id)
                continue
            geometry_name = "step7_final_polygon.gpkg" if module == "T03" else "final_case_polygon.gpkg"
            geometry_path = case_output_root / geometry_name
            if state == "accepted" and not geometry_path.is_file():
                invalid_terminal.append(case_id)
                continue

            sample = matched[0]
            sample_id = str(sample.get("sample_id") or "")
            status_document = _read_json(status_path)
            epsg = str(_read_json(source_manifest).get("epsg") or "")
            crs = f"EPSG:{epsg}" if epsg and not epsg.upper().startswith("EPSG:") else epsg
            document = {
                "schema_version": "p05-m2r-historical-surface-label-v1",
                "sample_id": sample_id,
                "family": str(sample.get("family") or ""),
                "business_id": case_id,
                "task_name": module,
                "target_kind": "surface",
                "formal_state": state,
                "crs": crs,
                "source_run": str(run_root),
                "source_preflight": {
                    "path": str(preflight_path.resolve()),
                    "sha256": sha256_file(preflight_path),
                },
                "source_input_manifest": {
                    "path": str(source_manifest.resolve()),
                    "sha256": source_manifest_sha256,
                },
                "registered_input_manifest": {
                    "path": str(_canonical(str(sample.get("manifest_path") or ""))),
                    "sha256": str(sample.get("manifest_sha256") or ""),
                },
                "terminal_status": {
                    "path": str(status_path.resolve()),
                    "sha256": sha256_file(status_path),
                },
                "surface_geometry": (
                    {"path": str(geometry_path.resolve()), "sha256": sha256_file(geometry_path)}
                    if geometry_path.is_file()
                    else None
                ),
                "lineage_gate": {
                    "explicit_run_root": True,
                    "input_manifest_sha256_exact_match": True,
                    "formal_terminal_state": True,
                    "user_authorized_local_case_scope": True,
                    "user_confirmed_strategy_replay_truth": True,
                    "rule_rerun_performed_by_p05": False,
                    "silent_fix": False,
                },
            }
            target_path = label_root / f"{_safe_stem(sample_id)}_{module.casefold()}_surface.json"
            payload = _json_bytes(document)
            documents[target_path] = payload
            targets.append(
                HistoricalTarget(
                    sample_id=sample_id,
                    task_name=module,
                    target_kind="surface",
                    artifact_path=str(target_path.resolve()),
                    artifact_sha256=_bytes_sha256(payload),
                    crs=crs,
                    source_run=str(run_root),
                    target_selector=case_id,
                    reason="user_confirmed_strategy_replay_terminal_surface_exact_input_manifest_match",
                )
            )

            relation = _relation_evidence(module, status_document, t04_relation_rows.get(case_id))
            if relation is not None:
                relation_document = {
                    "schema_version": "p05-m2r-historical-relation-label-v1",
                    "sample_id": sample_id,
                    "family": str(sample.get("family") or ""),
                    "business_id": case_id,
                    "task_name": module,
                    "target_kind": "relation",
                    "formal_state": state,
                    "crs": crs,
                    "source_run": str(run_root),
                    "source_preflight": document["source_preflight"],
                    "source_input_manifest": document["source_input_manifest"],
                    "registered_input_manifest": document["registered_input_manifest"],
                    "terminal_status": document["terminal_status"],
                    "relation_evidence": relation,
                    "lineage_gate": document["lineage_gate"],
                }
                relation_path = label_root / f"{_safe_stem(sample_id)}_{module.casefold()}_relation.json"
                relation_payload = _json_bytes(relation_document)
                documents[relation_path] = relation_payload
                targets.append(
                    HistoricalTarget(
                        sample_id=sample_id,
                        task_name=module,
                        target_kind="relation",
                        artifact_path=str(relation_path.resolve()),
                        artifact_sha256=_bytes_sha256(relation_payload),
                        crs=crs,
                        source_run=str(run_root),
                        target_selector=case_id,
                        reason="user_confirmed_strategy_replay_terminal_relation_exact_input_manifest_match",
                    )
                )

        audit["accepted_label_count"] = len(case_ids) - len(unmatched) - len(invalid_terminal)
        audit["accepted_target_count"] = sum(
            target.source_run == str(run_root) for target in targets
        )
        audit["unmatched_case_count"] = len(unmatched)
        audit["invalid_terminal_count"] = len(invalid_terminal)
        audit["unmatched_case_ids"] = unmatched
        audit["invalid_terminal_case_ids"] = invalid_terminal
        audit["status"] = "accepted" if audit["accepted_label_count"] else "rejected"
        audit["reason"] = "exact_manifest_terminal_labels_available" if audit["accepted_label_count"] else "no_eligible_labels"
        if unmatched:
            anomalies.append(
                {
                    "severity": "info",
                    "category": "historical_case_manifest_not_matched",
                    "detail": f"{len(unmatched)} selected cases were not exact manifest matches; first={unmatched[:10]}",
                    "path": str(run_root),
                }
            )
        if invalid_terminal:
            anomalies.append(
                {
                    "severity": "warning",
                    "category": "historical_case_terminal_invalid",
                    "detail": f"{len(invalid_terminal)} cases lacked a valid formal terminal surface; first={invalid_terminal[:10]}",
                    "path": str(run_root),
                }
            )
        run_audits.append(audit)

    targets.sort(key=lambda item: (item.sample_id, item.task_name, item.target_kind))
    summary = {
        "schema_version": "p05-m2r-historical-output-audit-v1",
        "run_count": len(run_audits),
        "accepted_run_count": sum(item["status"] == "accepted" for item in run_audits),
        "accepted_label_count": len(targets),
        "runs": run_audits,
    }
    return targets, anomalies, documents, summary


__all__ = ["HistoricalTarget", "audit_historical_surface_outputs"]
