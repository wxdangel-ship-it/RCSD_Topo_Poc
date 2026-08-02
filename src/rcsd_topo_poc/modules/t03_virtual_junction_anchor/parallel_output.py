from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import Any


SHARED_OUTPUT_MAX_WORKERS = 16

_shared_executor: ThreadPoolExecutor | None = None
_shared_executor_lock = Lock()


def _get_shared_executor() -> ThreadPoolExecutor:
    global _shared_executor
    if _shared_executor is not None:
        return _shared_executor
    with _shared_executor_lock:
        if _shared_executor is None:
            _shared_executor = ThreadPoolExecutor(
                max_workers=SHARED_OUTPUT_MAX_WORKERS,
                thread_name_prefix="t03-output",
            )
    return _shared_executor


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
    limiter = BoundedSemaphore(effective_workers)

    def _run_limited(job: Callable[[], Any]) -> Any:
        with limiter:
            return job()

    executor = _get_shared_executor()
    futures = [executor.submit(_run_limited, job) for job in ordered_jobs]
    first_error: BaseException | None = None
    for future in futures:
        try:
            future.result()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


__all__ = ["run_output_jobs"]
