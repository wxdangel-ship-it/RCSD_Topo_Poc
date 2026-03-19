from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from rcsd_topo_poc.protocol.text_lint import lint_text
from rcsd_topo_poc.protocol.text_qc_bundle import build_demo_bundle, qc_bundle_template


REQUIRED_DOCS = [
    "SPEC.md",
    "docs/PROJECT_BRIEF.md",
    "docs/ARTIFACT_PROTOCOL.md",
    "docs/doc-governance/README.md",
    "docs/repository-metadata/README.md",
    "modules/_template/INTERFACE_CONTRACT.md",
]


def _find_repo_root(start: Path) -> Optional[Path]:
    p = start.resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def _cmd_doctor(_args: argparse.Namespace) -> int:
    root = _find_repo_root(Path.cwd())
    print("RCSD_Topo_Poc doctor")

    if root is None:
        print("RepoRoot: NOT_FOUND (need SPEC.md + docs/)")
        return 1

    print("RepoRoot: OK")

    missing = [rel for rel in REQUIRED_DOCS if not (root / rel).exists()]
    if missing:
        print("Docs: MISSING")
        for rel in missing:
            print(f"- {rel}")
        return 1

    print("Docs: OK")

    pyver = sys.version.split()[0]
    print(f"Python: {pyver}")

    try:
        import rcsd_topo_poc as pkg

        print(f"PackageImport: OK (version={pkg.__version__})")
    except Exception:
        print("PackageImport: FAIL")
        return 1

    return 0


def _cmd_qc_template(_args: argparse.Namespace) -> int:
    print(qc_bundle_template())
    return 0


def _cmd_qc_demo(_args: argparse.Namespace) -> int:
    print(build_demo_bundle())
    return 0


def _cmd_lint_text(args: argparse.Namespace) -> int:
    if args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("No input text provided.", file=sys.stderr)
        return 2

    ok, violations = lint_text(text)
    if ok:
        print("OK")
        for v in violations:
            if v.startswith("LONG_LINE"):
                print(f"- {v}")
        return 0

    print("NOT_PASTEABLE")
    for v in violations:
        print(f"- {v}")
    return 2


def _cmd_t01_step1_pair_poc(args: argparse.Namespace) -> int:
    from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import run_step1_pair_poc_cli

    return run_step1_pair_poc_cli(args)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="rcsd_topo_poc")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Check repo/docs/python environment.")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_tpl = sub.add_parser("qc-template", help="Print TEXT_QC_BUNDLE v1 template.")
    p_tpl.set_defaults(func=_cmd_qc_template)

    p_demo = sub.add_parser("qc-demo", help="Print a demo TEXT_QC_BUNDLE (pasteable + truncated).")
    p_demo.set_defaults(func=_cmd_qc_demo)

    p_lint = sub.add_parser("lint-text", help="Check text pasteability (size/lines/long lines).")
    p_lint.add_argument("--text", help="Text to lint (if omitted, read stdin).")
    p_lint.set_defaults(func=_cmd_lint_text)

    p_t01 = sub.add_parser(
        "t01-step1-pair-poc",
        help="Run T01 Step1 Pair prototype and write QGIS-reviewable outputs.",
    )
    p_t01.add_argument("--road-path", required=True, help="Path to Road Shp/GeoJSON.")
    p_t01.add_argument("--road-layer", help="Optional road layer name.")
    p_t01.add_argument("--road-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_t01.add_argument("--node-path", required=True, help="Path to Node Shp/GeoJSON.")
    p_t01.add_argument("--node-layer", help="Optional node layer name.")
    p_t01.add_argument("--node-crs", help="Optional CRS override, e.g. EPSG:4326.")
    p_t01.add_argument(
        "--strategy-config",
        action="append",
        required=True,
        help="Strategy config path. Repeat the option to run multiple strategies.",
    )
    p_t01.add_argument(
        "--run-id",
        help="Optional run id. If omitted, use t01_step1_pair_poc_YYYYMMDD_HHMMSS.",
    )
    p_t01.add_argument(
        "--out-root",
        help="Optional output root override. If omitted, write to outputs/_work/t01_step1_pair_poc/<run_id>.",
    )
    p_t01.set_defaults(func=_cmd_t01_step1_pair_poc)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as e:
        if isinstance(e, ValueError) and str(e):
            print(f"ERROR: {e}", file=sys.stderr)
        else:
            print(f"ERROR: {type(e).__name__}", file=sys.stderr)
        return 1
