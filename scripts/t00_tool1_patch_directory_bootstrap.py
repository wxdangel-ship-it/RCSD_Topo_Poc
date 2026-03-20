#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


# Windows reference: D:\TestData\POC_Data\数据整理\vectors
SOURCE_VECTOR_ROOT = Path("/mnt/d/TestData/POC_Data/数据整理/vectors")

# Windows reference: D:\TestData\POC_Data\patch_all
TARGET_PATCH_ROOT = Path("/mnt/d/TestData/POC_Data/patch_all")


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "src").is_dir():
            return candidate
    return None


def main() -> int:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        print("Repo root not found. Expected SPEC.md and src/ above this script.", file=sys.stderr)
        return 2

    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from rcsd_topo_poc.modules.t00_utility_toolbox import (
        PatchBootstrapConfig,
        run_patch_directory_bootstrap,
    )

    summary = run_patch_directory_bootstrap(
        PatchBootstrapConfig(
            source_root=SOURCE_VECTOR_ROOT,
            target_root=TARGET_PATCH_ROOT,
        )
    )

    print(f"run_id={summary['run_id']}")
    print(f"total_patch_count={summary['total_patch_count']}")
    print(f"success_count={summary['success_count']}")
    print(f"failure_count={summary['failure_count']}")
    print(f"skip_count={summary['skip_count']}")
    print(f"log_path={summary['log_path']}")
    print(f"summary_path={summary['summary_path']}")

    return 0 if summary["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
