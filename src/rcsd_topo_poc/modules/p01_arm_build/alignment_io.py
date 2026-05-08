from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset
from rcsd_topo_poc.modules.p01_arm_build.models import DATASETS, DatasetInput, LoadedDataset


@dataclass(frozen=True)
class DatasetA1Artifacts:
    context: dict[str, Any]
    initial_arms: list[dict[str, Any]]
    final_arms: list[dict[str, Any]]
    local_arm_candidates: list[dict[str, Any]]
    arm_traces: list[dict[str, Any]]
    through_decisions: list[dict[str, Any]]
    issue_report: dict[str, Any]


@dataclass(frozen=True)
class CaseA1Artifacts:
    group_id: str
    case_dir: Path
    case_input: dict[str, Any]
    case_summary: dict[str, Any]
    datasets: dict[str, DatasetA1Artifacts]


@dataclass(frozen=True)
class A1RunArtifacts:
    run_root: Path
    preflight: dict[str, Any]
    build_summary: dict[str, Any]
    review_index_rows: list[dict[str, str]]
    cases: tuple[CaseA1Artifacts, ...]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_a1_run_root(run_root: Path) -> A1RunArtifacts:
    required = [
        "preflight.json",
        "p01_arm_build_summary.json",
        "p01_arm_build_review_index.csv",
        "cases",
    ]
    missing = [name for name in required if not (run_root / name).exists()]
    if missing:
        raise FileNotFoundError(f"P01-A1 run root missing required entries: {', '.join(missing)}")

    cases: list[CaseA1Artifacts] = []
    for case_dir in sorted((run_root / "cases").iterdir()):
        if not case_dir.is_dir():
            continue
        datasets: dict[str, DatasetA1Artifacts] = {}
        for dataset in DATASETS:
            dataset_dir = case_dir / dataset
            datasets[dataset] = DatasetA1Artifacts(
                context=read_json(dataset_dir / "junction_context.json"),
                initial_arms=read_json(dataset_dir / "initial_arms.json"),
                final_arms=read_json(dataset_dir / "final_arms.json"),
                local_arm_candidates=read_json(dataset_dir / "local_arm_candidates.json"),
                arm_traces=read_json(dataset_dir / "arm_traces.json"),
                through_decisions=read_json(dataset_dir / "through_decisions.json"),
                issue_report=read_json(dataset_dir / "issue_report.json"),
            )
        cases.append(
            CaseA1Artifacts(
                group_id=case_dir.name,
                case_dir=case_dir,
                case_input=read_json(case_dir / "case_input.json"),
                case_summary=read_json(case_dir / "case_summary.json"),
                datasets=datasets,
            )
        )
    return A1RunArtifacts(
        run_root=run_root,
        preflight=read_json(run_root / "preflight.json"),
        build_summary=read_json(run_root / "p01_arm_build_summary.json"),
        review_index_rows=_read_csv_rows(run_root / "p01_arm_build_review_index.csv"),
        cases=tuple(cases),
    )


def dataset_inputs_from_preflight(preflight: dict[str, Any]) -> dict[str, DatasetInput]:
    input_paths = preflight.get("input_paths", {})
    dataset_inputs: dict[str, DatasetInput] = {}
    for dataset in DATASETS:
        paths = input_paths.get(dataset, {})
        nodes_path = Path(str(paths.get("nodes", "")))
        roads_path = Path(str(paths.get("roads", "")))
        dataset_inputs[dataset] = DatasetInput(dataset, nodes_path, roads_path)
    return dataset_inputs


def load_datasets_from_a1_preflight(preflight: dict[str, Any]) -> tuple[dict[str, LoadedDataset], dict[str, str]]:
    loaded: dict[str, LoadedDataset] = {}
    load_errors: dict[str, str] = {}
    for dataset, dataset_input in dataset_inputs_from_preflight(preflight).items():
        try:
            loaded[dataset] = load_dataset(dataset_input)
        except Exception as exc:  # noqa: BLE001 - persisted in preflight for auditability
            load_errors[dataset] = str(exc)
    return loaded, load_errors
