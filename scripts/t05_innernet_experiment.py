#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rcsd_topo_poc.modules.t05_junction_surface_fusion import (  # noqa: E402
    backfill_t03_relation_evidence,
    run_t05_junction_surface_fusion,
)
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_runner import (  # noqa: E402
    run_t05_phase2_rcsd_junctionization_and_relation,
)


DEFAULT_T02_DIR = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_internal_step1_step2/stage2/t02_stage2_internal_20260519_115056"
DEFAULT_T03_DIR = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t03_internal_full_input/t03_internal_full_input_innernet_flat_review_20260519_130230"
DEFAULT_T04_DIR = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t04_internal_full_input/t04_internal_full_20260520_000716"
DEFAULT_RCSDROAD = "/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg"
DEFAULT_RCSDNODE = "/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg"
DEFAULT_NODES = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg"
DEFAULT_OUT_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment"
T02_ANCHOR_SURFACE_FILENAME = "t02_rcsdintersection_anchor_surface.gpkg"
T07_ANCHOR_SURFACE_FILENAME = "t07_rcsdintersection_anchor_surface.gpkg"
T02_RELATION_EVIDENCE_FILENAMES = (
    "t02_swsd_rcsd_relation_evidence.csv",
    "t02_swsd_rcsd_relation_evidence.json",
)
T07_RELATION_EVIDENCE_FILENAMES = (
    "t07_swsd_rcsd_relation_evidence.csv",
    "t07_swsd_rcsd_relation_evidence.json",
)


def main() -> int:
    args = _parse_args()
    t02_dir = Path(args.t02_dir)
    t07_dir = Path(args.t07_dir) if args.t07_dir else None
    t03_dir = Path(args.t03_dir)
    t04_dir = Path(args.t04_dir)
    out_root = Path(args.out_root)
    t07_mode = _uses_t07(args)

    t02_evidence = _resolve_t02_evidence(args=args, t02_dir=t02_dir, t07_mode=t07_mode)
    t07_evidence = _resolve_t07_file(args.t07_evidence, t07_dir, T07_RELATION_EVIDENCE_FILENAMES)
    t02_input = _resolve_phase1_input(args=args, t02_dir=t02_dir, t07_dir=t07_dir)
    t03_evidence = _resolve_file(args.t03_evidence, t03_dir, "t03_swsd_rcsd_relation_evidence.csv")
    t04_evidence = _resolve_file(args.t04_evidence, t04_dir, "t04_swsd_rcsd_relation_evidence.csv")
    t03_surface = _resolve_file(args.t03_surface, t03_dir, "virtual_intersection_polygons.gpkg")
    t04_surface = _resolve_file(args.t04_surface, t04_dir, "divmerge_virtual_anchor_surface.gpkg")
    t04_summary = _resolve_optional_file(
        args.t04_summary,
        t04_dir,
        ("divmerge_virtual_anchor_surface_summary.csv", "divmerge_virtual_anchor_surface_summary.json"),
    )
    t04_audit = _resolve_optional_file(args.t04_audit, t04_dir, ("divmerge_virtual_anchor_surface_audit.gpkg",))
    t04_case_root = Path(args.t04_case_root) if args.t04_case_root else _default_case_root(t04_dir)

    t03_phase2_evidence, t03_backfill = _resolve_t03_phase2_evidence(
        args=args,
        t03_dir=t03_dir,
        t03_evidence=t03_evidence,
        out_root=out_root,
    )

    print("[T05 innernet] run Phase 1", flush=True)
    phase1 = run_t05_junction_surface_fusion(
        t02_rcsdintersection_path=t02_input,
        t03_surface_path=t03_surface,
        t04_surface_path=t04_surface,
        nodes_path=args.nodes,
        out_root=out_root,
        run_id=args.phase1_run_id,
    )

    print("[T05 innernet] run Phase 2", flush=True)
    phase2 = run_t05_phase2_rcsd_junctionization_and_relation(
        junction_surface_path=phase1.surface_path,
        fusion_audit_path=phase1.audit_csv_path,
        nodes_path=args.nodes,
        rcsdroad_path=args.rcsdroad,
        rcsdnode_path=args.rcsdnode,
        t02_relation_evidence_path=t02_evidence,
        t03_relation_evidence_path=t03_phase2_evidence,
        t04_relation_evidence_path=t04_evidence,
        t07_relation_evidence_path=t07_evidence,
        t04_surface_path=t04_surface,
        t04_summary_path=t04_summary,
        t04_audit_path=t04_audit,
        t04_case_root=t04_case_root,
        out_root=out_root,
        run_id=args.phase2_run_id,
        progress=True,
        progress_interval=args.progress_interval,
        readonly_workers=args.readonly_workers,
    )

    phase1_summary = _read_json(phase1.summary_path)
    phase2_summary = _read_json(phase2.summary_path)
    print(
        json.dumps(
            {
                "inputs": {
                    "t02_dir": str(t02_dir),
                    "t07_dir": str(t07_dir) if t07_dir else None,
                    "t03_dir": str(t03_dir),
                    "t04_dir": str(t04_dir),
                    "rcsdroad": str(args.rcsdroad),
                    "rcsdnode": str(args.rcsdnode),
                    "nodes": str(args.nodes),
                    "t05_phase1_existing_intersection_input": str(t02_input),
                    "t02_evidence": str(t02_evidence) if t02_evidence else None,
                    "t07_evidence": str(t07_evidence) if t07_evidence else None,
                    "t03_evidence": str(t03_phase2_evidence),
                    "t03_backfill_mode": args.t03_backfill_mode,
                    "t03_backfill_summary": str(t03_backfill.summary_path) if t03_backfill else None,
                },
                "phase1": {
                    "run_root": str(phase1.run_root),
                    "surface": str(phase1.surface_path),
                    "audit_csv": str(phase1.audit_csv_path),
                    "summary": str(phase1.summary_path),
                    "published_surface_count": phase1_summary.get("published_surface_count"),
                    "skipped_count": phase1_summary.get("skipped_count"),
                    "conflict_count": phase1_summary.get("conflict_count"),
                },
                "phase2": {
                    "run_root": str(phase2.run_root),
                    "relation": str(phase2.relation_geojson_path),
                    "summary": str(phase2.summary_path),
                    "relation_count": phase2.relation_count,
                    "success_count": phase2.success_count,
                    "failure_count": phase2.failure_count,
                    "blocking_error_count": phase2_summary.get("blocking_error_count"),
                    "passed": phase2_summary.get("passed"),
                    "performance": phase2_summary.get("performance"),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run T05 Phase 1 and Phase 2 against innernet T07/T03/T04 outputs; legacy T02 inputs remain supported.")
    parser.add_argument("--t02-dir", default=DEFAULT_T02_DIR)
    parser.add_argument("--t07-dir", default=None)
    parser.add_argument("--t03-dir", default=DEFAULT_T03_DIR)
    parser.add_argument("--t04-dir", default=DEFAULT_T04_DIR)
    parser.add_argument("--rcsdroad", default=DEFAULT_RCSDROAD)
    parser.add_argument("--rcsdnode", default=DEFAULT_RCSDNODE)
    parser.add_argument("--nodes", default=DEFAULT_NODES)
    parser.add_argument(
        "--t02-input",
        default=None,
        help=(
            "Optional explicit T02_INPUT surface path. Defaults to "
            f"{T02_ANCHOR_SURFACE_FILENAME} discovered under --t02-dir."
        ),
    )
    parser.add_argument(
        "--t07-input",
        default=None,
        help=(
            "Optional explicit T07 existing-intersection surface path. Defaults to "
            f"{T07_ANCHOR_SURFACE_FILENAME} discovered under --t07-dir when --t07-dir is provided."
        ),
    )
    parser.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    parser.add_argument("--t02-evidence", default=None)
    parser.add_argument("--t07-evidence", default=None)
    parser.add_argument(
        "--include-legacy-t02-evidence",
        action="store_true",
        help=(
            "Include legacy T02 relation evidence even when T07 inputs are provided. "
            "By default T07 mode disables automatic T02 evidence discovery."
        ),
    )
    parser.add_argument("--t03-evidence", default=None)
    parser.add_argument("--t04-evidence", default=None)
    parser.add_argument("--t03-surface", default=None)
    parser.add_argument("--t04-surface", default=None)
    parser.add_argument("--t04-summary", default=None)
    parser.add_argument("--t04-audit", default=None)
    parser.add_argument("--t04-case-root", default=None)
    parser.add_argument("--phase1-run-id", default="t05_phase1_innernet")
    parser.add_argument("--phase2-run-id", default="t05_phase2_innernet")
    parser.add_argument("--readonly-workers", type=int, default=4)
    parser.add_argument("--progress-interval", type=int, default=1000)
    parser.add_argument("--t03-accepted-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--t03-backfill-mode",
        choices=("auto", "always", "never"),
        default="auto",
        help=(
            "Controls T03 relation evidence compatibility backfill. "
            "auto runs only when old T03 evidence lacks Phase 2 handoff fields; "
            "always forces backfill; never consumes T03 evidence as-is. Defaults to auto."
        ),
    )
    return parser.parse_args()


def _uses_t07(args: argparse.Namespace) -> bool:
    return bool(args.t07_dir or args.t07_input or args.t07_evidence)


def _resolve_t02_evidence(*, args: argparse.Namespace, t02_dir: Path, t07_mode: bool) -> Path | None:
    if t07_mode and not args.t02_evidence and not args.include_legacy_t02_evidence:
        return None
    return _resolve_optional_file(args.t02_evidence, t02_dir, T02_RELATION_EVIDENCE_FILENAMES)


def _resolve_file(explicit_path: str | None, root: Path, filename: str) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if path.is_file():
            return path
        raise FileNotFoundError(f"configured path does not exist: {path}")
    direct = root / filename
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(filename))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"missing {filename} under {root}")


def _resolve_t07_file(explicit_path: str | None, root: Path | None, filenames: tuple[str, ...]) -> Path | None:
    if explicit_path:
        path = Path(explicit_path)
        if path.is_file():
            return path
        raise FileNotFoundError(f"configured path does not exist: {path}")
    if root is None:
        return None
    resolved = _resolve_optional_file(None, root, filenames)
    if resolved is not None:
        return resolved
    raise FileNotFoundError(f"missing one of {', '.join(filenames)} under {root}")


def _resolve_phase1_input(*, args: argparse.Namespace, t02_dir: Path, t07_dir: Path | None) -> Path:
    if args.t07_input:
        path = Path(args.t07_input)
        if path.is_file():
            return path
        raise FileNotFoundError(f"configured path does not exist: {path}")
    if args.t02_input:
        path = Path(args.t02_input)
        if path.is_file():
            return path
        raise FileNotFoundError(f"configured path does not exist: {path}")
    if t07_dir is not None:
        return _resolve_file(None, t07_dir, T07_ANCHOR_SURFACE_FILENAME)
    return _resolve_file(args.t02_input, t02_dir, T02_ANCHOR_SURFACE_FILENAME)


def _resolve_t03_phase2_evidence(
    *,
    args: argparse.Namespace,
    t03_dir: Path,
    t03_evidence: Path,
    out_root: Path,
):
    mode = args.t03_backfill_mode
    should_backfill = mode == "always" or (mode == "auto" and _t03_backfill_needed(t03_evidence))
    if mode == "never" or not should_backfill:
        print(f"[T05 innernet] use T03 evidence as-is mode={mode}", flush=True)
        return t03_evidence, None
    print(f"[T05 innernet] backfill T03 evidence mode={mode}", flush=True)
    backfilled = backfill_t03_relation_evidence(
        t03_run_root=t03_dir,
        relation_evidence_path=t03_evidence,
        out_root=out_root / "t03_backfill",
        accepted_only=args.t03_accepted_only,
    )
    return backfilled.evidence_csv_path, backfilled


def _t03_backfill_needed(path: Path) -> bool:
    rows = _read_table_rows(path)
    for row in rows:
        if not _t03_accepted_surface(row):
            continue
        relation_state = _text(row.get("relation_state"))
        if relation_state == "success_required_rcsd_junction" and not _has_any_value(
            row,
            ("base_id_candidate", "required_rcsdnode_ids", "required_rcsd_node_ids"),
        ):
            return True
        if relation_state == "rcsd_present_not_junction" and not _has_any_value(
            row,
            ("support_rcsdroad_ids", "selected_rcsdroad_ids", "required_rcsdroad_ids"),
        ):
            return True
        if relation_state in {"", "ambiguous_review", "step7_accepted"} and not _has_any_value(
            row,
            (
                "base_id_candidate",
                "required_rcsdnode_ids",
                "required_rcsd_node_ids",
                "support_rcsdroad_ids",
                "selected_rcsdroad_ids",
                "required_rcsdroad_ids",
            ),
        ):
            return True
    return False


def _read_table_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            return [dict(row) for row in payload["rows"] if isinstance(row, dict)]
        if isinstance(payload, list):
            return [dict(row) for row in payload if isinstance(row, dict)]
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return [dict(row) for row in csv.DictReader(fp)]


def _t03_accepted_surface(row: dict) -> bool:
    return _text(row.get("step7_state")) == "accepted" or _truthy(row.get("surface_candidate_present"))


def _has_any_value(row: dict, fields: tuple[str, ...]) -> bool:
    return any(_split_values(row.get(field)) for field in fields)


def _split_values(value) -> list[str]:
    if value in (None, "", -1, "-1", 0, "0"):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item or "").strip() and str(item).strip() not in {"-1", "0"}]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace(",", "|").split("|") if part.strip() and part.strip() not in {"-1", "0"}]


def _truthy(value) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "y", "accepted"}


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _resolve_optional_file(explicit_path: str | None, root: Path, filenames: tuple[str, ...]) -> Path | None:
    if explicit_path:
        path = Path(explicit_path)
        if path.is_file():
            return path
        raise FileNotFoundError(f"configured path does not exist: {path}")
    for filename in filenames:
        direct = root / filename
        if direct.is_file():
            return direct
        matches = sorted(root.rglob(filename))
        if matches:
            return matches[0]
    return None


def _default_case_root(t04_dir: Path) -> Path:
    cases_dir = t04_dir / "cases"
    return cases_dir if cases_dir.is_dir() else t04_dir


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
