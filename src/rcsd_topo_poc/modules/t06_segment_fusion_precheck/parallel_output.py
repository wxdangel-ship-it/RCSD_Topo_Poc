from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import write_feature_triplet


@dataclass(frozen=True)
class FeatureTripletJob:
    stem: str
    features: list[dict[str, Any]]
    fieldnames: list[str]


def publish_feature_triplets(
    *,
    step_root: Path,
    jobs: dict[str, FeatureTripletJob],
    max_workers: int = 1,
) -> dict[str, dict[str, Path]]:
    if not jobs:
        return {}
    effective_workers = min(max(1, int(max_workers)), len(jobs))
    if effective_workers == 1:
        return {
            name: _publish_job(step_root, job)
            for name, job in jobs.items()
        }
    with ThreadPoolExecutor(
        max_workers=effective_workers,
        thread_name_prefix="t06-output",
    ) as executor:
        futures = {
            name: executor.submit(_publish_job, step_root, job)
            for name, job in jobs.items()
        }
        return {name: futures[name].result() for name in jobs}


def _publish_job(step_root: Path, job: FeatureTripletJob) -> dict[str, Path]:
    return write_feature_triplet(
        step_root=step_root,
        stem=job.stem,
        features=job.features,
        fieldnames=job.fieldnames,
    )


__all__ = ["FeatureTripletJob", "publish_feature_triplets"]
