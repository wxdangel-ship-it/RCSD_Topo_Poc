#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rcsd_topo_poc.modules.p04_road_direct_generation import (  # noqa: E402
    SegmentFirstConfig,
)


Runner = Callable[[SegmentFirstConfig], Any]
PROGRESS_HEARTBEAT_SECONDS = 30.0


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
) -> int:
    args = _parse_args(argv)
    _log_progress("[1/4] Validating input paths and runtime configuration.")
    config = _build_config(args)

    from rcsd_topo_poc.modules.p04_road_direct_generation.io import (
        discover_patch_dirs,
    )

    patch_dirs = discover_patch_dirs(config.patch_root)
    config.validate_paths()
    _log_progress(
        f"[1/4] Input validation completed. run_id={config.run_id}, "
        f"analysis_crs={config.analysis_crs}."
    )
    _log_progress(
        f"[2/4] Discovered {len(patch_dirs)} Patch directories: "
        f"{_summarize_patch_ids(patch_dirs)}."
    )
    if runner is None:
        from rcsd_topo_poc.modules.p04_road_direct_generation import (
            run_segment_first_road_direct,
        )

        runner = run_segment_first_road_direct

    _log_progress("[3/4] Starting Segment-first Road generation.")
    started_at = time.monotonic()
    result = _run_with_progress_heartbeat(runner, config, started_at=started_at)
    elapsed_seconds = time.monotonic() - started_at
    _log_progress(
        f"[3/4] Segment-first Road generation completed in "
        f"{elapsed_seconds:.1f}s."
    )
    payload = {
        "process_completed": True,
        "run_id": result.run_id,
        "patch_count": len(patch_dirs),
        "patch_ids": [path.name for path in patch_dirs],
        "analysis_crs": config.analysis_crs,
        "output_dir": str(result.output_dir),
        "terminal_status": result.terminal_status,
        "core_gate_pass": result.core_gate_pass,
        "formal_gpkg": str(result.formal_gpkg),
        "audit_gpkg": str(result.audit_gpkg),
        "relations_gpkg": str(result.relations_gpkg),
        "summary_path": str(result.summary_path),
        "report_path": str(result.report_path),
        "independent_quality_path": str(result.independent_quality_path),
        "qgis_project_path": (
            str(result.qgis_project_path)
            if result.qgis_project_path is not None
            else None
        ),
    }
    _log_progress(
        f"[4/4] Outputs completed. terminal_status={result.terminal_status}, "
        f"core_gate_pass={result.core_gate_pass}."
    )
    _log_progress(f"[4/4] Summary: {result.summary_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    if args.require_core_pass and not result.core_gate_pass:
        _log_progress("Run finished with exit_code=2 because the core gate failed.")
        return 2
    _log_progress("Run finished with exit_code=0.")
    return 0


def _run_with_progress_heartbeat(
    runner: Runner,
    config: SegmentFirstConfig,
    *,
    started_at: float,
) -> Any:
    stop_event = threading.Event()

    def report_progress() -> None:
        while not stop_event.wait(PROGRESS_HEARTBEAT_SECONDS):
            elapsed_seconds = time.monotonic() - started_at
            _log_progress(
                f"[3/4] Segment-first Road generation is still running; "
                f"elapsed={elapsed_seconds:.1f}s."
            )

    reporter = threading.Thread(
        target=report_progress,
        name="p04-progress-reporter",
        daemon=True,
    )
    reporter.start()
    try:
        return runner(config)
    finally:
        stop_event.set()
        reporter.join(timeout=1.0)


def _log_progress(message: str) -> None:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{timestamp}] [P04] {message}", file=sys.stderr, flush=True)


def _summarize_patch_ids(patch_dirs: Sequence[Path], *, limit: int = 10) -> str:
    patch_ids = [path.name for path in patch_dirs]
    visible_ids = patch_ids[:limit]
    if len(patch_ids) > limit:
        visible_ids.append(f"...(+{len(patch_ids) - limit})")
    return ", ".join(visible_ids)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the P04 SWSD-first Segment-first Road direct-generation POC. "
            "Patch data is provided as one directory; every other business input "
            "is provided as an explicit file path."
        )
    )
    parser.add_argument(
        "--patch-root",
        type=Path,
        required=True,
        help="<PatchID>/Vector directory collection root.",
    )
    parser.add_argument("--swsd-road", type=Path, required=True, help="Original SWSD Road vector file.")
    parser.add_argument("--swsd-node", type=Path, required=True, help="Original SWSD Node vector file.")
    parser.add_argument("--t01-road", type=Path, required=True, help="T01 roads.gpkg file.")
    parser.add_argument("--t01-node", type=Path, required=True, help="T01 nodes.gpkg file.")
    parser.add_argument("--t01-segment", type=Path, required=True, help="T01 segment.gpkg file.")
    parser.add_argument("--t07-surface", type=Path, required=True, help="T07 accepted surface vector file.")
    parser.add_argument("--t03-surface", type=Path, required=True, help="T03 accepted surface vector file.")
    parser.add_argument("--t04-surface", type=Path, required=True, help="T04 accepted surface vector file.")
    parser.add_argument("--full-rcsd-road", type=Path, required=True, help="Full-map RCSD Road vector file.")
    parser.add_argument("--full-rcsd-node", type=Path, required=True, help="Full-map RCSD Node vector file.")
    parser.add_argument(
        "--target-replaceability",
        type=Path,
        help="Optional T06 replaceability vector/CSV file.",
    )
    parser.add_argument(
        "--target-disposition",
        type=Path,
        help="Optional externally confirmed DirectBuild disposition JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New or empty output directory. It must not overlap an input path.",
    )
    parser.add_argument("--run-id", required=True, help="Stable audit run identifier.")
    parser.add_argument(
        "--analysis-crs",
        default="EPSG:32650",
        help="Projected analysis CRS. Default: EPSG:32650.",
    )
    parser.add_argument(
        "--require-core-pass",
        action="store_true",
        help=(
            "Return exit code 2 when P04 core gates fail. By default a completed "
            "POC run returns 0 and reports terminal_status/core_gate_pass in JSON."
        ),
    )
    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace) -> SegmentFirstConfig:
    return SegmentFirstConfig(
        patch_root=_require_directory(args.patch_root, "patch_root"),
        swsd_road_path=_require_file(args.swsd_road, "swsd_road"),
        swsd_node_path=_require_file(args.swsd_node, "swsd_node"),
        t01_road_path=_require_file(args.t01_road, "t01_road"),
        t01_node_path=_require_file(args.t01_node, "t01_node"),
        t01_segment_path=_require_file(args.t01_segment, "t01_segment"),
        t07_surface_path=_require_file(args.t07_surface, "t07_surface"),
        t03_surface_path=_require_file(args.t03_surface, "t03_surface"),
        t04_surface_path=_require_file(args.t04_surface, "t04_surface"),
        full_rcsd_road_path=_require_file(args.full_rcsd_road, "full_rcsd_road"),
        full_rcsd_node_path=_require_file(args.full_rcsd_node, "full_rcsd_node"),
        target_replaceability_path=_optional_file(
            args.target_replaceability,
            "target_replaceability",
        ),
        target_disposition_path=_optional_file(
            args.target_disposition,
            "target_disposition",
        ),
        output_dir=args.output_dir.expanduser().resolve(),
        run_id=args.run_id,
        analysis_crs=args.analysis_crs,
    ).resolved()


def _require_directory(path: Path, role: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"{role} directory does not exist: {resolved}")
    return resolved


def _require_file(path: Path, role: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{role} file does not exist: {resolved}")
    return resolved


def _optional_file(path: Path | None, role: str) -> Path | None:
    if path is None:
        return None
    return _require_file(path, role)


if __name__ == "__main__":
    raise SystemExit(main())
