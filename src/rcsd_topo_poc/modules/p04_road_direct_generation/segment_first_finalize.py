from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .io import sha256_file, write_json
from .segment_first_types import SegmentFirstResult


_ACCEPTED_MANUAL_DECISIONS = {"accepted", "accepted_with_review"}


def finalize_segment_first_run(
    output_dir: Path,
    acceptance_manifest_path: Path,
) -> SegmentFirstResult:
    """Promote a technical run only after external acceptance evidence is complete."""
    root = output_dir.resolve()
    summary_path = root / "p04_segment_first_summary.json"
    report_path = root / "p04_segment_first_report.md"
    summary = _read_json(summary_path)
    run_id = str(summary.get("run_id", ""))
    if not run_id:
        raise ValueError("summary run_id is missing")
    if summary.get("terminal_status") not in {"technical_passed", "passed"}:
        raise ValueError("only a technical_passed run can be finalized")
    _validate_technical_gates(summary)

    manifest_path = _inside_root(root, acceptance_manifest_path)
    manifest = _read_json(manifest_path)
    if str(manifest.get("run_id", "")) != run_id:
        raise ValueError("acceptance manifest run_id does not match summary")

    reports = {
        role: _inside_root(root, root / str(manifest.get(key, "")))
        for role, key in {
            "qgis_overlay": "qgis_overlay_report",
            "pyqgis_readback": "pyqgis_readback_report",
            "determinism": "determinism_report",
            "manual_audit": "manual_audit_report",
        }.items()
    }
    payloads = {role: _read_json(path) for role, path in reports.items()}
    _validate_qgis_overlay(payloads["qgis_overlay"])
    _validate_pyqgis_readback(payloads["pyqgis_readback"])
    _validate_determinism(payloads["determinism"])
    _validate_manual_audit(root, payloads["manual_audit"])

    evidence = {
        role: {
            "path": path.name,
            "sha256": sha256_file(path),
        }
        for role, path in reports.items()
    }
    published_paths = {
        "formal_gpkg": root / "p04_segment_first_rcsd.gpkg",
        "audit_gpkg": root / "p04_segment_first_audit.gpkg",
        "relations_gpkg": root / "p04_segment_first_relations.gpkg",
        "independent_quality_json": root
        / "p04_segment_first_independent_quality.json",
        "qgis_project": root / "p04_segment_first_comparison.qgz",
    }
    for path in published_paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    published_outputs = {
        role: {"path": path.name, "sha256": sha256_file(path)}
        for role, path in published_paths.items()
    }
    acceptance = {
        "run_id": run_id,
        "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
        "terminal_status": "passed",
        "evidence": evidence,
        "published_outputs": published_outputs,
        "manual_decision": payloads["manual_audit"]["decision"],
        "manual_review_required_count": int(
            payloads["manual_audit"].get("review_required_count", 0)
        ),
    }
    acceptance_path = root / "p04_segment_first_acceptance.json"
    write_json(acceptance_path, acceptance)
    summary["terminal_status"] = "passed"
    summary["acceptance"] = {
        **acceptance,
        "acceptance_json": acceptance_path.name,
        "acceptance_manifest": manifest_path.name,
    }
    write_json(summary_path, summary)
    existing_report = report_path.read_text(encoding="utf-8")
    report_path.write_text(
        _final_report(existing_report, acceptance),
        encoding="utf-8",
    )
    return SegmentFirstResult(
        run_id=run_id,
        output_dir=root,
        formal_gpkg=root / "p04_segment_first_rcsd.gpkg",
        audit_gpkg=root / "p04_segment_first_audit.gpkg",
        relations_gpkg=root / "p04_segment_first_relations.gpkg",
        summary_path=summary_path,
        report_path=report_path,
        independent_quality_path=root / "p04_segment_first_independent_quality.json",
        qgis_project_path=root / "p04_segment_first_comparison.qgz",
        terminal_status="passed",
        core_gate_pass=True,
    )


def _validate_technical_gates(summary: dict[str, Any]) -> None:
    if not bool(summary.get("core_gate_pass")):
        raise ValueError("core gate did not pass")
    if not bool(summary.get("independent_quality", {}).get("gate_pass")):
        raise ValueError("independent quality did not pass")
    if not bool(summary.get("qgis", {}).get("readback_pass")):
        raise ValueError("QGIS generator readback did not pass")


def _validate_qgis_overlay(payload: dict[str, Any]) -> None:
    if not bool(payload.get("gate_pass")):
        raise ValueError("QGIS overlay gate did not pass")
    if "new_built_roads" not in payload.get("selected_layers", []):
        raise ValueError("QGIS overlay did not audit new_built_roads")


def _validate_pyqgis_readback(payload: dict[str, Any]) -> None:
    if not bool(payload.get("project_read")):
        raise ValueError("PyQGIS project readback failed")
    if int(payload.get("invalid_layer_count", -1)) != 0:
        raise ValueError("PyQGIS project contains invalid layers")
    if int(payload.get("spatial_renderer_missing_count", -1)) != 0:
        raise ValueError("PyQGIS project contains unrenderable spatial layers")


def _validate_determinism(payload: dict[str, Any]) -> None:
    if not bool(payload.get("gate_pass")):
        raise ValueError("determinism replay did not pass")
    required = {"Road", "Node", "RoadNextRoad"}
    if not required.issubset(set(payload.get("formal_layers_compared", []))):
        raise ValueError("determinism report did not compare all formal layers")


def _validate_manual_audit(root: Path, payload: dict[str, Any]) -> None:
    if payload.get("decision") not in _ACCEPTED_MANUAL_DECISIONS:
        raise ValueError("manual audit did not accept the run")
    if int(payload.get("hard_failure_count", -1)) != 0:
        raise ValueError("manual audit contains hard failures")
    if int(payload.get("reviewed_case_count", 0)) <= 0:
        raise ValueError("manual audit has no reviewed cases")
    image_path = _inside_root(root, root / str(payload.get("audit_image", "")))
    if not image_path.is_file():
        raise FileNotFoundError(f"manual audit image is missing: {image_path}")


def _inside_root(root: Path, path: Path) -> Path:
    candidate = path.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"acceptance evidence must stay inside output_dir: {candidate}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _final_report(report: str, acceptance: dict[str, Any]) -> str:
    base = report.split("\n## 最终验收证据", maxsplit=1)[0]
    base = base.replace(
        "- 终态：`technical_passed`",
        "- 终态：`passed`",
    )
    return "\n".join(
        [
            base,
            "",
            "## 最终验收证据",
            "",
            f"- Finalizer：`{acceptance['finalized_at_utc']}`",
            f"- 人工结论：`{acceptance['manual_decision']}`；保留Review：{acceptance['manual_review_required_count']}",
            "- QGIS道路面覆盖、真实PyQGIS回读、重复运行确定性和人工极值审计均已通过。",
        ]
    )


__all__ = ["finalize_segment_first_run"]
