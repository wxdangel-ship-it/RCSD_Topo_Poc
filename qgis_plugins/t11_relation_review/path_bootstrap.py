from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_repo_src_on_path() -> Path:
    candidates = []
    env_src = os.environ.get("RCSD_TOPO_POC_SRC")
    env_root = os.environ.get("RCSD_TOPO_POC_ROOT")
    if env_src:
        candidates.append(Path(env_src))
    if env_root:
        candidates.append(Path(env_root) / "src")

    plugin_path = Path(__file__).resolve()
    candidates.extend(
        [
            plugin_path.parents[2] / "src",
            Path("/mnt/e/Work/RCSD_Topo_Poc/src"),
            Path("/mnt/c/Users/admin/.codex/worktrees/t11-qgis-manual-review-plugin/RCSD_Topo_Poc/src"),
            Path("E:/Work/RCSD_Topo_Poc/src"),
            Path("C:/Users/admin/.codex/worktrees/t11-qgis-manual-review-plugin/RCSD_Topo_Poc/src"),
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            src = str(candidate)
            if src not in sys.path:
                sys.path.insert(0, src)
            return candidate
    raise RuntimeError(
        "Cannot locate RCSD_Topo_Poc src. Set RCSD_TOPO_POC_SRC or RCSD_TOPO_POC_ROOT before loading the plugin."
    )
