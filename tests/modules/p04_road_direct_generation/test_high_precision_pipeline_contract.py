from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    HighPrecisionRoadV3Config,
    run_high_precision_road_v3,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.high_precision_pipeline import (
    _output_names,
    _report,
)


def test_v3_keeps_m2_and_frozen_v2_in_isolated_locations(tmp_path: Path) -> None:
    frozen = tmp_path / "frozen-v2"
    config = HighPrecisionRoadV3Config(
        patch_root=tmp_path / "patches",
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "v3",
        run_id="hp-v3",
        frozen_v2_root=frozen,
        expected_parent_road_count=571,
    )

    milestone_two = config.milestone_two_config()
    assert milestone_two.output_dir == tmp_path / "v3" / "_milestone2"
    assert milestone_two.run_id == "hp-v3_m2"
    assert config.frozen_v2_root == frozen
    assert config.output_dir != frozen
    assert callable(run_high_precision_road_v3)


def test_v3_success_thresholds_are_explicit_configuration(tmp_path: Path) -> None:
    config = HighPrecisionRoadV3Config(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "roads.gpkg",
        swsd_node_path=tmp_path / "nodes.gpkg",
        output_dir=tmp_path / "v3",
        run_id="hp-v3",
    )

    assert config.minimum_evidence_road_control_ratio == 0.8
    assert config.maximum_network_swsd_fallback_ratio == 0.4
    assert config.drivezone_tolerance_m == 1.5


def test_v3_output_contract_names_actual_four_network_qgis_project() -> None:
    assert _output_names()["qgis_project"] == "p04_hp_v3_four_network_comparison.qgz"


def test_v3_final_report_prefers_independent_published_metrics() -> None:
    report = _report(
        {
            "high_precision_geometry": {
                "observed_ratio": 0.39,
                "evidence_road_control_ratio": 0.90,
                "swsd_fallback_ratio": 0.40,
            },
            "independent_quality": {
                "geometry_source": {
                    "observed_ratio": 0.389968,
                    "evidence_road_control_ratio": 0.885503,
                    "network_swsd_fallback_ratio": 0.398172,
                }
            },
            "frozen_v2_comparison": {
                "v3_road_count": 603,
                "matched_count": 603,
                "median_mean_sample_distance_m": 0.133292,
                "p95_sample_distance_m": 4.869610,
            },
        }
    )

    assert "指标来源：独立发布后 QA" in report
    assert "有证据 Road高精控制覆盖：88.55%" in report
    assert "全网 SWSD fallback：39.82%" in report
    assert "冻结 V2 逐 Road 对照：603 / 603 已匹配" in report
