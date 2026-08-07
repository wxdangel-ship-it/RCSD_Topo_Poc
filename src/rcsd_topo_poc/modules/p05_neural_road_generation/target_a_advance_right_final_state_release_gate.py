from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_training import (
    advance_right_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


def compose_final_state_advance_right_release_gate(
    *,
    primary_prediction_root: Path,
    confirmation_prediction_root: Path,
    output_root: Path,
) -> Path:
    """Require two independent strict-OOF decoders to accept one exact plan."""
    primary_root = normalize_runtime_path(
        primary_prediction_root
    ).resolve(strict=True)
    confirmation_root = normalize_runtime_path(
        confirmation_prediction_root
    ).resolve(strict=True)
    root = normalize_runtime_path(output_root).resolve()
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)

    primary_path = primary_root / "oof_predictions.jsonl"
    confirmation_path = confirmation_root / "oof_predictions.jsonl"
    primary = _unique_predictions(_jsonl_rows(primary_path))
    confirmation = _unique_predictions(_jsonl_rows(confirmation_path))
    rows = compose_final_state_release_rows(
        primary,
        confirmation,
    )
    prediction_path = root / "oof_predictions.jsonl"
    _write_jsonl(prediction_path, rows)
    metrics = advance_right_metrics(rows)
    summary = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ADVANCE_RIGHT_FINAL_STATE_TWO_SEED_RELEASE_GATE",
        "release_contract": (
            "Both independent strict-OOF seeds must automatically accept the "
            "same plan type, complete RCSD candidate set and complete fixed "
            "SWSD Road set. Scores are not averaged and truth is not used by "
            "the release decision."
        ),
        "prediction_count": len(rows),
        "primary_automatic_count": sum(
            bool(row["primary_automatic_decision"]) for row in rows
        ),
        "confirmation_automatic_count": sum(
            bool(row["confirmation_automatic_decision"]) for row in rows
        ),
        "ensemble_automatic_count": sum(
            bool(row["automatic_decision"]) for row in rows
        ),
        "plan_disagreement_count": sum(
            not bool(row["ensemble_plan_consistent"]) for row in rows
        ),
        "fold_mismatch_count": sum(
            not bool(row["ensemble_fold_consistent"]) for row in rows
        ),
        "metrics": metrics,
        "feature_uses_truth": False,
        "release_uses_truth": False,
        "terminal_input_count": 0,
        "raw_id_embedding_count": 0,
        "inputs": {
            "primary_predictions": _input_record(primary_path),
            "confirmation_predictions": _input_record(confirmation_path),
        },
        "predictions": _input_record(prediction_path),
        "release_gate": (
            "PASS"
            if metrics["automatic_count"] > 0
            and metrics["unsafe_automatic_count"] == 0
            else "NO_GO"
        ),
        "gate_pass": bool(
            len(rows) == 474
            and metrics["automatic_count"] > 0
            and metrics["unsafe_automatic_count"] == 0
            and all(row["ensemble_fold_consistent"] for row in rows)
        ),
    }
    _write_json(root / "summary.json", summary)
    if not summary["gate_pass"]:
        raise RuntimeError("AdvanceRight final-state release gate failed")
    return root


def compose_final_state_release_rows(
    primary: Mapping[tuple[str, str], Mapping[str, Any]],
    confirmation: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if set(primary) != set(confirmation):
        raise ValueError("AdvanceRight release seed scopes differ")
    rows = []
    for key in sorted(primary):
        first = primary[key]
        second = confirmation[key]
        fold_consistent = int(first["fold"]) == int(second["fold"])
        plan_consistent = bool(
            str(first["predicted_plan_type"])
            == str(second["predicted_plan_type"])
            and _ids(first, "raw_selected_candidate_road_ids")
            == _ids(second, "raw_selected_candidate_road_ids")
            and _ids(first, "raw_selected_fixed_swsd_road_ids")
            == _ids(second, "raw_selected_fixed_swsd_road_ids")
        )
        accepted = bool(
            fold_consistent
            and plan_consistent
            and first.get("automatic_decision")
            and second.get("automatic_decision")
        )
        row = dict(first)
        row.update(
            {
                "primary_automatic_decision": bool(
                    first.get("automatic_decision")
                ),
                "confirmation_automatic_decision": bool(
                    second.get("automatic_decision")
                ),
                "ensemble_fold_consistent": fold_consistent,
                "ensemble_plan_consistent": plan_consistent,
                "automatic_decision": accepted,
                "effective_decision": (
                    str(first["predicted_plan_type"])
                    if accepted
                    else "ABSTAIN"
                ),
                "positive_keep_swsd": bool(
                    accepted
                    and str(first["predicted_plan_type"]) == "SWSD_ONLY"
                ),
                "unsafe_automatic": bool(
                    accepted
                    and (
                        not first.get("safety_target")
                        or not first.get("raw_plan_exact")
                    )
                ),
                "release_gate_kind": "TWO_SEED_EXACT_PLAN_INTERSECTION",
            }
        )
        rows.append(row)
    return rows


def _ids(row: Mapping[str, Any], field: str) -> tuple[str, ...]:
    return tuple(sorted(str(value) for value in row.get(field) or ()))


def _unique_predictions(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for row in rows:
        key = (str(row["case_key"]), str(row["object_id"]))
        if key in result:
            raise ValueError("AdvanceRight predictions contain duplicates")
        result[key] = row
    return result


def _input_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True)
                + "\n"
            )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "compose_final_state_advance_right_release_gate",
    "compose_final_state_release_rows",
]
