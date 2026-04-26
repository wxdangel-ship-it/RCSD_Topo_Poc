from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


CASE_INPUT_FILENAMES = (
    "manifest.json",
    "size_report.json",
    "drivezone.gpkg",
    "divstripzone.gpkg",
    "nodes.gpkg",
    "roads.gpkg",
    "rcsdroad.gpkg",
    "rcsdnode.gpkg",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_git_sha(*, repo_root: Path | None = None) -> str:
    root = repo_root or Path(__file__).resolve().parents[4]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    value = result.stdout.strip()
    return value or "unknown"


def _hash_path_stat(digest, *, base: Path, path: Path) -> None:
    relative = path.relative_to(base) if path.is_relative_to(base) else path
    digest.update(str(relative).replace("\\", "/").encode("utf-8"))
    digest.update(b"\0")
    try:
        stat = path.stat()
    except OSError:
        digest.update(b"missing")
        return
    digest.update(str(int(stat.st_size)).encode("ascii"))
    digest.update(b":")
    digest.update(str(int(stat.st_mtime_ns)).encode("ascii"))


def case_input_fingerprint(input_paths: Mapping[str, Path | str]) -> str:
    digest = hashlib.sha256()
    resolved_paths = [Path(value) for _key, value in sorted(input_paths.items())]
    base = Path("/") if not resolved_paths else Path(resolved_paths[0].anchor or "/")
    for path in resolved_paths:
        _hash_path_stat(digest, base=Path(base), path=path)
    return f"case-input-stat-sha256:{digest.hexdigest()[:16]}"


def input_paths_fingerprint(input_paths: Mapping[str, Path | str]) -> str:
    digest = hashlib.sha256()
    resolved_paths = [Path(value) for _key, value in sorted(input_paths.items())]
    base = Path("/") if not resolved_paths else Path(resolved_paths[0].anchor or "/")
    for key, value in sorted(input_paths.items()):
        digest.update(str(key).encode("utf-8"))
        digest.update(b"=")
        _hash_path_stat(digest, base=Path(base), path=Path(value))
        digest.update(b"\n")
    return f"input-paths-stat-sha256:{digest.hexdigest()[:16]}"


def batch_input_dataset_id(*, case_root: Path, case_ids: Iterable[str]) -> str:
    root = Path(case_root)
    digest = hashlib.sha256()
    digest.update(str(root).encode("utf-8"))
    for case_id in sorted(str(item) for item in case_ids):
        digest.update(b"\ncase:")
        digest.update(case_id.encode("utf-8"))
        case_dir = root / case_id
        for filename in CASE_INPUT_FILENAMES:
            _hash_path_stat(digest, base=root, path=case_dir / filename)
    return f"case-package-stat-sha256:{digest.hexdigest()[:16]}"


def provenance_doc(*, input_dataset_id: str | None = None) -> dict[str, str | None]:
    return {
        "produced_at": utc_now_iso(),
        "git_sha": current_git_sha(),
        "input_dataset_id": input_dataset_id,
    }
