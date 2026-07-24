import os

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p0 import _percentile, _rss_bytes


def test_percentile_uses_deterministic_linear_interpolation() -> None:
    assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == 4.8


def test_peak_rss_is_measurable_on_supported_runtime() -> None:
    if os.name == "nt":
        assert _rss_bytes() > 0
