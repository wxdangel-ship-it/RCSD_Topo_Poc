from __future__ import annotations

import json
import shutil

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, TypeVar

from .schemas import T06Step3Artifacts


_VALIDATION_STEP3_RUN: ContextVar[bool] = ContextVar(
    "t06_validation_step3_run",
    default=False,
)
_DECISION_ONLY_VALIDATION_STEP3_RUN: ContextVar[bool] = ContextVar(
    "t06_decision_only_validation_step3_run",
    default=False,
)
_DEFER_STEP3_AUXILIARY_AUDITS: ContextVar[bool] = ContextVar(
    "t06_defer_step3_auxiliary_audits",
    default=False,
)
_DEFER_STEP3_INITIAL_TOPOLOGY_AUDIT: ContextVar[bool] = ContextVar(
    "t06_defer_step3_initial_topology_audit",
    default=False,
)
T = TypeVar("T")


@contextmanager
def validation_step3_run() -> Iterator[None]:
    """Mark a Step3 replay as a promotable, non-final validation run."""

    token = _VALIDATION_STEP3_RUN.set(True)
    try:
        yield
    finally:
        _VALIDATION_STEP3_RUN.reset(token)


def is_validation_step3_run() -> bool:
    return _VALIDATION_STEP3_RUN.get()


@contextmanager
def decision_only_validation_step3_run() -> Iterator[None]:
    """Limit a non-promotable baseline replay to topology decision outputs."""

    token = _DECISION_ONLY_VALIDATION_STEP3_RUN.set(True)
    try:
        yield
    finally:
        _DECISION_ONLY_VALIDATION_STEP3_RUN.reset(token)


def is_decision_only_validation_step3_run() -> bool:
    return _DECISION_ONLY_VALIDATION_STEP3_RUN.get()


@contextmanager
def defer_step3_auxiliary_audits() -> Iterator[None]:
    """Build ownership/construction only after surface closure is final."""

    token = _DEFER_STEP3_AUXILIARY_AUDITS.set(True)
    try:
        yield
    finally:
        _DEFER_STEP3_AUXILIARY_AUDITS.reset(token)


def are_step3_auxiliary_audits_deferred() -> bool:
    return _DEFER_STEP3_AUXILIARY_AUDITS.get()


@contextmanager
def defer_step3_initial_topology_audit() -> Iterator[None]:
    """Let the mandatory surface pass build the first formal topology audit."""

    token = _DEFER_STEP3_INITIAL_TOPOLOGY_AUDIT.set(True)
    try:
        yield
    finally:
        _DEFER_STEP3_INITIAL_TOPOLOGY_AUDIT.reset(token)


def is_step3_initial_topology_audit_deferred() -> bool:
    return _DEFER_STEP3_INITIAL_TOPOLOGY_AUDIT.get()


def select_step3_publish_jobs(jobs: Mapping[str, T]) -> dict[str, T]:
    if is_validation_step3_run() or is_decision_only_validation_step3_run():
        return {}
    return dict(jobs)


def expected_feature_triplet_paths(step_root: Path, stem: str) -> dict[str, Path]:
    return {
        "gpkg": step_root / f"{stem}.gpkg",
        "csv": step_root / f"{stem}.csv",
    }


def promote_validation_step3_outputs(
    artifacts: T06Step3Artifacts,
    final_step_root: Path,
) -> T06Step3Artifacts:
    """Publish the last validated core outputs without recalculating Step3."""

    source_step_root = artifacts.step_root.resolve()
    resolved_final_step_root = final_step_root.resolve()
    if source_step_root == resolved_final_step_root:
        raise ValueError("Validation and final Step3 roots must be different.")
    resolved_final_step_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_step_root, resolved_final_step_root, dirs_exist_ok=True)
    _rebase_json_paths(
        resolved_final_step_root,
        old_root=str(source_step_root),
        new_root=str(resolved_final_step_root),
    )

    path_updates: dict[str, Any] = {
        "run_root": resolved_final_step_root.parent,
        "step_root": resolved_final_step_root,
    }
    for field_info in fields(artifacts):
        value = getattr(artifacts, field_info.name)
        if not isinstance(value, Path):
            continue
        try:
            relative_path = value.resolve().relative_to(source_step_root)
        except ValueError:
            continue
        path_updates[field_info.name] = resolved_final_step_root / relative_path
    return replace(artifacts, **path_updates)


def _rebase_json_paths(root: Path, *, old_root: str, new_root: str) -> None:
    for path in root.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        rebased = _replace_path_prefix(payload, old_root=old_root, new_root=new_root)
        if rebased == payload:
            continue
        path.write_text(
            json.dumps(rebased, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )


def _replace_path_prefix(value: Any, *, old_root: str, new_root: str) -> Any:
    if isinstance(value, str):
        return value.replace(old_root, new_root)
    if isinstance(value, list):
        return [
            _replace_path_prefix(item, old_root=old_root, new_root=new_root)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _replace_path_prefix(item, old_root=old_root, new_root=new_root)
            for key, item in value.items()
        }
    return value
