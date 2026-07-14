from __future__ import annotations

import os
import subprocess
import sys


def test_package_defers_step3_only_imports_but_preserves_export() -> None:
    module_prefix = "rcsd_topo_poc.modules.t06_segment_fusion_precheck"
    code = f"""
import sys
import {module_prefix} as package
assert {module_prefix!r} + '.step3_segment_replacement' not in sys.modules
assert {module_prefix!r} + '.rcsd_unreplaced_attribution' not in sys.modules
assert callable(package.run_t06_step3_segment_replacement)
assert {module_prefix!r} + '.step3_segment_replacement' in sys.modules
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
