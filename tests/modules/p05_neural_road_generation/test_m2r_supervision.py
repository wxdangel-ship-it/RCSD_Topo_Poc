from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_supervision import (
    M2RSupervisionConfig,
    TaskTarget,
    _apply_historical_targets,
    build_m2r_supervision,
    derive_task_targets,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_historical import HistoricalTarget


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample(
    sample_id: str,
    family: str,
    business_id: str,
    manifest: Path,
    *,
    scope_type: str,
    target_weight: float,
    context_weight: float,
) -> dict[str, str]:
    return {
        "sample_id": sample_id,
        "family": family,
        "business_id": business_id,
        "sample_group_id": f"junction:{business_id}" if scope_type == "single_junction_object" else f"segment:{business_id}",
        "scope_type": scope_type,
        "case_root": str(manifest.parent),
        "manifest_path": str(manifest),
        "manifest_sha256": _sha(manifest),
        "target_weight": str(target_weight),
        "context_weight": str(context_weight),
        "task_mask": json.dumps({"object_scene": True, "road_graph": scope_type != "single_junction_object"}),
        "task_mask_reasons": "{}",
        "source_metadata": "{}",
    }


def _artifact(sample: dict[str, str], role: str, path: Path) -> dict[str, str]:
    return {
        "sample_id": sample["sample_id"],
        "family": sample["family"],
        "business_id": sample["business_id"],
        "role": role,
        "artifact_path": str(path),
        "artifact_sha256": _sha(path),
        "baseline_id": "baseline",
        "repo_head": "abc",
        "baseline_summary_path": "summary.json",
        "case_run_summary_path": "case-summary.json",
        "source_case_root": sample["case_root"],
        "target_selector": sample["business_id"],
        "target_weight": sample["target_weight"],
        "context_weight": sample["context_weight"],
    }


def _target(targets, sample_id: str, task_name: str, target_kind: str):
    return next(
        target
        for target in targets
        if target.sample_id == sample_id and target.task_name == task_name and target.target_kind == target_kind
    )


def test_single_point_case_only_enables_proven_object_scope(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"mainnodeid": 101, "epsg": 3857}), encoding="utf-8")
    sample = _sample("t03_error:101:v1", "T03_Error", "101", manifest, scope_type="single_junction_object", target_weight=1.0, context_weight=0.3)

    targets, anomalies = derive_task_targets(
        [sample],
        [],
        [{"sample_id": sample["sample_id"], "sample_group_id": sample["sample_group_id"], "fold": "2", "split": "train"}],
        approved_exclusions=set(),
    )

    object_scope = _target(targets, sample["sample_id"], "T03", "object_scope")
    assert object_scope.availability == "available"
    assert object_scope.trust_tier == "gold"
    assert object_scope.target_weight == 1.0
    assert _target(targets, sample["sample_id"], "T03", "surface").availability == "unknown"
    assert _target(targets, sample["sample_id"], "T03", "relation").availability == "unknown"
    assert _target(targets, sample["sample_id"], "T04", "object_scope").availability == "unknown"
    assert not [item for item in anomalies if item.severity == "error"]


def test_t10_roles_map_to_task_targets_without_using_family_as_label(tmp_path: Path) -> None:
    manifest = tmp_path / "t10_case_evidence_manifest.json"
    manifest.write_text(json.dumps({"scope": {"swsd_segment_id": "s1"}}), encoding="utf-8")
    sample = _sample("t10_error:s1:v1", "T10-Error", "s1", manifest, scope_type="t10_segment", target_weight=0.7, context_weight=0.3)
    role_paths: dict[str, Path] = {}
    for role in (
        "t03_nodes",
        "t04_nodes",
        "t05_intersection_match_all",
        "t05_rcsdroad_out",
        "t05_rcsdnode_out",
        "t06_frcsd_road",
        "t06_frcsd_node",
        "t06_swsd_frcsd_segment_relation",
        "t07_nodes",
    ):
        path = tmp_path / f"{role}.json"
        path.write_text("{}", encoding="utf-8")
        role_paths[role] = path
    artifacts = [_artifact(sample, role, path) for role, path in role_paths.items()]

    targets, anomalies = derive_task_targets(
        [sample],
        artifacts,
        [{"sample_id": sample["sample_id"], "sample_group_id": sample["sample_group_id"], "fold": "3", "split": "train"}],
        approved_exclusions=set(),
    )

    assert _target(targets, sample["sample_id"], "T03", "nodes").availability == "available"
    assert _target(targets, sample["sample_id"], "T04", "nodes").availability == "available"
    assert _target(targets, sample["sample_id"], "T05", "relation").availability == "available"
    assert _target(targets, sample["sample_id"], "T06", "road").availability == "available"
    assert _target(targets, sample["sample_id"], "T07", "nodes").availability == "available"
    assert _target(targets, sample["sample_id"], "T03", "surface").availability == "unknown"
    assert all(target.trust_tier != "negative" for target in targets)
    assert not [item for item in anomalies if item.severity == "error"]


def test_approved_exclusion_closes_every_task(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    sample = _sample("t10_error:bad:v1", "T10-Error", "bad", manifest, scope_type="t10_segment", target_weight=0.7, context_weight=0.3)

    targets, _ = derive_task_targets(
        [sample],
        [],
        [{"sample_id": sample["sample_id"], "sample_group_id": sample["sample_group_id"], "fold": "0", "split": "test"}],
        approved_exclusions={("T10-Error", "bad")},
    )

    assert targets
    assert {target.availability for target in targets} == {"excluded"}
    assert {target.trust_tier for target in targets} == {"unknown"}


def test_user_confirmed_strategy_replay_uses_frozen_single_point_weights(tmp_path: Path) -> None:
    label_path = tmp_path / "surface.json"
    label_path.write_text("{}", encoding="utf-8")
    unknown = TaskTarget(
        sample_id="t03:101:v1",
        sample_group_id="junction:101",
        family="T03",
        business_id="101",
        fold=2,
        split="train",
        task_name="T03",
        target_kind="surface",
        availability="unknown",
        trust_tier="unknown",
        target_weight=0.0,
        context_weight=0.0,
        target_selector="101",
        artifact_role="",
        artifact_path="",
        artifact_sha256="",
        crs="",
        source_run="",
        reason="no_traceable_target_artifact",
    )
    replay = HistoricalTarget(
        sample_id=unknown.sample_id,
        task_name="T03",
        target_kind="surface",
        artifact_path=str(label_path),
        artifact_sha256=_sha(label_path),
        crs="EPSG:3857",
        source_run="replay",
        target_selector="101",
        reason="user_confirmed_strategy_replay_terminal_surface_exact_input_manifest_match",
    )

    targets, anomalies = _apply_historical_targets([unknown], [replay])

    assert not anomalies
    assert targets[0].availability == "available"
    assert targets[0].trust_tier == "gold"
    assert targets[0].target_weight == 1.0
    assert targets[0].context_weight == 0.3


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_build_supervision_writes_immutable_hashed_contract(tmp_path: Path) -> None:
    case_root = tmp_path / "POC_Data" / "T03" / "101"
    case_root.mkdir(parents=True)
    manifest = case_root / "manifest.json"
    manifest.write_text(json.dumps({"mainnodeid": 101, "epsg": 3857}), encoding="utf-8")
    sample = _sample("t03:101:v1", "T03", "101", manifest, scope_type="single_junction_object", target_weight=1.0, context_weight=0.3)
    m0_root = tmp_path / "m0"
    m0_root.mkdir()
    samples_path = m0_root / "p05_training_samples.csv"
    artifacts_path = m0_root / "p05_label_artifacts.csv"
    split_path = m0_root / "p05_grouped_split.csv"
    anomalies_path = m0_root / "p05_data_anomalies.csv"
    oracle_path = m0_root / "p05_oracle_evaluation.json"
    summary_path = m0_root / "p05_m0_summary.json"
    _write_csv(samples_path, [sample])
    _write_csv(
        artifacts_path,
        [
            {
                "sample_id": "unused",
                "family": "T10",
                "business_id": "unused",
                "role": "unused",
                "artifact_path": "unused",
                "artifact_sha256": "unused",
                "baseline_id": "unused",
                "repo_head": "unused",
                "baseline_summary_path": "unused",
                "case_run_summary_path": "unused",
                "source_case_root": "unused",
                "target_selector": "unused",
                "target_weight": "0.3",
                "context_weight": "0.3",
            }
        ],
    )
    _write_csv(split_path, [{"sample_id": sample["sample_id"], "sample_group_id": sample["sample_group_id"], "fold": "2", "split": "train"}])
    _write_csv(anomalies_path, [{"severity": "info", "category": "none", "detail": "none", "family": "", "business_id": "", "path": ""}])
    oracle_path.write_text("{}", encoding="utf-8")
    summary_path.write_text("{}", encoding="utf-8")
    outputs = {}
    for role, path in {
        "samples": samples_path,
        "artifacts": artifacts_path,
        "split": split_path,
        "anomalies": anomalies_path,
        "oracle": oracle_path,
        "summary": summary_path,
    }.items():
        outputs[role] = {"path": str(path), "sha256": _sha(path), "size_bytes": path.stat().st_size}
    (m0_root / "p05_m0_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "p05-m0-manifest-v1",
                "run_id": "m0",
                "poc_data_root": str(tmp_path / "POC_Data"),
                "silent_fix": False,
                "approved_exclusions": [],
                "outputs": outputs,
            }
        ),
        encoding="utf-8",
    )

    result = build_m2r_supervision(
        M2RSupervisionConfig(
            m0_run_root=m0_root,
            output_root=tmp_path / "out",
            run_id="m2r",
            enforce_poc_scope=False,
        )
    )

    run_root = tmp_path / "out" / "m2r"
    output_manifest = json.loads((run_root / "p05_m2r_supervision_manifest.json").read_text(encoding="utf-8"))
    assert result["sample_count"] == 1
    assert result["available_target_count"] == 1
    assert output_manifest["silent_fix"] is False
    assert output_manifest["outputs"]["targets"]["sha256"] == _sha(run_root / "p05_m2r_task_targets.csv")
    assert not (run_root / "p05_m2r_task_targets.csv").read_text(encoding="utf-8-sig").find("negative") >= 0
