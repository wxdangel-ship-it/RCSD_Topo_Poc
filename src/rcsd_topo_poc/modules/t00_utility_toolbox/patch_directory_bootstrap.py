from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


RUN_ID_PREFIX = "t00_tool1_patch_directory_bootstrap"


@dataclass(frozen=True)
class PatchBootstrapConfig:
    source_root: Path
    target_root: Path
    run_id: str | None = None


def _sort_key(name: str) -> tuple[int, int | str]:
    stripped = name.strip()
    if stripped.isdigit():
        return (0, int(stripped))
    return (1, stripped)


def _build_run_id(now: datetime | None = None) -> str:
    current = datetime.now() if now is None else now
    return f"{RUN_ID_PREFIX}_{current.strftime('%Y%m%d_%H%M%S')}"


def _clear_directory_contents(path: Path) -> None:
    if not path.exists():
        return

    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_patch_files(source_patch_dir: Path, target_vector_dir: Path) -> int:
    copied_file_count = 0
    for child in sorted(source_patch_dir.iterdir(), key=lambda item: _sort_key(item.name)):
        if child.is_dir():
            raise ValueError(
                f"Source patch directory '{source_patch_dir}' contains nested directory '{child.name}', "
                "which is outside the current Tool1 scope."
            )
        if not child.is_file():
            raise ValueError(
                f"Source patch directory '{source_patch_dir}' contains unsupported entry '{child.name}'."
            )

        shutil.copy2(child, target_vector_dir / child.name)
        copied_file_count += 1

    return copied_file_count


def _build_logger(log_path: Path, run_id: str) -> logging.Logger:
    logger = logging.getLogger(run_id)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        for existing_handler in list(logger.handlers):
            existing_handler.close()
            logger.removeHandler(existing_handler)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


def run_patch_directory_bootstrap(config: PatchBootstrapConfig) -> dict[str, Any]:
    source_root = config.source_root.expanduser().resolve()
    target_root = config.target_root.expanduser().resolve()

    if not source_root.is_dir():
        raise ValueError(f"Source root does not exist or is not a directory: {source_root}")

    target_root.mkdir(parents=True, exist_ok=True)

    run_id = config.run_id or _build_run_id()
    started_at = datetime.now().isoformat(timespec="seconds")
    log_path = target_root / f"{run_id}.log"
    summary_path = target_root / f"{run_id}_summary.json"

    logger = _build_logger(log_path, run_id)
    try:
        logger.info("Run started.")
        logger.info("Source root: %s", source_root)
        logger.info("Target root: %s", target_root)

        source_patch_dirs = sorted(
            [path for path in source_root.iterdir() if path.is_dir()],
            key=lambda path: _sort_key(path.name),
        )

        patch_results: list[dict[str, Any]] = []
        success_count = 0
        failure_count = 0
        skip_count = 0

        for source_patch_dir in source_patch_dirs:
            patch_id = source_patch_dir.name
            target_patch_dir = target_root / patch_id
            target_pointcloud_dir = target_patch_dir / "PointCloud"
            target_vector_dir = target_patch_dir / "Vector"
            target_traj_dir = target_patch_dir / "Traj"

            try:
                if not patch_id.isdigit():
                    raise ValueError("PatchID directory name must be numeric.")

                target_pointcloud_dir.mkdir(parents=True, exist_ok=True)
                target_vector_dir.mkdir(parents=True, exist_ok=True)
                target_traj_dir.mkdir(parents=True, exist_ok=True)
                _clear_directory_contents(target_vector_dir)

                copied_file_count = _copy_patch_files(source_patch_dir, target_vector_dir)
                success_count += 1
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "success",
                        "copied_file_count": copied_file_count,
                        "skipped": False,
                        "error_reason": None,
                    }
                )
                logger.info("Patch %s succeeded. copied_file_count=%s", patch_id, copied_file_count)
            except Exception as exc:
                failure_count += 1
                skip_count += 1
                if target_vector_dir.exists():
                    _clear_directory_contents(target_vector_dir)
                patch_results.append(
                    {
                        "patch_id": patch_id,
                        "status": "failure",
                        "copied_file_count": 0,
                        "skipped": True,
                        "error_reason": str(exc),
                    }
                )
                logger.exception("Patch %s failed and was skipped: %s", patch_id, exc)

        total_patch_count = len(source_patch_dirs)
        if success_count + failure_count != total_patch_count:
            raise RuntimeError(
                "Summary invariant violated: success_count + failure_count must equal total_patch_count."
            )

        summary = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "source_root": str(source_root),
            "target_root": str(target_root),
            "total_patch_count": total_patch_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "skip_count": skip_count,
            "patch_results": patch_results,
            "log_path": str(log_path),
            "summary_path": str(summary_path),
        }

        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "Run completed. total_patch_count=%s success_count=%s failure_count=%s skip_count=%s",
            total_patch_count,
            success_count,
            failure_count,
            skip_count,
        )
        return summary
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
