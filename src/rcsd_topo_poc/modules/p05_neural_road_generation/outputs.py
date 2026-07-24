from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.p05_neural_road_generation.models import (
    DataAnomaly,
    LabelArtifact,
    SplitAssignment,
    TrainingSample,
    sha256_file,
)


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for raw in rows:
            writer.writerow({key: _json_value(value) if isinstance(value, (dict, list, tuple)) else value for key, value in raw.items()})


def _sample_rows(samples: list[TrainingSample]) -> list[dict[str, Any]]:
    return [sample.to_dict() for sample in samples]


def build_summary(
    samples: list[TrainingSample],
    artifacts: list[LabelArtifact],
    assignments: list[SplitAssignment],
    anomalies: list[DataAnomaly],
    oracle: dict[str, Any],
    *,
    duration_seconds: float,
) -> dict[str, Any]:
    family_counts = Counter(sample.family for sample in samples)
    split_counts = Counter(assignment.split for assignment in assignments)
    fold_counts = Counter(str(assignment.fold) for assignment in assignments)
    anomaly_counts = Counter(f"{item.severity}:{item.category}" for item in anomalies)
    road_graph_samples = sum(bool(sample.task_mask.get("road_graph")) for sample in samples)
    usable_samples = sum(any(sample.task_mask.values()) for sample in samples)
    t10_samples = sum(sample.family.startswith("T10") for sample in samples)
    return {
        "schema_version": "p05-m0-summary-v1",
        "sample_count": len(samples),
        "sample_group_count": len({sample.sample_group_id for sample in samples}),
        "family_counts": dict(sorted(family_counts.items())),
        "label_artifact_count": len(artifacts),
        "road_graph_training_sample_count": road_graph_samples,
        "usable_sample_count": usable_samples,
        "usable_sample_rate": usable_samples / len(samples) if samples else 0.0,
        "t10_road_graph_sample_count": t10_samples,
        "t10_road_graph_usable_rate": road_graph_samples / t10_samples if t10_samples else 0.0,
        "split_counts": dict(sorted(split_counts.items())),
        "fold_counts": dict(sorted(fold_counts.items())),
        "anomaly_count": len(anomalies),
        "anomaly_counts": dict(sorted(anomaly_counts.items())),
        "oracle_case_count": int(oracle.get("case_count", 0)),
        "oracle_evaluated_case_count": int(oracle.get("evaluated_case_count", oracle.get("case_count", 0))),
        "oracle_quarantined_count": int(oracle.get("quarantined_count", 0)),
        "approved_exclusion_count": int(oracle.get("approved_exclusion_count", 0)),
        "oracle_passed_count": int(oracle.get("passed_count", 0)),
        "oracle_all_passed": bool(oracle.get("all_passed")),
        "corruption_suite_all_detected": bool(oracle.get("corruption_suite", {}).get("all_detected")),
        "duration_seconds": duration_seconds,
    }


def _report(summary: dict[str, Any]) -> str:
    family_lines = "\n".join(f"- `{name}`: {count}" for name, count in summary["family_counts"].items())
    anomaly_lines = "\n".join(f"- `{name}`: {count}" for name, count in summary["anomaly_counts"].items()) or "- 无"
    return f"""# P05 M0 数据与度量基准报告

## 结论

- 样本：{summary['sample_count']}，稳定业务分组：{summary['sample_group_count']}。
- 可用于 T06 RoadGraph 监督的样本：{summary['road_graph_training_sample_count']}。
- 任一任务可训练比例：{summary['usable_sample_rate']:.2%}；T10 RoadGraph 可训练比例：{summary['t10_road_graph_usable_rate']:.2%}。
- 标签 artifacts：{summary['label_artifact_count']}。
- Oracle：{summary['oracle_passed_count']}/{summary['oracle_case_count']} 个可用 Case passed；用户确认排除 {summary['approved_exclusion_count']} 个，另有 {summary['oracle_quarantined_count']} 个待复评 canonical truth 异常 Case。
- 定向破坏检测：{'全部检出' if summary['corruption_suite_all_detected'] else '存在未检出项'}。
- 总耗时：{summary['duration_seconds']:.3f} 秒。

## Case 家族

{family_lines}

## 异常

总数：{summary['anomaly_count']}。

{anomaly_lines}

## 边界

M0 只建立训练真值、lineage、grouped split 和 T06 F-RCSD Road/Node 评估基准，不包含正式神经网络训练。异常不会被 silent fix；需人工重评的对象保留在 `p05_data_anomalies.csv`。
"""


def write_m0_outputs(
    run_root: Path,
    *,
    samples: list[TrainingSample],
    artifacts: list[LabelArtifact],
    assignments: list[SplitAssignment],
    anomalies: list[DataAnomaly],
    oracle: dict[str, Any],
    manifest: dict[str, Any],
    duration_seconds: float,
) -> dict[str, Any]:
    summary = build_summary(samples, artifacts, assignments, anomalies, oracle, duration_seconds=duration_seconds)
    sample_fields = list(TrainingSample.__dataclass_fields__)
    artifact_fields = list(LabelArtifact.__dataclass_fields__)
    split_fields = list(SplitAssignment.__dataclass_fields__)
    anomaly_fields = list(DataAnomaly.__dataclass_fields__)
    paths = {
        "samples": run_root / "p05_training_samples.csv",
        "artifacts": run_root / "p05_label_artifacts.csv",
        "split": run_root / "p05_grouped_split.csv",
        "anomalies": run_root / "p05_data_anomalies.csv",
        "oracle": run_root / "p05_oracle_evaluation.json",
        "summary": run_root / "p05_m0_summary.json",
        "report": run_root / "p05_m0_report.md",
    }
    _write_csv(paths["samples"], _sample_rows(samples), sample_fields)
    _write_csv(paths["artifacts"], (item.to_dict() for item in artifacts), artifact_fields)
    _write_csv(paths["split"], (item.to_dict() for item in assignments), split_fields)
    _write_csv(paths["anomalies"], (item.to_dict() for item in anomalies), anomaly_fields)
    _write_json(paths["oracle"], oracle)
    _write_json(paths["summary"], summary)
    paths["report"].write_text(_report(summary), encoding="utf-8")
    manifest_payload = dict(manifest)
    manifest_payload["outputs"] = {
        name: {"path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        for name, path in paths.items()
    }
    manifest_path = run_root / "p05_m0_manifest.json"
    _write_json(manifest_path, manifest_payload)
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["build_summary", "write_m0_outputs"]
