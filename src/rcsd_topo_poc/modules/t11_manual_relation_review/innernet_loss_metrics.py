from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


POSITIVE_MANUAL_TYPES = {
    "1v1_rcsd_junction",
    "1vN_rcsd_junction",
    "1v1_rcsd_road",
    "1vN_rcsd_road",
}

DEFAULT_RUN_ROOT = (
    "/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/"
    "t11_manual_rerun_innernet_partial/run_20260703T232329Z"
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_root = args.run_root.expanduser().resolve()
    if not run_root.exists():
        print(f"[BLOCK] run root not found: {run_root}", file=sys.stderr)
        return 2

    out_dir = args.out_dir or (run_root / "_loss_metric_extract")
    out_dir.mkdir(parents=True, exist_ok=True)

    index = _build_file_index(run_root)
    manual_rows = _load_manual_rows(index)
    target_context = _load_target_context(index)
    t05_relations = _load_t05_relations(index)
    graph_audit = _load_graph_audit(index)

    relation_rows = _build_relation_priority(
        manual_rows=manual_rows,
        target_context=target_context,
        t05_relations=t05_relations,
        graph_audit=graph_audit,
    )
    root5_road_rows, root5_segment_rows = _build_root5_priorities(index)
    pack_rows = _build_pack_requests(
        relation_rows=relation_rows,
        root5_segment_rows=root5_segment_rows,
        top_n=args.pack_top_n,
        t10_run_root=args.t10_run_root,
    )

    outputs = {
        "relation_gain_priority_csv": _write_csv_capped(
            out_dir / "relation_gain_priority.csv",
            relation_rows,
            max_rows=args.top_n,
            max_bytes=args.max_output_bytes,
        ),
        "root5_strategy_priority_csv": _write_csv_capped(
            out_dir / "root5_strategy_priority.csv",
            root5_road_rows,
            max_rows=args.top_n,
            max_bytes=args.max_output_bytes,
        ),
        "root5_strategy_by_segment_csv": _write_csv_capped(
            out_dir / "root5_strategy_by_segment.csv",
            root5_segment_rows,
            max_rows=args.top_n,
            max_bytes=args.max_output_bytes,
        ),
        "case_pack_request_csv": _write_csv_capped(
            out_dir / "case_pack_request.csv",
            pack_rows,
            max_rows=args.pack_top_n,
            max_bytes=args.max_output_bytes,
        ),
    }

    snapshot = _build_snapshot(
        run_root=run_root,
        out_dir=out_dir,
        index=index,
        manual_rows=manual_rows,
        relation_rows=relation_rows,
        root5_road_rows=root5_road_rows,
        root5_segment_rows=root5_segment_rows,
        pack_rows=pack_rows,
        outputs=outputs,
    )
    snapshot_path = out_dir / "metrics_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    if snapshot_path.stat().st_size > args.max_output_bytes:
        compact = {
            "run_root": snapshot["run_root"],
            "out_dir": snapshot["out_dir"],
            "produced_at_utc": snapshot["produced_at_utc"],
            "totals": snapshot["totals"],
            "outputs": snapshot["outputs"],
            "note": "compact snapshot because full snapshot exceeded max_output_bytes",
        }
        snapshot_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "success": True,
                "out_dir": str(out_dir),
                "metrics_snapshot_json": str(snapshot_path),
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract benefit-ranked T11 manual relation and root5 "
            "replaceable-scope-unreplaced metrics from an innernet run root."
        )
    )
    parser.add_argument("--run-root", type=Path, default=Path(DEFAULT_RUN_ROOT))
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--top-n", type=int, default=500)
    parser.add_argument("--pack-top-n", type=int, default=80)
    parser.add_argument("--max-output-bytes", type=int, default=240_000)
    parser.add_argument(
        "--t10-run-root",
        default="",
        help="Optional T10 run root used only to print Segment pack command hints.",
    )
    return parser.parse_args(argv)


def _build_file_index(run_root: Path) -> dict[str, list[Path]]:
    names = {
        "t11_manual_relation_merged.csv",
        "t11_manual_relation_merged.summary.json",
        "intersection_match_all.geojson",
        "relation_graph_consumability_audit.csv",
        "t06_step3_unreplaced_rcsd_attribution.csv",
        "t06_segment_replacement_plan.csv",
        "t06_step3_swsd_frcsd_segment_relation.csv",
        "t06_segment_replacement_problem_registry.csv",
        "t06_rcsd_segment_replaceable.csv",
        "manual_rerun_metric_compare.json",
        "t11_manual_rerun_summary.json",
    }
    index: dict[str, list[Path]] = {name: [] for name in names}
    index["_all_t11_csv"] = []
    index["_compare_json"] = []
    for path in run_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in names:
            index[path.name].append(path)
        if path.suffix.lower() == ".csv" and path.name.startswith("t11_"):
            index["_all_t11_csv"].append(path)
        if path.suffix.lower() == ".json" and "metric_compare" in path.name:
            index["_compare_json"].append(path)
    return index


def _load_manual_rows(index: dict[str, list[Path]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in index.get("t11_manual_relation_merged.csv", []):
        for raw in _read_csv(path):
            relation_type = _text(raw.get("manual_relation_type"))
            selected = _text(raw.get("selected_ids"))
            if relation_type not in POSITIVE_MANUAL_TYPES:
                continue
            if selected == "" or selected.upper() == "NULL":
                continue
            row = _normalize_row(raw)
            row["_source_path"] = str(path)
            rows.append(row)
    return rows


def _load_target_context(index: dict[str, list[Path]]) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    carry_fields = {
        "candidate_category",
        "candidate_reason",
        "root_cause_categories",
        "t06_reject_reasons",
        "affected_segment_ids",
        "highest_priority_segment_id",
        "swsd_segment_id",
    }
    for path in index.get("_all_t11_csv", []):
        for row in _read_csv(path):
            target = _text(row.get("target_id"))
            if not target:
                continue
            current = context.setdefault(target, {"target_id": target, "segments": set(), "length_m": 0.0})
            for key in carry_fields:
                value = _text(row.get(key))
                if value and key not in current:
                    current[key] = value
            for key in ("swsd_segment_id", "highest_priority_segment_id"):
                value = _text(row.get(key))
                if value:
                    current["segments"].add(value)
            for value in _split_ids(row.get("affected_segment_ids")):
                current["segments"].add(value)
            length = max(
                _to_float(row.get("affected_segment_total_length_m")),
                _to_float(row.get("highest_priority_segment_length_m")),
                _to_float(row.get("segment_length_m")),
            )
            if length > float(current.get("length_m", 0.0)):
                current["length_m"] = length
    for item in context.values():
        segments = sorted(str(v) for v in item.get("segments", set()) if str(v))
        item["segments"] = "|".join(segments)
    return context


def _load_t05_relations(index: dict[str, list[Path]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in index.get("intersection_match_all.geojson", []):
        payload = _read_json(path)
        features = payload.get("features", []) if isinstance(payload, dict) else []
        for feature in features:
            props = _normalize_row((feature or {}).get("properties") or {})
            target = _text(props.get("target_id") or props.get("id"))
            if not target:
                continue
            props["_source_path"] = str(path)
            result[target] = props
    return result


def _load_graph_audit(index: dict[str, list[Path]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in index.get("relation_graph_consumability_audit.csv", []):
        for raw in _read_csv(path):
            target = _text(raw.get("target_id") or raw.get("swsd_node_id"))
            if not target:
                continue
            row = _normalize_row(raw)
            row["_source_path"] = str(path)
            result[target] = row
    return result


def _build_relation_priority(
    *,
    manual_rows: list[dict[str, str]],
    target_context: dict[str, dict[str, Any]],
    t05_relations: dict[str, dict[str, Any]],
    graph_audit: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manual in manual_rows:
        target = _text(manual.get("target_id"))
        context = target_context.get(target, {})
        t05 = t05_relations.get(target, {})
        graph = graph_audit.get(target, {})
        status = _text(t05.get("status") or t05.get("relation_status"))
        base_id = _text(t05.get("base_id"))
        graph_consumable = _text(
            graph.get("graph_consumable")
            or t05.get("graph_consumable")
            or graph.get("relation_graph_consumable")
        )
        source_modules = _text(
            t05.get("source_modules")
            or t05.get("source_module")
            or graph.get("source_modules")
            or graph.get("source_module")
        )
        gap_class = _classify_relation_gap(status, base_id, graph_consumable, source_modules)
        length_m = max(
            _to_float(context.get("length_m")),
            _to_float(manual.get("affected_segment_total_length_m")),
            _to_float(manual.get("segment_length_m")),
        )
        problem_weight = 0 if gap_class == "already_machine_consumable" else 1
        benefit_m = length_m if length_m > 0 else float(problem_weight)
        segments = _text(manual.get("swsd_segment_id")) or _text(context.get("segments"))
        rows.append(
            {
                "sort_benefit_m": round(benefit_m, 3),
                "problem_weight": problem_weight,
                "relation_gap_class": gap_class,
                "case_id": _text(manual.get("case_id")),
                "target_id": target,
                "swsd_segment_ids": segments,
                "manual_relation_type": _text(manual.get("manual_relation_type")),
                "selected_ids": _text(manual.get("selected_ids")),
                "t05_status": status,
                "t05_base_id": base_id,
                "t05_graph_consumable": graph_consumable,
                "t05_source_modules": source_modules,
                "graph_consumability_status": _text(graph.get("graph_consumability_status")),
                "candidate_category": _text(context.get("candidate_category")),
                "candidate_reason": _text(context.get("candidate_reason")),
                "root_cause_categories": _text(context.get("root_cause_categories")),
                "t06_reject_reasons": _text(context.get("t06_reject_reasons")),
                "source_path": _text(manual.get("_source_path")),
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row["problem_weight"]),
            -float(row["sort_benefit_m"]),
            _text(row["case_id"]),
            _text(row["target_id"]),
        )
    )
    return rows


def _classify_relation_gap(status: str, base_id: str, graph_consumable: str, source_modules: str) -> str:
    status_ok = status in {"0", "success", "passed", "true", "True"}
    base_ok = base_id not in {"", "0", "-1", "None", "NULL"}
    graph_ok = graph_consumable in {"1", "true", "True", "yes", "YES"}
    manual_consumed = "T11_MANUAL" in source_modules
    if status_ok and base_ok and graph_ok and not manual_consumed:
        return "already_machine_consumable"
    if status_ok and base_ok and graph_ok and manual_consumed:
        return "manual_consumed_graph_consumable"
    if status_ok and base_ok and not graph_ok:
        return "relation_success_but_graph_unconsumable"
    if not status_ok:
        return "manual_can_fix_machine_relation_failure"
    return "manual_relation_needs_review"


def _build_root5_priorities(index: dict[str, list[Path]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plan_by_segment = _load_by_segment(index.get("t06_segment_replacement_plan.csv", []))
    step3_by_segment = _load_by_segment(index.get("t06_step3_swsd_frcsd_segment_relation.csv", []))
    registry_by_segment = _load_by_segment(index.get("t06_segment_replacement_problem_registry.csv", []))
    replaceable_by_segment = _load_by_segment(index.get("t06_rcsd_segment_replaceable.csv", []))

    road_rows: list[dict[str, Any]] = []
    segment_acc: dict[str, dict[str, Any]] = {}
    for path in index.get("t06_step3_unreplaced_rcsd_attribution.csv", []):
        for raw in _read_csv(path):
            row = _normalize_row(raw)
            final_class = _text(row.get("final_attribution_class") or row.get("attribution_class"))
            if final_class != "5_replaceable_scope_unreplaced":
                continue
            segment_id = _first_nonempty(
                row.get("final_primary_segment_id"),
                _first_id(row.get("matched_replaceable_segment_ids")),
                _first_id(row.get("matched_relation_segment_ids")),
                _first_id(row.get("matched_segment_ids")),
            )
            plan = plan_by_segment.get(segment_id, {})
            step3 = step3_by_segment.get(segment_id, {})
            registry = registry_by_segment.get(segment_id, {})
            replaceable = replaceable_by_segment.get(segment_id, {})
            length_m = _to_float(row.get("length_m"))
            plan_statuses = _first_nonempty(row.get("final_plan_statuses"), row.get("plan_statuses"), plan.get("plan_status"))
            step3_statuses = _first_nonempty(
                row.get("final_step3_relation_statuses"),
                row.get("step3_relation_statuses"),
                step3.get("relation_status"),
            )
            strategy_class = _classify_root5_strategy(
                plan_statuses=plan_statuses,
                step3_statuses=step3_statuses,
                plan=plan,
                step3=step3,
                replaceable=replaceable,
            )
            out = {
                "sort_benefit_m": round(length_m, 3),
                "strategy_error_class": strategy_class,
                "case_id": _infer_case_id(path),
                "swsd_segment_id": segment_id,
                "rcsd_road_id": _text(row.get("rcsd_road_id") or row.get("id")),
                "length_m": round(length_m, 3),
                "final_attribution_subclass": _text(row.get("final_attribution_subclass")),
                "final_attribution_owner": _text(row.get("final_attribution_owner")),
                "final_attribution_reason": _text(row.get("final_attribution_reason")),
                "plan_statuses": _text(plan_statuses),
                "step3_relation_statuses": _text(step3_statuses),
                "plan_execution_scope": _text(plan.get("execution_scope")),
                "plan_replacement_strategy": _text(plan.get("replacement_strategy")),
                "plan_source_reason": _text(plan.get("source_reason")),
                "step3_relation_reason": _text(step3.get("relation_reason")),
                "step3_source_mix": _text(step3.get("source_mix")),
                "problem_status": _text(registry.get("problem_status")),
                "reject_reason": _text(registry.get("reject_reason")),
                "root_cause_category": _text(registry.get("root_cause_category")),
                "problem_failure_business_category": _text(registry.get("failure_business_category")),
                "matched_segment_ids": _text(row.get("matched_segment_ids")),
                "source_path": str(path),
            }
            road_rows.append(out)
            acc = segment_acc.setdefault(
                segment_id,
                {
                    "sort_benefit_m": 0.0,
                    "case_id": out["case_id"],
                    "swsd_segment_id": segment_id,
                    "root5_road_count": 0,
                    "rcsd_road_ids": [],
                    "strategy_error_classes": set(),
                    "plan_statuses": set(),
                    "step3_relation_statuses": set(),
                    "plan_execution_scopes": set(),
                    "top_reasons": set(),
                },
            )
            acc["sort_benefit_m"] += length_m
            acc["root5_road_count"] += 1
            _append_limited(acc["rcsd_road_ids"], out["rcsd_road_id"], 20)
            acc["strategy_error_classes"].add(strategy_class)
            _add_if(acc["plan_statuses"], out["plan_statuses"])
            _add_if(acc["step3_relation_statuses"], out["step3_relation_statuses"])
            _add_if(acc["plan_execution_scopes"], out["plan_execution_scope"])
            _add_if(acc["top_reasons"], out["final_attribution_subclass"] or out["reject_reason"])

    road_rows.sort(key=lambda row: (-float(row["sort_benefit_m"]), _text(row["case_id"]), _text(row["swsd_segment_id"])))
    segment_rows = [
        {
            "sort_benefit_m": round(float(acc["sort_benefit_m"]), 3),
            "case_id": acc["case_id"],
            "swsd_segment_id": acc["swsd_segment_id"],
            "root5_road_count": acc["root5_road_count"],
            "strategy_error_classes": _join_sorted(acc["strategy_error_classes"]),
            "plan_statuses": _join_sorted(acc["plan_statuses"]),
            "step3_relation_statuses": _join_sorted(acc["step3_relation_statuses"]),
            "plan_execution_scopes": _join_sorted(acc["plan_execution_scopes"]),
            "top_reasons": _join_sorted(acc["top_reasons"]),
            "sample_rcsd_road_ids": "|".join(acc["rcsd_road_ids"]),
        }
        for acc in segment_acc.values()
    ]
    segment_rows.sort(key=lambda row: (-float(row["sort_benefit_m"]), _text(row["case_id"]), _text(row["swsd_segment_id"])))
    return road_rows, segment_rows


def _classify_root5_strategy(
    *,
    plan_statuses: str,
    step3_statuses: str,
    plan: dict[str, str],
    step3: dict[str, str],
    replaceable: dict[str, str],
) -> str:
    plan_text = _text(plan_statuses)
    step3_text = _text(step3_statuses)
    ready = "ready" in plan_text
    replaced = "replaced" in step3_text and "retained_swsd" not in step3_text
    retained = "retained_swsd" in step3_text
    if ready and retained:
        return "ready_plan_step3_retained_swsd"
    if ready and replaced:
        return "ready_plan_replaced_but_road_unreferenced"
    if ready and not step3_text:
        return "ready_plan_missing_step3_relation"
    if _text(replaceable.get("swsd_segment_id")) and not ready:
        return "replaceable_without_ready_plan"
    if _text(plan.get("execution_scope")) == "path_corridor_group":
        return "group_plan_road_scope_review"
    return "root5_strategy_review"


def _load_by_segment(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path in paths:
        for raw in _read_csv(path):
            row = _normalize_row(raw)
            segment_ids = _split_ids(row.get("swsd_segment_id") or row.get("segment_id") or row.get("id") or row.get("group_segment_ids"))
            if not segment_ids:
                segment_ids = _split_ids(row.get("source_segment_ids") or row.get("swsd_segment_ids"))
            for segment_id in segment_ids:
                result.setdefault(segment_id, row)
    return result


def _build_pack_requests(
    *,
    relation_rows: list[dict[str, Any]],
    root5_segment_rows: list[dict[str, Any]],
    top_n: int,
    t10_run_root: str,
) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = {}
    for row in root5_segment_rows:
        segment = _text(row.get("swsd_segment_id"))
        if not segment:
            continue
        item = acc.setdefault(f"segment:{segment}", _base_pack_row("segment", row.get("case_id"), segment, t10_run_root))
        item["sort_benefit_m"] = max(float(item["sort_benefit_m"]), _to_float(row.get("sort_benefit_m")))
        item["root5_length_m"] = round(_to_float(row.get("sort_benefit_m")), 3)
        item["root5_road_count"] = row.get("root5_road_count", "")
        item["reason"] = _append_reason(item["reason"], "root5_strategy")
        item["strategy_error_classes"] = row.get("strategy_error_classes", "")

    for row in relation_rows:
        if _text(row.get("relation_gap_class")) == "already_machine_consumable":
            continue
        segments = _split_ids(row.get("swsd_segment_ids"))
        if segments:
            item = acc.setdefault(
                f"segment:{segments[0]}",
                _base_pack_row("segment", row.get("case_id"), segments[0], t10_run_root),
            )
        else:
            case_id = _text(row.get("case_id")) or "UNKNOWN"
            item = acc.setdefault(f"case:{case_id}", _base_pack_row("case", case_id, "", t10_run_root))
        benefit = _to_float(row.get("sort_benefit_m"))
        item["sort_benefit_m"] = max(float(item["sort_benefit_m"]), benefit)
        item["relation_target_count"] = int(item["relation_target_count"]) + 1
        item["relation_benefit_m"] = round(float(item["relation_benefit_m"]) + benefit, 3)
        _append_limited(item["_target_ids"], _text(row.get("target_id")), 20)
        item["reason"] = _append_reason(item["reason"], _text(row.get("relation_gap_class")))

    rows = []
    for item in acc.values():
        item["target_ids"] = "|".join(item.pop("_target_ids", []))
        if item["pack_type"] == "segment" and item["swsd_segment_id"]:
            item["pack_command_hint"] = _pack_segment_hint(t10_run_root, item["swsd_segment_id"])
        rows.append(item)
    rows.sort(key=lambda row: (-float(row["sort_benefit_m"]), _text(row["pack_type"]), _text(row["case_id"]), _text(row["swsd_segment_id"])))
    return rows[:top_n]


def _base_pack_row(pack_type: str, case_id: Any, segment_id: Any, t10_run_root: str) -> dict[str, Any]:
    return {
        "sort_benefit_m": 0.0,
        "pack_type": pack_type,
        "case_id": _text(case_id),
        "swsd_segment_id": _text(segment_id),
        "reason": "",
        "root5_length_m": 0.0,
        "root5_road_count": "",
        "relation_benefit_m": 0.0,
        "relation_target_count": 0,
        "target_ids": "",
        "_target_ids": [],
        "strategy_error_classes": "",
        "pack_command_hint": _pack_segment_hint(t10_run_root, _text(segment_id)) if segment_id else "",
    }


def _pack_segment_hint(t10_run_root: str, segment_id: str) -> str:
    if not segment_id:
        return ""
    prefix = f"T10_RUN_ROOT={t10_run_root} " if t10_run_root else "T10_RUN_ROOT=<T10_RUN_ROOT> "
    return prefix + f"bash scripts/t10_pack_innernet_segments.sh {segment_id}"


def _build_snapshot(
    *,
    run_root: Path,
    out_dir: Path,
    index: dict[str, list[Path]],
    manual_rows: list[dict[str, str]],
    relation_rows: list[dict[str, Any]],
    root5_road_rows: list[dict[str, Any]],
    root5_segment_rows: list[dict[str, Any]],
    pack_rows: list[dict[str, Any]],
    outputs: dict[str, Any],
) -> dict[str, Any]:
    metric_compares = []
    for path in index.get("_compare_json", [])[:20]:
        payload = _read_json(path)
        if isinstance(payload, dict):
            metric_compares.append(
                {
                    "path": str(path),
                    "delta": payload.get("delta", {}),
                    "before": _slim_metric(payload.get("before", {})),
                    "after": _slim_metric(payload.get("after", {})),
                }
            )
    return {
        "run_root": str(run_root),
        "out_dir": str(out_dir),
        "produced_at_utc": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "manual_positive_rows": len(manual_rows),
            "relation_priority_rows": len(relation_rows),
            "root5_road_rows": len(root5_road_rows),
            "root5_segment_rows": len(root5_segment_rows),
            "pack_request_rows": len(pack_rows),
            "root5_total_length_m": round(sum(_to_float(row.get("length_m")) for row in root5_road_rows), 3),
        },
        "relation_gap_class_counts": _count_by(relation_rows, "relation_gap_class"),
        "root5_strategy_class_counts": _count_by(root5_road_rows, "strategy_error_class"),
        "metric_compares": metric_compares,
        "input_files": {key: [str(path) for path in paths[:20]] for key, paths in index.items() if paths},
        "outputs": outputs,
    }


def _slim_metric(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = [
        "step1_final_fusion_unit_count",
        "manual_anchor_override_segment_count",
        "manual_evd_override_segment_count",
        "step2_replaceable_count",
        "replacement_plan_ready_count",
        "step3_replacement_success_count",
        "unreplaced_rcsd_road_count",
        "unreplaced_rcsd_road_length_m",
        "rcsd_replaced_length_rate_percent",
    ]
    return {key: value.get(key) for key in keys if key in value}


def _write_csv_capped(path: Path, rows: list[dict[str, Any]], *, max_rows: int, max_bytes: int) -> dict[str, Any]:
    selected = rows[: max(0, max_rows)]
    fields = [field for field in selected[0].keys() if not field.startswith("_")] if selected else ["empty"]
    while True:
        _write_csv(path, selected, fields)
        size = path.stat().st_size
        if size <= max_bytes or len(selected) <= 1:
            return {
                "path": str(path),
                "row_count_written": len(selected),
                "row_count_available": len(rows),
                "size_bytes": size,
                "truncated": len(selected) < len(rows),
            }
        ratio = max_bytes / max(size, 1)
        next_count = max(1, int(len(selected) * ratio * 0.9))
        selected = selected[: next_count if next_count < len(selected) else len(selected) - 1]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _read_csv(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(sys.maxsize)
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception as exc:
        print(f"[WARN] failed to read csv {path}: {exc}", file=sys.stderr)
        return []


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(f"[WARN] failed to read json {path}: {exc}", file=sys.stderr)
        return {}


def _normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {str(key): _text(value) for key, value in row.items()}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _csv_value(value: Any) -> str:
    if isinstance(value, float):
        return str(round(value, 6))
    return _text(value)


def _to_float(value: Any) -> float:
    try:
        raw = _text(value)
        return float(raw) if raw else 0.0
    except Exception:
        return 0.0


def _split_ids(value: Any) -> list[str]:
    raw = _text(value)
    if not raw:
        return []
    cleaned = raw
    for char in "[]'\"":
        cleaned = cleaned.replace(char, "")
    for sep in [",", ";"]:
        cleaned = cleaned.replace(sep, "|")
    return [part.strip() for part in cleaned.split("|") if part.strip()]


def _first_id(value: Any) -> str:
    values = _split_ids(value)
    return values[0] if values else ""


def _first_nonempty(*values: Any) -> str:
    for value in values:
        item = _text(value)
        if item:
            return item
    return ""


def _infer_case_id(path: Path) -> str:
    parts = list(path.parts)
    for index, part in enumerate(parts[:-1]):
        if part == "cases" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _append_limited(target: list[str], value: str, limit: int) -> None:
    if value and value not in target and len(target) < limit:
        target.append(value)


def _add_if(target: set[str], value: str) -> None:
    if value:
        target.add(value)


def _join_sorted(values: Iterable[str]) -> str:
    return "|".join(sorted(value for value in values if value))


def _append_reason(existing: str, value: str) -> str:
    if not value:
        return existing
    values = _split_ids(existing)
    if value not in values:
        values.append(value)
    return "|".join(values)


def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[_text(row.get(field)) or "__blank__"] += 1
    return dict(sorted(result.items(), key=lambda item: (-item[1], item[0])))


if __name__ == "__main__":
    raise SystemExit(main())
