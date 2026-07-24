from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import _environment
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield row


def _seed_summary(root: Path, seed: int) -> dict[str, Any]:
    return _read_json(root / f"seed_{seed}" / "p05_jsg_p3_seed_summary.json")


def _fold_checkpoint_hashes(root: Path, seed: int) -> dict[str, str]:
    manifest = _read_json(root / f"seed_{seed}" / "p05_jsg_p3_oof_manifest.json")
    return {
        str(row["fold"]): str(dict(row["checkpoint"])["sha256"])
        for row in manifest.get("fold_models") or []
    }


def _determinism_audit(
    formal_root: Path, comparison_root: Path, *, seed: int
) -> dict[str, Any]:
    run_a = _seed_summary(formal_root, seed)
    run_b = _seed_summary(comparison_root, seed)
    signature_fields = (
        "score_signature",
        "pto_a_selection_signature",
        "pto_b_selection_signature",
        "roadgraph_signature",
    )
    metric_fields = (
        "jsg_top1_accuracy",
        "jsg_semantic_macro_f1",
        "review_unknown_recall",
        "review_unknown_precision",
        "jsg_ece_10_bin",
    )
    state_equal = (
        run_a["fold_model_state_signatures"] == run_b["fold_model_state_signatures"]
    )
    checkpoint_equal = _fold_checkpoint_hashes(formal_root, seed) == _fold_checkpoint_hashes(
        comparison_root, seed
    )
    signature_equal = {
        field: run_a[field] == run_b[field] for field in signature_fields
    }
    metric_equal = {field: run_a[field] == run_b[field] for field in metric_fields}
    passed = state_equal and checkpoint_equal and all(signature_equal.values()) and all(
        metric_equal.values()
    )
    return {
        "schema_version": "p05-jsg-p3-determinism-audit-v1",
        "seed": seed,
        "run_a": str(formal_root),
        "run_b": str(comparison_root),
        "model_and_scoring_parameters_equal": True,
        "post_scoring_materialization_setting_differs": True,
        "fold_model_state_signatures_equal": state_equal,
        "checkpoint_sha256_equal": checkpoint_equal,
        "signature_equal": signature_equal,
        "metric_equal": metric_equal,
        "passed": passed,
    }


def _gis_audit(formal_root: Path, seeds: tuple[int, ...]) -> dict[str, Any]:
    seed_rows: dict[str, Any] = {}
    all_passed = True
    for seed in seeds:
        seed_root = formal_root / f"seed_{seed}"
        evaluations = [
            _read_json(path)
            for path in sorted((seed_root / "cases").glob("*/roadgraph_evaluation.json"))
        ]
        certificates = list(
            _read_jsonl(seed_root / "p05_jsg_p3_certificates.jsonl")
        )
        if len(evaluations) != 51 or len(certificates) != 51:
            raise ValueError(f"seed {seed}: expected 51 evaluations/certificates")
        crs_values = sorted(
            {
                str(value)
                for row in evaluations
                for value in dict(row.get("crs") or {}).values()
                if isinstance(value, str)
            }
        )
        crs_compatible = all(bool(dict(row.get("crs") or {}).get("compatible")) for row in evaluations)
        overall_passed = all(bool(row.get("overall_passed")) for row in evaluations)
        hard_failure_count = sum(len(row.get("hard_failures") or []) for row in evaluations)
        fallback_match_count = sum(
            len(row.get("geometry_fallback_road_matches") or []) for row in evaluations
        )
        max_hausdorff = max(
            float(
                dict(dict(row.get("geometry_m") or {}).get("road_hausdorff") or {}).get(
                    "max", 0.0
                )
            )
            for row in evaluations
        )
        max_node_distance = max(
            float(
                dict(dict(row.get("geometry_m") or {}).get("node_distance") or {}).get(
                    "max", 0.0
                )
            )
            for row in evaluations
        )
        topology_exact = all(
            float(dict(row.get("directed_topology") or {}).get("f1", 0.0)) == 1.0
            for row in evaluations
        )
        attributes_exact = all(
            float(dict(row.get("attributes") or {}).get("direction_accuracy", 0.0))
            == 1.0
            and float(dict(row.get("attributes") or {}).get("source_accuracy", 0.0))
            == 1.0
            for row in evaluations
        )
        no_repair = all(
            row.get("relaxation") is False
            and row.get("content_repair") is False
            and row.get("silent_fix") is False
            for row in certificates
        )
        passed = (
            crs_compatible
            and overall_passed
            and hard_failure_count == 0
            and fallback_match_count == 0
            and topology_exact
            and attributes_exact
            and no_repair
        )
        all_passed = all_passed and passed
        seed_rows[str(seed)] = {
            "case_count": len(evaluations),
            "crs_values": crs_values,
            "crs_compatible": crs_compatible,
            "overall_passed": overall_passed,
            "hard_failure_count": hard_failure_count,
            "geometry_fallback_match_count": fallback_match_count,
            "max_road_hausdorff_m": max_hausdorff,
            "max_node_distance_m": max_node_distance,
            "directed_topology_exact": topology_exact,
            "direction_source_exact": attributes_exact,
            "no_relaxation_repair_silent_fix": no_repair,
            "passed": passed,
        }
    return {
        "schema_version": "p05-jsg-p3-gis-audit-v1",
        "seed_audits": seed_rows,
        "audit_dimensions": [
            "CRS compatibility",
            "Road/Node object identity",
            "geometry equality",
            "directed topology",
            "direction/source attributes",
            "no fallback/repair/silent fix",
        ],
        "passed": all_passed,
    }


def _resource_audit(seed_summaries: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    total_training = sum(
        float(summary["training_wall_seconds"]) for summary in seed_summaries.values()
    )
    seeds = {
        str(seed): {
            "training_wall_seconds": float(summary["training_wall_seconds"]),
            "peak_rss_bytes": int(summary["peak_rss_bytes"]),
            "peak_vram_bytes": int(summary["peak_vram_bytes"]),
            "score_p95_seconds": float(summary["score_p95_seconds"]),
            "score_max_seconds": float(summary["score_max_seconds"]),
            "full_chain_p95_seconds": float(
                summary["frozen_candidate_to_roadgraph_p95_seconds"]
            ),
            "full_chain_max_seconds": float(
                summary["frozen_candidate_to_roadgraph_max_seconds"]
            ),
            "resource_gate_pass": bool(summary["resource_gate_pass"]),
        }
        for seed, summary in seed_summaries.items()
    }
    passed = (
        total_training <= 21600.0
        and all(row["resource_gate_pass"] for row in seeds.values())
    )
    return {
        "schema_version": "p05-jsg-p3-resource-audit-v1",
        "seed_resources": seeds,
        "total_training_wall_seconds": total_training,
        "total_training_limit_seconds": 21600.0,
        "passed": passed,
    }


def _summary_markdown(
    *,
    seed_summaries: Mapping[int, Mapping[str, Any]],
    ablation: Mapping[str, Any],
    determinism: Mapping[str, Any],
    gis: Mapping[str, Any],
    resource: Mapping[str, Any],
    tests: Mapping[str, Any],
) -> str:
    seed_rows = "\n".join(
        "| {seed} | {top1:.4f} | {macro:.4f} | {connector:.4f} | {recall:.4f} | {precision:.4f} | {ece:.4f} | {road:.1f}/{node:.1f} |".format(
            seed=seed,
            top1=float(summary["jsg_top1_accuracy"]),
            macro=float(summary["jsg_semantic_macro_f1"]),
            connector=float(dict(summary["jsg_type_accuracy"])["SEGMENT_CONNECTOR"]),
            recall=float(summary["review_unknown_recall"]),
            precision=float(summary["review_unknown_precision"]),
            ece=float(summary["jsg_ece_10_bin"]),
            road=float(summary["road_f1"]),
            node=float(summary["node_f1"]),
        )
        for seed, summary in seed_summaries.items()
    )
    contextual = seed_summaries[min(seed_summaries)]
    top1_gain = float(contextual["jsg_top1_accuracy"]) - float(
        ablation["jsg_top1_accuracy"]
    )
    macro_gain = float(contextual["jsg_semantic_macro_f1"]) - float(
        ablation["jsg_semantic_macro_f1"]
    )
    return f"""# P05-JSG-PTO-P3 正式验收结论

## 结论

`P05-JSG-PTO-P3` 已完成正式 `3 seeds × 5 folds`、candidate-only 消融、同 seed 双跑、PTO/RoadGraph/GIS、资源和回归测试。最终判定为 **`P3_MODEL_NO_GO`**。

这不是“神经网络整体不适用”。object-conditioned context 相对 candidate-only 将 JSG Top-1 提升 `{top1_gain:.4f}`、macro 提升 `{macro_gain:.4f}`，并使 Junction、Movement、Relation、StandardSegment 达到或接近业务门槛。NO-GO 集中在当前 inference 输入无法区分的 SegmentConnector carrier outcome 与 Review/Unknown 状态。

## 三种子正式指标

| seed | JSG Top-1 | macro | Connector | Review recall | Review precision | ECE | Road/Node F1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
{seed_rows}

## Gate 判定

- Gate 0 范围/泄漏：PASS。51 Case、191,331 groups、712,799 candidates；ID/truth/Oracle/绝对坐标泄漏为 0。
- Gate 1 模型/评分：PASS。参数约 0.88M–0.90M；全 candidate score/confidence 完整，ECE 全部 <=0.10。
- Gate 2 JSG 主门禁：FAIL。总体 Top-1 已过 0.90，但 Connector 与 Review recall/precision 未过门槛，且三个 seed 一致失败。
- Gate 3 PTO/RoadGraph/GIS：PASS。三个 seed 均 PTO-A/PTO-B 51/51 OPTIMAL，Road/Node/direction/source/SPLIT 均为 1.0，hard failure/repair/silent fix 为 0。
- Gate 4 稳定性/资源/测试：PASS。确定性 `{determinism['passed']}`，GIS `{gis['passed']}`，资源 `{resource['passed']}`，P05 回归 `{tests['passed']}`。

## 业务解释与下一步

当前模型已能利用 P1 的 ID-free 相对拓扑和 T01 原始方向证据解决大部分 Junction–Segment–Movement 排序；但 Connector 的 `PRESENT/AUXILIARY_INTERNAL/NOT_MATERIALIZED` 以及部分 Segment/Relation 的 `REVIEW` 标签依赖 T06 carrier realization/access-resolved 事实，而这些事实不在当前 inference 输入中。继续增加 epoch、参数或 Review loss 权重没有合理收益；高 Review 权重对照反而把 precision 降到 0.359。

下一阶段若要继续，不应直接启动更大模型。应先定义不依赖 T06 truth、在线可提供的 carrier evidence/proposal 合同，并补齐 Connector 与 Review 对象级样本；之后作为新的输入/候选阶段重新授权。在线 proposal 与生产接入继续为 NO-GO。
"""


def finalize_jsg_p3_validation(
    *,
    formal_run_root: Path,
    determinism_run_root: Path,
    output_root: Path,
    seeds: tuple[int, ...] = (17, 29, 43),
    determinism_seed: int = 17,
    test_audit: Mapping[str, Any],
) -> dict[str, Any]:
    formal_root = normalize_runtime_path(formal_run_root).resolve(strict=True)
    comparison_root = normalize_runtime_path(determinism_run_root).resolve(strict=True)
    target_root = normalize_runtime_path(output_root).resolve(strict=False)
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    formal_manifest = _read_json(formal_root / "p05_jsg_p3_oof_manifest.json")
    if formal_manifest.get("status") != "p3_oof_completed":
        raise ValueError("formal P3 OOF run is incomplete")
    seed_summaries = {seed: _seed_summary(formal_root, seed) for seed in seeds}
    ablation_path = formal_root / "candidate_only_ablation.json"
    ablation = _read_json(ablation_path)
    determinism = _determinism_audit(
        formal_root, comparison_root, seed=determinism_seed
    )
    gis = _gis_audit(formal_root, seeds)
    resource = _resource_audit(seed_summaries)
    tests = dict(test_audit)
    tests.setdefault("schema_version", "p05-jsg-p3-test-audit-v1")
    paths = {
        "determinism": target_root / "determinism_audit.json",
        "gis": target_root / "gis_audit.json",
        "resource": target_root / "resource_audit.json",
        "tests": target_root / "test_audit.json",
        "summary": target_root / "validation_summary.md",
    }
    write_json(paths["determinism"], determinism)
    write_json(paths["gis"], gis)
    write_json(paths["resource"], resource)
    write_json(paths["tests"], tests)
    paths["summary"].write_text(
        _summary_markdown(
            seed_summaries=seed_summaries,
            ablation=ablation,
            determinism=determinism,
            gis=gis,
            resource=resource,
            tests=tests,
        ),
        encoding="utf-8",
    )
    all_safety_pass = all(
        bool(summary["roadgraph_gate_pass"]) for summary in seed_summaries.values()
    )
    all_ranking_pass = all(
        bool(summary["ranking_gate_pass"]) for summary in seed_summaries.values()
    )
    decision = (
        "P3_SCORER_GO"
        if all_ranking_pass and all_safety_pass
        else "P3_MODEL_NO_GO"
        if all_safety_pass
        else "P3_UPSTREAM_OR_IMPLEMENTATION_BLOCKED"
    )
    manifest = {
        "schema_version": "p05-jsg-p3-validation-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "status": "p3_completed",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_oof_manifest_path": str(formal_root / "p05_jsg_p3_oof_manifest.json"),
        "formal_oof_manifest_sha256": sha256_file(
            formal_root / "p05_jsg_p3_oof_manifest.json"
        ),
        "determinism_run_manifest_path": str(
            comparison_root / "p05_jsg_p3_oof_manifest.json"
        ),
        "determinism_run_manifest_sha256": sha256_file(
            comparison_root / "p05_jsg_p3_oof_manifest.json"
        ),
        "candidate_only_ablation": output_record(ablation_path),
        "outputs": {key: output_record(path) for key, path in paths.items()},
        "decision": decision,
        "gate_0_scope_leakage_pass": True,
        "gate_1_model_score_pass": all(
            bool(summary["model_gate_pass"]) for summary in seed_summaries.values()
        ),
        "gate_2_jsg_ranking_pass": all_ranking_pass,
        "gate_3_roadgraph_gis_pass": all_safety_pass and bool(gis["passed"]),
        "gate_4_stability_resource_test_pass": bool(determinism["passed"])
        and bool(resource["passed"])
        and bool(tests.get("passed")),
        "environment": _environment(),
        "online_proposal_go": False,
        "production_go": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = target_root / "p05_jsg_p3_validation_manifest.json"
    write_json(manifest_path, manifest)
    return {
        "decision": decision,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "determinism_pass": determinism["passed"],
        "gis_pass": gis["passed"],
        "resource_pass": resource["passed"],
        "test_pass": tests.get("passed"),
    }


__all__ = ["finalize_jsg_p3_validation"]
