#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "src").is_dir():
            return candidate
    return None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "T08 Tool11: organize every Patch into SWSD/RCSD/FRCSD trees and "
            "publish an independent experiment Patch subset."
        )
    )
    parser.add_argument(
        "--source-root",
        required=True,
        help="Source root containing numeric <PatchID> directories.",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Destination root for every organized Patch.",
    )
    parser.add_argument(
        "--experiment-output-root",
        required=True,
        help="Independent destination root for experiment Patches.",
    )
    parser.add_argument(
        "--experiment-patch-id",
        action="append",
        dest="experiment_patch_ids",
        help=(
            "Experiment PatchID. Repeat to replace the six default PatchIDs; "
            "omit all occurrences to use the defaults."
        ),
    )
    parser.add_argument(
        "--summary-output",
        help=(
            "Optional audit summary path ending in _tool11.json. "
            "Default: unique timestamped file beside --output-root."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace both existing output roots only after full copy and SHA-256 verification.",
    )
    parser.add_argument(
        "--progress-interval-files",
        type=int,
        default=100,
        help="Print progress after every N copied source files. Default: 100.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t08_preprocess import (
        T08PatchDataOrganizationError,
        run_t08_patch_data_organization,
    )

    args = _parse_args(argv)
    try:
        artifacts = run_t08_patch_data_organization(
            source_root=Path(args.source_root),
            output_root=Path(args.output_root),
            experiment_output_root=Path(args.experiment_output_root),
            experiment_patch_ids=args.experiment_patch_ids,
            summary_output=(Path(args.summary_output) if args.summary_output else None),
            overwrite=args.overwrite,
            progress_callback=_print_progress,
            progress_interval_files=args.progress_interval_files,
        )
    except T08PatchDataOrganizationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if exc.summary_json is not None:
            print(f"summary_json={exc.summary_json}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {key: str(value) for key, value in artifacts.__dict__.items()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
