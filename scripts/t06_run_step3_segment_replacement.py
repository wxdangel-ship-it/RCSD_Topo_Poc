#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (  # noqa: E402
    run_t06_step3_segment_replacement,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_surface_topology_audit import (  # noqa: E402
    run_surface_topology_postprocess,
)


DEFAULT_SWSD_SEGMENT = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg"
DEFAULT_SWSD_ROADS = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg"
DEFAULT_SWSD_NODES = "/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg"
DEFAULT_T05_PHASE2_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet"
DEFAULT_T06_RUN_ROOT = "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck"


def main() -> int:
    args = _parse_args()
    t06_run_root = Path(args.t06_run_root)
    t05_phase2_root = Path(args.t05_phase2_root)
    step2_replaceable = _resolve_file(args.step2_replaceable, t06_run_root / "step2_extract_rcsd_segments", "t06_rcsd_segment_replaceable.gpkg")
    special_group_audit = _resolve_optional_file(
        args.step2_special_junction_group_audit,
        t06_run_root / "step2_extract_rcsd_segments",
        "t06_special_junction_group_audit.json",
    )
    group_replacement_audit = _resolve_optional_file(
        args.step2_group_replacement_audit,
        t06_run_root / "step2_extract_rcsd_segments",
        "t06_segment_group_replacement_audit.gpkg",
    )
    rcsdroad = _resolve_file(args.rcsdroad, t05_phase2_root, "rcsdroad_out.gpkg")
    rcsdnode = _resolve_file(args.rcsdnode, t05_phase2_root, "rcsdnode_out.gpkg")
    out_root = Path(args.out_root) if args.out_root else t06_run_root.parent
    run_id = args.run_id or t06_run_root.name

    inputs = {
        "step2_replaceable_path": step2_replaceable,
        "step2_special_junction_group_audit_path": special_group_audit,
        "step2_group_replacement_audit_path": group_replacement_audit,
        "swsd_segment_path": _require_file(args.swsd_segment),
        "swsd_roads_path": _require_file(args.swsd_roads),
        "swsd_nodes_path": _require_file(args.swsd_nodes),
        "rcsdroad_path": rcsdroad,
        "rcsdnode_path": rcsdnode,
        "t07_surface_path": _optional_file_arg(args.t07_surface),
        "t03_surface_path": _optional_file_arg(args.t03_surface),
        "t04_surface_path": _optional_file_arg(args.t04_surface),
        "t04_audit_path": _optional_file_arg(args.t04_audit),
        "t05_surface_path": _optional_file_arg(args.t05_surface),
    }

    print("[T06 Step3] run segment replacement from Step2 replaceable outputs", flush=True)
    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=inputs["step2_replaceable_path"],
        step2_special_junction_group_audit_path=inputs["step2_special_junction_group_audit_path"],
        step2_group_replacement_audit_path=inputs["step2_group_replacement_audit_path"],
        swsd_segment_path=inputs["swsd_segment_path"],
        swsd_roads_path=inputs["swsd_roads_path"],
        swsd_nodes_path=inputs["swsd_nodes_path"],
        rcsdroad_path=inputs["rcsdroad_path"],
        rcsdnode_path=inputs["rcsdnode_path"],
        out_root=out_root,
        run_id=run_id,
        progress=args.progress,
    )
    surface_inputs = {
        key: inputs[key]
        for key in ("t07_surface_path", "t03_surface_path", "t04_surface_path", "t04_audit_path", "t05_surface_path")
    }
    surface_topology = None
    if any(surface_inputs.values()):
        surface_topology = run_surface_topology_postprocess(
            step_root=artifacts.step_root,
            swsd_segment_path=inputs["swsd_segment_path"],
            swsd_roads_path=inputs["swsd_roads_path"],
            t07_surface_path=inputs["t07_surface_path"],
            t03_surface_path=inputs["t03_surface_path"],
            t04_surface_path=inputs["t04_surface_path"],
            t04_audit_path=inputs["t04_audit_path"],
            t05_surface_path=inputs["t05_surface_path"],
            apply_closure=args.surface_topology_closure,
        )
    summary = _read_json(artifacts.summary_path)
    print(
        json.dumps(
            {
                "inputs": {key: str(value) if value is not None else None for key, value in inputs.items()},
                "run_id": artifacts.run_id,
                "run_root": str(artifacts.run_root),
                "step3": {
                    "run_root": str(artifacts.step_root),
                    "frcsd_road": str(artifacts.frcsd_road_gpkg_path),
                    "frcsd_node": str(artifacts.frcsd_node_gpkg_path),
                    "replacement_units": str(artifacts.replacement_units_gpkg_path),
                    "junction_rebuild_audit": str(artifacts.junction_rebuild_audit_gpkg_path),
                    "summary": str(artifacts.summary_path),
                    "input_replaceable_count": summary.get("input_replaceable_count"),
                    "replacement_unit_success_count": summary.get("replacement_unit_success_count"),
                    "removed_swsd_road_count": summary.get("removed_swsd_road_count"),
                    "removed_swsd_node_count": summary.get("removed_swsd_node_count"),
                    "added_rcsd_road_count": summary.get("added_rcsd_road_count"),
                    "added_rcsd_node_count": summary.get("added_rcsd_node_count"),
                    "junction_c_count": summary.get("junction_c_count"),
                    "road_id_collision_count": summary.get("road_id_collision_count"),
                    "node_id_collision_count": summary.get("node_id_collision_count"),
                    "frcsd_road_count": summary.get("frcsd_road_count"),
                    "frcsd_node_count": summary.get("frcsd_node_count"),
                    "topology_connectivity_fail_count": summary.get("topology_connectivity_fail_count"),
                    "surface_topology": surface_topology,
                    "outputs": summary.get("outputs"),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run T06 Step3 segment replacement from Step2 replaceable outputs.")
    parser.add_argument("--t06-run-root", default=DEFAULT_T06_RUN_ROOT, help="T06 run root containing step2_extract_rcsd_segments.")
    parser.add_argument("--step2-replaceable", default=None, help="Explicit t06_rcsd_segment_replaceable.gpkg path.")
    parser.add_argument("--step2-special-junction-group-audit", default=None, help="Explicit t06_special_junction_group_audit.json path. Defaults to the Step2 output beside replaceable when present.")
    parser.add_argument("--step2-group-replacement-audit", default=None, help="Explicit t06_segment_group_replacement_audit.gpkg path. Defaults to the Step2 output beside replaceable when present.")
    parser.add_argument("--swsd-segment", default=DEFAULT_SWSD_SEGMENT, help="T01 segment.gpkg path.")
    parser.add_argument("--swsd-roads", default=DEFAULT_SWSD_ROADS, help="SWSD roads.gpkg path.")
    parser.add_argument("--swsd-nodes", default=DEFAULT_SWSD_NODES, help="Final SWSD nodes.gpkg path.")
    parser.add_argument("--t05-phase2-root", default=DEFAULT_T05_PHASE2_ROOT, help="T05 Phase 2 root containing rcsdroad_out.gpkg and rcsdnode_out.gpkg.")
    parser.add_argument("--rcsdroad", default=None, help="Explicit rcsdroad_out.gpkg path.")
    parser.add_argument("--rcsdnode", default=None, help="Explicit rcsdnode_out.gpkg path.")
    parser.add_argument("--t07-surface", default=None, help="Optional T07 RCSD intersection anchor surface path.")
    parser.add_argument("--t03-surface", default=None, help="Optional T03 virtual intersection polygon path.")
    parser.add_argument("--t04-surface", default=None, help="Optional T04 divmerge virtual anchor surface path.")
    parser.add_argument("--t04-audit", default=None, help="Optional T04 divmerge virtual anchor surface audit path.")
    parser.add_argument("--t05-surface", default=None, help="Optional T05 junction anchor surface path.")
    parser.add_argument("--surface-topology-closure", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--out-root", default=None, help="Output root. Defaults to parent of --t06-run-root.")
    parser.add_argument("--run-id", default=None, help="Run ID. Defaults to basename of --t06-run-root.")
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def _resolve_file(explicit_path: str | None, root: Path, filename: str) -> Path:
    if explicit_path:
        return _require_file(explicit_path)
    direct = root / filename
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(filename)) if root.is_dir() else []
    if matches:
        return matches[0]
    raise FileNotFoundError(f"missing {filename} under {root}")


def _resolve_optional_file(explicit_path: str | None, root: Path, filename: str) -> Path | None:
    if explicit_path:
        return _require_file(explicit_path)
    direct = root / filename
    if direct.is_file():
        return direct
    return None


def _require_file(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_file():
        return resolved
    raise FileNotFoundError(f"input file does not exist: {resolved}")


def _optional_file_arg(path: str | None) -> Path | None:
    if not path:
        return None
    return _require_file(path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
