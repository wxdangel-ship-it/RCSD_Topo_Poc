#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
for import_root in (REPO_ROOT, REPO_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from rcsd_topo_poc.modules.t10_e2e_orchestration.text_bundle import (  # noqa: E402
    decode_t10_case_evidence_text_bundle,
    export_t10_case_evidence_text_bundle,
)


MAX_TEXT_BYTES = 250 * 1024


def collect(args: argparse.Namespace) -> tuple[Path, ...]:
    repo = args.repo.resolve()
    candidate = args.candidate_run_root.resolve()
    evidence_dir = args.evidence_dir.resolve()
    package_dir = evidence_dir / "handoff_package"
    bundle_dir = evidence_dir / "handoff_bundle"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    for name in (
        "t06_innernet_validation_summary.json",
        "baseline_t06_semantic_manifest.json",
        "candidate_t06_semantic_manifest.json",
        "t06_step12.time.txt",
        "t06_step3.time.txt",
        "t11_t09.time.txt",
    ):
        _copy_if_file(evidence_dir / name, package_dir / name)
    _copy_if_file(candidate / "t06_perf_validation.status", package_dir / "t06_perf_validation.status")
    _copy_if_file(
        candidate / "t10_innernet_full_pipeline_manifest.json",
        package_dir / "t10_innernet_full_pipeline_manifest.json",
    )
    for stage in ("t06_step12", "t06_step3", "t11", "t09"):
        _write_tail(candidate / f"logs/{stage}.log", package_dir / f"{stage}_tail.log")
    _write_tail(evidence_dir / "launcher.log", package_dir / "launcher_tail.log")
    _write_tail(evidence_dir / "validation.log", package_dir / "validation_tail.log")
    _write_json(package_dir / "environment.json", _environment(repo))
    _write_json(package_dir / "t06_output_inventory.json", _inventory(candidate))
    _write_json(
        package_dir / "t10_case_evidence_manifest.json",
        {
            "schema_version": 1,
            "bundle_type": "t06_innernet_performance_validation",
            "candidate_run_root": str(candidate),
            "files": sorted(path.name for path in package_dir.iterdir() if path.is_file()),
        },
    )

    target = bundle_dir / "t06_innernet_validation_bundle.txt"
    artifacts = export_t10_case_evidence_text_bundle(
        package_dir=package_dir,
        out_txt=target,
        max_text_size_bytes=MAX_TEXT_BYTES,
    )
    with tempfile.TemporaryDirectory(prefix="t06_innernet_bundle_verify_") as temp_dir:
        decode_t10_case_evidence_text_bundle(
            bundle_txt=artifacts.part_txt_paths[0],
            out_dir=Path(temp_dir),
        )
    return artifacts.part_txt_paths


def _copy_if_file(source: Path, target: Path) -> None:
    if source.is_file():
        shutil.copy2(source, target)


def _write_tail(source: Path, target: Path, *, lines: int = 1200, max_chars: int = 180_000) -> None:
    if not source.is_file():
        return
    values = source.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    text = "\n".join(values) + "\n"
    target.write_text(text[-max_chars:], encoding="utf-8")


def _environment(repo: Path) -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "repo": str(repo),
        "repo_head": _command(["git", "-C", str(repo), "rev-parse", "HEAD"]),
        "repo_status": _command(["git", "-C", str(repo), "status", "--short"]),
        "dmesg_oom_tail": _command(["bash", "-lc", "dmesg --ctime 2>&1 | grep -Ei 'oom|killed process' | tail -n 80"]),
    }


def _inventory(candidate: Path) -> list[dict[str, Any]]:
    root = candidate / "t06_segment_fusion_precheck/t06_innernet_precheck"
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix.lower() not in {".gpkg", ".gpkt", ".geojson", ".csv", ".json"}:
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command(command: list[str]) -> str:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return (completed.stdout + completed.stderr).strip()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect a <=250KiB-per-part T06 validation text bundle.")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--candidate-run-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser


def main() -> int:
    parts = collect(build_parser().parse_args())
    for path in parts:
        print(f"[BUNDLE] {path} bytes={path.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
