from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_oof import (
    _class_metrics,
    _expected_failure_manifest,
    _percentile,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_models import (
    SchemeAP1OOFConfig,
)


def test_scheme_a_p1_class_metrics() -> None:
    metrics = _class_metrics(
        ["USE_RCSD", "KEEP_SWSD", "REVIEW_FALLBACK"],
        ["USE_RCSD", "KEEP_SWSD", "KEEP_SWSD"],
    )
    assert metrics["USE_RCSD"]["precision"] == 1.0
    assert metrics["REVIEW_FALLBACK"]["recall"] == 0.0


def test_scheme_a_p1_percentile() -> None:
    assert _percentile([1.0, 3.0, 2.0], 0.95) == 3.0


def test_scheme_a_p1_expected_failure_manifest(tmp_path) -> None:
    config = SchemeAP1OOFConfig(
        dataset_run_root=tmp_path,
        candidate_run_root=tmp_path,
        scheme_a_baseline_run_root=tmp_path,
        output_root=tmp_path,
        run_id="test",
    )
    manifest = _expected_failure_manifest(config)
    assert manifest["T10:74155468"] == frozenset(
        {
            "Road endpoint Node missing: 953982",
            "directed edge endpoint missing: 953982->47348378",
        }
    )
