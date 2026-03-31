#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import fiona


DEFAULT_STAGE1_ROOT = Path('outputs/_work/t02_stage1_drivezone_gate')
DEFAULT_STAGE2_ROOT = Path('outputs/_work/t02_stage2_anchor_recognition')


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _resolve_latest_run(root: Path, summary_name: str) -> Path | None:
    if not root.is_dir():
        return None
    candidates = [path for path in root.iterdir() if path.is_dir() and (path / summary_name).is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value


def _load_representative_rows(nodes_path: Path, include_anchor: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not nodes_path.is_file():
        return rows
    with fiona.open(nodes_path) as src:
        for feature in src:
            properties = dict(feature['properties'])
            if properties.get('has_evd') is None:
                continue
            row = {
                'id': _normalize_scalar(properties.get('id')),
                'mainnodeid': _normalize_scalar(properties.get('mainnodeid')),
                'has_evd': _normalize_scalar(properties.get('has_evd')),
                'kind_2': _normalize_scalar(properties.get('kind_2')),
                'grade_2': _normalize_scalar(properties.get('grade_2')),
            }
            if include_anchor:
                row['is_anchor'] = _normalize_scalar(properties.get('is_anchor'))
                row['anchor_reason'] = _normalize_scalar(properties.get('anchor_reason'))
            rows.append(row)
    rows.sort(key=lambda item: (str(item.get('mainnodeid')), str(item.get('id'))))
    return rows


def _counter_dict(values: list[Any]) -> dict[str, int]:
    counter = Counter('null' if value is None else str(value) for value in values)
    return dict(sorted(counter.items()))


def _stage1_payload(run_dir: Path, representative_limit: int) -> dict[str, Any]:
    summary = _load_json(run_dir / 't02_stage1_summary.json')
    representatives = _load_representative_rows(run_dir / 'nodes.gpkg', include_anchor=False)
    return {
        'run_dir': str(run_dir),
        'run_id': summary.get('run_id'),
        'success': summary.get('success'),
        'counts': summary.get('counts', {}),
        'all_d_sgrade': summary.get('summary_by_s_grade', {}).get('all__d_sgrade', {}),
        'summary_by_kind_grade': summary.get('summary_by_kind_grade', {}),
        'representative_count': len(representatives),
        'representative_has_evd_counts': _counter_dict([row.get('has_evd') for row in representatives]),
        'representatives': representatives[:representative_limit],
    }


def _stage2_payload(run_dir: Path, representative_limit: int) -> dict[str, Any]:
    summary = _load_json(run_dir / 't02_stage2_summary.json')
    audit = _load_json(run_dir / 't02_stage2_audit.json')
    error1_audit = _load_json(run_dir / 'node_error_1_audit.json')
    error2_audit = _load_json(run_dir / 'node_error_2_audit.json')
    representatives = _load_representative_rows(run_dir / 'nodes.gpkg', include_anchor=True)
    return {
        'run_dir': str(run_dir),
        'run_id': summary.get('run_id'),
        'success': summary.get('success'),
        'counts': summary.get('counts', {}),
        'anchor_summary_by_s_grade': summary.get('anchor_summary_by_s_grade', {}),
        'anchor_summary_by_kind_grade': summary.get('anchor_summary_by_kind_grade', {}),
        'audit_count': audit.get('audit_count'),
        'node_error_1_count': error1_audit.get('error_count'),
        'node_error_2_count': error2_audit.get('error_count'),
        'representative_count': len(representatives),
        'representative_has_evd_counts': _counter_dict([row.get('has_evd') for row in representatives]),
        'representative_is_anchor_counts': _counter_dict([row.get('is_anchor') for row in representatives]),
        'representative_anchor_reason_counts': _counter_dict([row.get('anchor_reason') for row in representatives]),
        'representatives': representatives[:representative_limit],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Extract high-signal T02 stage1/stage2 run information.')
    parser.add_argument('--stage1-run-dir', type=Path, help='Explicit T02 stage1 run directory.')
    parser.add_argument('--stage2-run-dir', type=Path, help='Explicit T02 stage2 run directory.')
    parser.add_argument('--stage1-root', type=Path, default=DEFAULT_STAGE1_ROOT, help='Stage1 output root used to auto-discover the latest run.')
    parser.add_argument('--stage2-root', type=Path, default=DEFAULT_STAGE2_ROOT, help='Stage2 output root used to auto-discover the latest run.')
    parser.add_argument('--representative-limit', type=int, default=20, help='Maximum representative rows to emit per stage.')
    parser.add_argument('--json-out', type=Path, help='Optional JSON output path.')
    args = parser.parse_args()

    stage1_run_dir = args.stage1_run_dir or _resolve_latest_run(args.stage1_root, 't02_stage1_summary.json')
    stage2_run_dir = args.stage2_run_dir or _resolve_latest_run(args.stage2_root, 't02_stage2_summary.json')
    if stage1_run_dir is None and stage2_run_dir is None:
        raise SystemExit('No stage1/stage2 run directory found. Provide --stage1-run-dir/--stage2-run-dir or ensure default output roots exist.')

    payload: dict[str, Any] = {}
    if stage1_run_dir is not None:
        payload['stage1'] = _stage1_payload(stage1_run_dir, args.representative_limit)
    if stage2_run_dir is not None:
        payload['stage2'] = _stage2_payload(stage2_run_dir, args.representative_limit)

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
