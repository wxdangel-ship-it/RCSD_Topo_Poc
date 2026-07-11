from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


def run_output_jobs(
    jobs: Iterable[Callable[[], Any]],
    *,
    max_workers: int = 4,
) -> None:
    ordered_jobs = tuple(jobs)
    if not ordered_jobs:
        return
    effective_workers = min(max(1, int(max_workers)), len(ordered_jobs))
    if effective_workers == 1:
        for job in ordered_jobs:
            job()
        return
    with ThreadPoolExecutor(
        max_workers=effective_workers,
        thread_name_prefix="t03-output",
    ) as executor:
        futures = [executor.submit(job) for job in ordered_jobs]
        for future in futures:
            future.result()


__all__ = ["run_output_jobs"]
