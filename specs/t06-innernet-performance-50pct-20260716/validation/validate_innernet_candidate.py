#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
for import_root in (REPO_ROOT, REPO_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tests.modules.t10_e2e_orchestration.artifact_equivalence import (  # noqa: E402
    STRUCTURED_SUFFIXES,
    _is_excluded_relative_path,
    compare_tree_manifests,
    semantic_fingerprint,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_output_slimming import (  # noqa: E402
    COMPAT_TOP_LEVEL_KEYS,
)


BASELINE_STEP3_INTERNAL_SECONDS = 32207.946
TARGET_STEP3_INTERNAL_SECONDS = 16103.973
BASELINE_T06_WALL_SECONDS = 42928.299
TARGET_T06_WALL_SECONDS = 21464.149
BASELINE_PEAK_RSS_KB = 9365992
T06_RELATIVE_ROOT = Path("t06_segment_fusion_precheck/t06_innernet_precheck")
BUSINESS_FINGERPRINT_VERSION = 2


def parse_elapsed_seconds(value: str) -> float:
    text = value.strip()
    day_count = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        day_count = int(day_text)
    parts = [float(part) for part in text.split(":")]
    if len(parts) == 2:
        hours, minutes, seconds = 0.0, parts[0], parts[1]
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"Unsupported GNU time elapsed value: {value!r}")
    return day_count * 86400.0 + hours * 3600.0 + minutes * 60.0 + seconds


def parse_gnu_time(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")

    def capture(pattern: str) -> str | None:
        match = re.search(pattern, text, flags=re.MULTILINE)
        return match.group(1).strip() if match else None

    elapsed_text = capture(r"^\s*Elapsed \(wall clock\) time \([^)]*\):\s*(\S+)\s*$")
    return {
        "path": str(path),
        "elapsed_text": elapsed_text,
        "wall_seconds": parse_elapsed_seconds(elapsed_text) if elapsed_text else None,
        "user_seconds": _optional_float(capture(r"^\s*User time \(seconds\):\s*(\S+)\s*$")),
        "system_seconds": _optional_float(capture(r"^\s*System time \(seconds\):\s*(\S+)\s*$")),
        "peak_rss_kb": _optional_int(capture(r"^\s*Maximum resident set size \(kbytes\):\s*(\S+)\s*$")),
        "swaps": _optional_int(capture(r"^\s*Swaps:\s*(\S+)\s*$")),
        "exit_status": _optional_int(capture(r"^\s*Exit status:\s*(\S+)\s*$")),
    }


def parse_step3_internal_seconds(path: Path) -> float | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    values = re.findall(r"\[T06 Step3\]\s+stage=read_summary\s+elapsed=([0-9.]+)s", text)
    return float(values[-1]) if values else None


def build_performance_summary(
    *,
    step12_time_path: Path,
    step3_time_path: Path,
    step3_log_path: Path,
) -> dict[str, Any]:
    step12 = parse_gnu_time(step12_time_path)
    step3 = parse_gnu_time(step3_time_path)
    step3_internal = parse_step3_internal_seconds(step3_log_path)
    walls = [step12.get("wall_seconds"), step3.get("wall_seconds")]
    total_wall = sum(float(value) for value in walls) if all(value is not None for value in walls) else None
    peaks = [value for value in (step12.get("peak_rss_kb"), step3.get("peak_rss_kb")) if value is not None]
    peak_rss = max(peaks) if peaks else None
    checks = {
        "step12_exit_zero": step12.get("exit_status") == 0,
        "step3_exit_zero": step3.get("exit_status") == 0,
        "step12_swap_zero": step12.get("swaps") == 0,
        "step3_swap_zero": step3.get("swaps") == 0,
        "step3_internal_at_or_below_50pct": (
            step3_internal is not None and step3_internal <= TARGET_STEP3_INTERNAL_SECONDS
        ),
        "t06_group_wall_sum_at_or_below_50pct": (
            total_wall is not None and total_wall <= TARGET_T06_WALL_SECONDS
        ),
        "peak_rss_not_above_baseline": peak_rss is not None and peak_rss <= BASELINE_PEAK_RSS_KB,
    }
    return {
        "passed": all(checks.values()),
        "baseline": {
            "step3_internal_seconds": BASELINE_STEP3_INTERNAL_SECONDS,
            "t06_wall_seconds_inferred": BASELINE_T06_WALL_SECONDS,
            "peak_rss_kb": BASELINE_PEAK_RSS_KB,
        },
        "targets": {
            "step3_internal_seconds_max": TARGET_STEP3_INTERNAL_SECONDS,
            "t06_group_wall_sum_seconds_max": TARGET_T06_WALL_SECONDS,
            "peak_rss_kb_max": BASELINE_PEAK_RSS_KB,
            "swap_max": 0,
        },
        "candidate": {
            "step12": step12,
            "step3": step3,
            "step3_internal_seconds": step3_internal,
            "t06_group_wall_sum_seconds": total_wall,
            "peak_rss_kb": peak_rss,
        },
        "checks": checks,
    }


def compare_business_outputs(
    *,
    baseline_run_root: Path,
    candidate_run_root: Path,
    out_dir: Path,
) -> dict[str, Any]:
    baseline_t06 = baseline_run_root / T06_RELATIVE_ROOT
    candidate_t06 = candidate_run_root / T06_RELATIVE_ROOT
    if not baseline_t06.is_dir():
        raise FileNotFoundError(f"Baseline T06 root does not exist: {baseline_t06}")
    if not candidate_t06.is_dir():
        raise FileNotFoundError(f"Candidate T06 root does not exist: {candidate_t06}")
    baseline_manifest = _build_tree_manifest_with_progress(
        root=baseline_t06,
        normalization_root=baseline_t06,
        label="baseline",
        checkpoint_path=out_dir / "baseline_t06_semantic_checkpoint.json",
    )
    candidate_manifest = _build_tree_manifest_with_progress(
        root=candidate_t06,
        normalization_root=candidate_t06,
        label="candidate",
        checkpoint_path=out_dir / "candidate_t06_semantic_checkpoint.json",
    )
    _write_json(out_dir / "baseline_t06_semantic_manifest.json", baseline_manifest)
    _write_json(out_dir / "candidate_t06_semantic_manifest.json", candidate_manifest)
    comparison = compare_tree_manifests(baseline_manifest, candidate_manifest)
    stable_reference = {key: value for key, value in baseline_manifest.items() if not key.endswith(".json")}
    stable_candidate = {key: value for key, value in candidate_manifest.items() if not key.endswith(".json")}
    json_reference = {key: value for key, value in baseline_manifest.items() if key.endswith(".json")}
    json_candidate = {key: value for key, value in candidate_manifest.items() if key.endswith(".json")}
    stable_comparison = compare_tree_manifests(stable_reference, stable_candidate)
    json_comparison = compare_tree_manifests(json_reference, json_candidate)
    allowed_json_changes = {
        "step3_segment_replacement/t06_step3_detail_metrics.json",
        "step3_segment_replacement/t06_step3_summary.json",
    }
    unexpected_json_changes = sorted(set(json_comparison["changed"]) - allowed_json_changes)
    summary_consistency = _validate_candidate_step3_summaries(baseline_t06, candidate_t06)
    comparison.update(
        {
            "passed": bool(
                stable_comparison["passed"]
                and not json_comparison["missing_in_candidate"]
                and not json_comparison["extra_in_candidate"]
                and not unexpected_json_changes
                and summary_consistency["passed"]
            ),
            "baseline_t06_root": str(baseline_t06),
            "candidate_t06_root": str(candidate_t06),
            "comparison_scope": (
                "CSV/GPKG/GeoJSON strict business semantics; JSON file-set and non-summary strict semantics; "
                "known compact summary changes require authoritative audit consistency; streaming workers=1"
            ),
            "stable_artifacts": stable_comparison,
            "json_artifacts": json_comparison,
            "allowed_json_changes": sorted(allowed_json_changes),
            "unexpected_json_changes": unexpected_json_changes,
            "candidate_summary_consistency": summary_consistency,
        }
    )
    return comparison


def _validate_candidate_step3_summaries(baseline_t06: Path, candidate_t06: Path) -> dict[str, Any]:
    step3_root = candidate_t06 / "step3_segment_replacement"
    baseline_step3_root = baseline_t06 / "step3_segment_replacement"
    if not step3_root.is_dir():
        return {"passed": True, "applicable": False, "checks": {}}
    summary_path = step3_root / "t06_step3_summary.json"
    detail_path = step3_root / "t06_step3_detail_metrics.json"
    audit_path = step3_root / "t06_step3_topology_connectivity_audit.csv"
    try:
        baseline_summary = json.loads(
            (baseline_step3_root / "t06_step3_summary.json").read_text(encoding="utf-8")
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        with audit_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "applicable": True,
            "checks": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
    statuses = Counter(str(row.get("audit_status") or "") for row in rows)
    layers = Counter(
        (str(row.get("audit_layer") or ""), str(row.get("audit_status") or ""))
        for row in rows
    )
    topology = summary.get("topology") if isinstance(summary.get("topology"), dict) else {}
    checks: dict[str, bool] = {
        "compact_schema": summary.get("summary_schema") == "t06_step3_summary_compact_v1",
        "summary_audit_row_count": _as_int(topology.get("audit_row_count")) == len(rows),
        "detail_audit_row_count": _as_int(detail.get("topology_connectivity_audit_row_count")) == len(rows),
    }
    for status in ("fail", "warn", "pass"):
        expected = statuses[status]
        checks[f"summary_{status}_count"] = _as_int(topology.get(f"{status}_count")) == expected
        checks[f"summary_compat_{status}_count"] = (
            _as_int(summary.get(f"topology_connectivity_{status}_count")) == expected
        )
        checks[f"detail_{status}_count"] = (
            _as_int(detail.get(f"topology_connectivity_{status}_count")) == expected
        )
    for (layer, status), expected in sorted(layers.items()):
        checks[f"summary_layer::{layer}::{status}"] = (
            _as_int(topology.get(f"{layer}_{status}_count")) == expected
        )
        checks[f"detail_layer::{layer}::{status}"] = (
            _as_int(detail.get(f"topology_connectivity_{layer}_{status}_count")) == expected
        )
    final_rows = [row for row in rows if _truthy(row.get("counts_in_final_frcsd_topology_fail"))]
    keys_by_category = {
        category: {
            str(row.get("final_topology_object_key") or "")
            for row in final_rows
            if str(row.get("final_topology_category") or "") == category
            and str(row.get("final_topology_object_key") or "")
        }
        for category in ("segment_transition", "independent_attachment")
    }
    final_expected = {
        "final_frcsd_topology_fail_row_count": len(final_rows),
        "final_frcsd_segment_transition_fail_count": len(keys_by_category["segment_transition"]),
        "final_frcsd_independent_attachment_fail_count": len(keys_by_category["independent_attachment"]),
    }
    final_expected["final_frcsd_topology_fail_count"] = (
        final_expected["final_frcsd_segment_transition_fail_count"]
        + final_expected["final_frcsd_independent_attachment_fail_count"]
    )
    for key, expected in final_expected.items():
        checks[f"summary_{key}"] = _as_int(summary.get(key)) == expected
        checks[f"detail_{key}"] = _as_int(detail.get(key)) == expected
    checks["summary_topology_audit_fail_row_count"] = (
        _as_int(summary.get("topology_audit_fail_row_count")) == statuses["fail"]
    )
    checks["detail_topology_audit_fail_row_count"] = (
        _as_int(detail.get("topology_audit_fail_row_count")) == statuses["fail"]
    )
    topology_compat_keys = {
        key
        for key in COMPAT_TOP_LEVEL_KEYS
        if key.startswith("topology_connectivity_")
        or key.startswith("final_frcsd_topology_")
        or key
        in {
            "topology_audit_fail_row_count",
            "final_frcsd_segment_transition_fail_count",
            "final_frcsd_independent_attachment_fail_count",
        }
    }
    compared_compat_keys: list[str] = []
    for key in COMPAT_TOP_LEVEL_KEYS:
        if key in topology_compat_keys or key not in baseline_summary:
            continue
        compared_compat_keys.append(key)
        checks[f"summary_compat_business::{key}"] = summary.get(key) == baseline_summary.get(key)
        checks[f"detail_compat_business::{key}"] = detail.get(key) == baseline_summary.get(key)
    return {
        "passed": all(checks.values()),
        "applicable": True,
        "checks": checks,
        "audit_row_count": len(rows),
        "audit_status_counts": dict(sorted(statuses.items())),
        "compared_compat_business_keys": compared_compat_keys,
        "failed_checks": sorted(key for key, passed in checks.items() if not passed),
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _build_tree_manifest_with_progress(
    *,
    root: Path,
    normalization_root: Path,
    label: str,
    checkpoint_path: Path,
) -> dict[str, dict[str, Any]]:
    paths = _structured_paths(root)
    expected = {path.relative_to(root).as_posix() for path in paths}
    manifest = {
        key: value
        for key, value in _read_json_mapping(checkpoint_path).items()
        if key in expected and isinstance(value, dict)
    }
    started = time.perf_counter()
    for index, path in enumerate(paths, start=1):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        cached = manifest.get(relative)
        reused = bool(
            cached
            and cached.get("size_bytes") == stat.st_size
            and cached.get("mtime_ns") == stat.st_mtime_ns
            and cached.get("fingerprint_version") == BUSINESS_FINGERPRINT_VERSION
            and cached.get("sha256")
        )
        if not reused:
            fingerprint = _business_fingerprint(path, root=normalization_root)
            manifest[relative] = {
                "kind": fingerprint["kind"],
                "sha256": fingerprint["sha256"],
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "fingerprint_version": BUSINESS_FINGERPRINT_VERSION,
            }
            del fingerprint
            _write_json(checkpoint_path, manifest)
        print(
            f"[BUSINESS_COMPARE] label={label} file={index}/{len(paths)} "
            f"reused={int(reused)} elapsed={time.perf_counter() - started:.3f}s path={relative}",
            flush=True,
        )
    return dict(sorted(manifest.items()))


def _business_fingerprint(path: Path, *, root: Path) -> dict[str, str]:
    fingerprint = semantic_fingerprint(path, root=root)
    payload = fingerprint["payload"]
    if fingerprint["kind"] == "vector":
        layers = payload.get("layers") if isinstance(payload, dict) else None
        if isinstance(layers, list):
            for layer in layers:
                if not isinstance(layer, dict):
                    continue
                name = str(layer.get("name") or "")
                layer["name"] = re.sub(r"^[0-9a-fA-F]{16}_", "", name)
            layers.sort(key=lambda layer: str(layer.get("name") or ""))
    payload = _normalize_t06_runtime_paths(payload)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return {
        "kind": str(fingerprint["kind"]),
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _normalize_t06_runtime_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_t06_runtime_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_t06_runtime_paths(item) for item in value]
    if not isinstance(value, str):
        return value
    normalized = value.replace("\\", "/")
    for marker in (
        "step1_identify_fusion_units",
        "step2_extract_rcsd_segments",
        "step3_segment_replacement",
    ):
        token = f"/{marker}/"
        index = normalized.find(token)
        if index >= 0:
            return "<T06>" + normalized[index:]
    return normalized


def _structured_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory, _, filenames in os.walk(root):
        for filename in filenames:
            path = Path(directory) / filename
            relative = path.relative_to(root).as_posix()
            if path.suffix.lower() in STRUCTURED_SUFFIXES and not _is_excluded_relative_path(relative):
                paths.append(path)
    return sorted(paths, key=lambda item: item.as_posix())


def _read_json_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def run_validation(args: argparse.Namespace) -> dict[str, Any]:
    baseline_root = args.baseline_run_root.resolve()
    candidate_root = args.candidate_run_root.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    performance = build_performance_summary(
        step12_time_path=out_dir / "t06_step12.time.txt",
        step3_time_path=out_dir / "t06_step3.time.txt",
        step3_log_path=candidate_root / "logs/t06_step3.log",
    )
    business = compare_business_outputs(
        baseline_run_root=baseline_root,
        candidate_run_root=candidate_root,
        out_dir=out_dir,
    )
    return {
        "schema_version": 1,
        "baseline_run_root": str(baseline_root),
        "candidate_run_root": str(candidate_root),
        "performance": performance,
        "business": business,
        "overall_passed": bool(performance["passed"] and business["passed"]),
    }


def _optional_float(value: str | None) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value: str | None) -> int | None:
    return int(value) if value is not None else None


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an isolated full-innernet T06 candidate.")
    parser.add_argument("--baseline-run-root", type=Path, required=True)
    parser.add_argument("--candidate-run-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        summary = run_validation(args)
    except Exception as exc:
        summary = {
            "schema_version": 1,
            "baseline_run_root": str(args.baseline_run_root),
            "candidate_run_root": str(args.candidate_run_root),
            "overall_passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(out_dir / "t06_innernet_validation_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0 if summary.get("overall_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
