from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rcsd_topo_poc.protocol.text_lint import lint_text
from rcsd_topo_poc.protocol.text_qc_bundle import build_demo_bundle


@pytest.mark.smoke
def test_smoke_qc_demo_bundle_writes_outputs_work() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path("outputs/_work/smoke_qc_bundle") / f"{run_id}_{os.getpid()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = build_demo_bundle()
    out_file = out_dir / "TEXT_QC_BUNDLE.txt"
    out_file.write_text(bundle + "\n", encoding="utf-8")

    assert out_file.is_file()

    ok, violations = lint_text(bundle)
    assert ok is True, violations
    assert "Truncated: true" in bundle
