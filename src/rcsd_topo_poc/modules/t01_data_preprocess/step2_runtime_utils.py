from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import _find_repo_root


DEFAULT_RUN_ID_PREFIX = "t01_step2_segment_poc_"
Step2ProgressCallback = Callable[[str, dict[str, Any]], None]


def _build_default_run_id(now: Optional[datetime] = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        return Path(out_root), resolved_run_id

    start = Path.cwd() if cwd is None else cwd
    repo_root = _find_repo_root(start)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_step2_segment_poc" / resolved_run_id, resolved_run_id


def _emit_progress(
    progress_callback: Optional[Step2ProgressCallback],
    event: str,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return
    progress_callback(event, payload)
