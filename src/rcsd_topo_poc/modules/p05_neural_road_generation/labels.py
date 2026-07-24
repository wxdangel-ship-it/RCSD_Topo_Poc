from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    DataAnomaly,
    LabelArtifact,
    M0Config,
    TrainingSample,
    sha256_file,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


LABEL_ROLES = (
    "t01_segment",
    "t03_nodes",
    "t04_nodes",
    "t05_intersection_match_all",
    "t05_rcsdroad_out",
    "t05_rcsdnode_out",
    "t06_frcsd_road",
    "t06_frcsd_node",
    "t06_swsd_frcsd_segment_relation",
    "t07_nodes",
)
REQUIRED_ROAD_GRAPH_ROLES = frozenset({"t06_frcsd_road", "t06_frcsd_node"})
FAMILY_NAMES = {
    "t10": "T10",
    "t10-error": "T10-Error",
    "t10_error": "T10-Error",
    "t10-error-2": "T10-Error-2",
    "t10_error2": "T10-Error-2",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _canonical(path: Path | str) -> Path:
    return normalize_runtime_path(path).resolve(strict=False)


def _is_under(path: Path, root: Path) -> bool:
    left = str(_canonical(path)).casefold()
    right = str(_canonical(root)).rstrip("\\/").casefold()
    return left == right or left.startswith(right + "\\") or left.startswith(right + "/")


def _family_for_source_root(source_root: Path) -> str | None:
    return FAMILY_NAMES.get(source_root.name.casefold())


def _package_entries(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw_entries = summary.get("package_summaries")
    if isinstance(raw_entries, list):
        return [item for item in raw_entries if isinstance(item, dict)]
    if summary.get("source_root") and summary.get("run_root"):
        return [{"source_root": summary["source_root"], "run_root": summary["run_root"]}]
    return []


def _case_business_id(case_id: str) -> str:
    return case_id[len("segment_") :] if case_id.startswith("segment_") else case_id


def discover_label_artifacts(
    config: M0Config,
    samples: list[TrainingSample],
) -> tuple[list[TrainingSample], list[LabelArtifact], list[DataAnomaly]]:
    sample_lookup: dict[tuple[str, str], list[TrainingSample]] = {}
    for sample in samples:
        sample_lookup.setdefault((sample.family, sample.business_id), []).append(sample)

    artifacts: list[LabelArtifact] = []
    anomalies: list[DataAnomaly] = []
    selected_cases: set[tuple[str, str]] = set()
    poc_root = _canonical(config.poc_data_root)

    for baseline_root_raw in config.baseline_roots:
        baseline_root = _canonical(baseline_root_raw)
        summary_path = baseline_root / "baseline_summary.json"
        if not summary_path.is_file():
            anomalies.append(DataAnomaly("error", "missing_baseline_summary", "baseline_summary.json is missing", path=str(summary_path)))
            continue
        try:
            summary = _read_json(summary_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            anomalies.append(DataAnomaly("error", "invalid_baseline_summary", str(exc), path=str(summary_path)))
            continue
        baseline_id = str(summary.get("baseline_id") or baseline_root.name)
        repo_head = str(summary.get("repo_head") or "")
        entries = _package_entries(summary)
        if not entries:
            anomalies.append(DataAnomaly("error", "baseline_packages_missing", "no source_root/run_root package entries", path=str(summary_path)))
            continue
        for entry in entries:
            source_root = _canonical(str(entry.get("source_root") or ""))
            run_root = _canonical(str(entry.get("run_root") or ""))
            family = _family_for_source_root(source_root)
            if family is None:
                anomalies.append(DataAnomaly("warning", "unregistered_baseline_family", f"source root is not a registered T10 family: {source_root}", path=str(summary_path)))
                continue
            expected_family_root = poc_root / family
            if not _is_under(source_root, poc_root) or str(source_root).casefold() != str(expected_family_root.resolve(strict=False)).casefold():
                anomalies.append(
                    DataAnomaly(
                        "error",
                        "baseline_scope_violation",
                        f"baseline source root does not exactly match {expected_family_root}: {source_root}",
                        family=family,
                        path=str(summary_path),
                    )
                )
                continue
            cases_root = run_root / "cases"
            if not cases_root.is_dir():
                anomalies.append(DataAnomaly("error", "baseline_cases_missing", "run_root/cases is missing", family=family, path=str(cases_root)))
                continue
            for case_dir in sorted((path for path in cases_root.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
                business_id = _case_business_id(case_dir.name)
                case_key = (family, business_id)
                if case_key in selected_cases:
                    continue
                target_samples = sample_lookup.get(case_key)
                if not target_samples:
                    anomalies.append(
                        DataAnomaly(
                            "warning",
                            "baseline_case_not_in_inventory",
                            "passed baseline Case has no matching POC_Data sample",
                            family=family,
                            business_id=business_id,
                            path=str(case_dir),
                        )
                    )
                    continue
                run_summary_path = case_dir / "t10_e2e_case_run_summary.json"
                if not run_summary_path.is_file():
                    anomalies.append(DataAnomaly("error", "case_run_summary_missing", "t10_e2e_case_run_summary.json is missing", family, business_id, str(run_summary_path)))
                    continue
                try:
                    run_summary = _read_json(run_summary_path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    anomalies.append(DataAnomaly("error", "invalid_case_run_summary", str(exc), family, business_id, str(run_summary_path)))
                    continue
                passed = bool(run_summary.get("passed")) or str(run_summary.get("status") or "").casefold() == "passed"
                if not passed:
                    anomalies.append(DataAnomaly("error", "canonical_case_not_passed", "baseline Case is not passed", family, business_id, str(run_summary_path)))
                    continue
                funnel = run_summary.get("t06_funnel") if isinstance(run_summary.get("t06_funnel"), dict) else {}
                handoffs = funnel.get("handoffs") if isinstance(funnel.get("handoffs"), dict) else {}
                available_required: set[str] = set()
                for role in LABEL_ROLES:
                    raw_path = handoffs.get(role)
                    if not raw_path:
                        continue
                    artifact_path = _canonical(str(raw_path))
                    if not artifact_path.is_file():
                        anomalies.append(DataAnomaly("error", "label_artifact_missing", f"{role} artifact is missing", family, business_id, str(artifact_path)))
                        continue
                    artifact_hash = sha256_file(artifact_path)
                    if role in REQUIRED_ROAD_GRAPH_ROLES:
                        available_required.add(role)
                    for sample in target_samples:
                        artifacts.append(
                            LabelArtifact(
                                sample_id=sample.sample_id,
                                family=family,
                                business_id=business_id,
                                role=role,
                                artifact_path=str(artifact_path),
                                artifact_sha256=artifact_hash,
                                baseline_id=baseline_id,
                                repo_head=repo_head,
                                baseline_summary_path=str(summary_path),
                                case_run_summary_path=str(run_summary_path),
                                source_case_root=str(source_root / business_id),
                                target_selector=business_id,
                                target_weight=sample.target_weight,
                                context_weight=sample.context_weight,
                            )
                        )
                if available_required == REQUIRED_ROAD_GRAPH_ROLES:
                    selected_cases.add(case_key)
                else:
                    missing = sorted(REQUIRED_ROAD_GRAPH_ROLES - available_required)
                    anomalies.append(
                        DataAnomaly(
                            "error",
                            "road_graph_label_incomplete",
                            f"required label roles missing: {missing}",
                            family,
                            business_id,
                            str(run_summary_path),
                        )
                    )

    roles_by_sample: dict[str, set[str]] = {}
    for artifact in artifacts:
        roles_by_sample.setdefault(artifact.sample_id, set()).add(artifact.role)
    updated_samples: list[TrainingSample] = []
    for sample in samples:
        roles = roles_by_sample.get(sample.sample_id, set())
        road_graph_ready = REQUIRED_ROAD_GRAPH_ROLES.issubset(roles)
        task_mask = dict(sample.task_mask)
        reasons = dict(sample.task_mask_reasons)
        if sample.family.startswith("T10"):
            task_mask["road_graph"] = road_graph_ready
            reasons["road_graph"] = (
                "canonical passed T06 Road/Node lineage available"
                if road_graph_ready
                else "canonical passed T06 Road/Node lineage missing"
            )
            if not road_graph_ready:
                anomalies.append(
                    DataAnomaly(
                        "error",
                        "sample_without_road_graph_truth",
                        "T10 sample cannot train the end-to-end RoadGraph task",
                        sample.family,
                        sample.business_id,
                        sample.case_root,
                    )
                )
        updated_samples.append(replace(sample, task_mask=task_mask, task_mask_reasons=reasons))

    artifacts.sort(key=lambda item: (item.family.casefold(), item.business_id, item.sample_id, item.role))
    anomalies.sort(key=lambda item: (item.severity, item.category, item.family, item.business_id, item.path))
    return updated_samples, artifacts, anomalies


__all__ = ["LABEL_ROLES", "REQUIRED_ROAD_GRAPH_ROLES", "discover_label_artifacts"]
