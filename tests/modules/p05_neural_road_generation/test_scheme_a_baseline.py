from pathlib import Path

import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_baseline import (
    _canonical_crs,
    _label_weight,
    _require_single_crs,
    _strategy_mapping,
    _string_list,
    _verified_outputs,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierTarget,
    StrategyOutcome,
)


@pytest.mark.parametrize(
    ("status", "outcome", "target"),
    [
        ("replaced", StrategyOutcome.SUCCESS_DIRECT, CarrierTarget.USE_RCSD),
        ("retained_swsd", StrategyOutcome.SUCCESS_WITH_FALLBACK, CarrierTarget.KEEP_SWSD),
        (
            "replaced+retained_swsd",
            StrategyOutcome.SUCCESS_WITH_FALLBACK,
            CarrierTarget.MIXED_CARRIER,
        ),
        ("failed", StrategyOutcome.FAIL, CarrierTarget.REVIEW_FALLBACK),
    ],
)
def test_strategy_status_mapping_is_closed(
    status: str, outcome: StrategyOutcome, target: CarrierTarget
) -> None:
    assert _strategy_mapping(status) == (outcome, target)


def test_unknown_strategy_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown T06 relation_status"):
        _strategy_mapping("invented")


def test_list_parsing_and_crs_are_canonical() -> None:
    assert _string_list('["1",2]') == ["1", "2"]
    assert _string_list("1,2") == ["1", "2"]
    assert _canonical_crs("EPSG:3857") == "EPSG:3857"


def test_crs_tamper_is_rejected() -> None:
    with pytest.raises(ValueError, match="CRS mismatch"):
        _require_single_crs("T10:case", {"EPSG:3857", "EPSG:4326"})


def test_segment_level_weights_distinguish_target_and_context() -> None:
    sample = {
        "scope_type": "t10_segment",
        "business_id": "target",
        "target_weight": "0.7",
        "context_weight": "0.3",
    }
    assert _label_weight(sample, ("target",)) == (0.7, "TARGET")
    assert _label_weight(sample, ("context",)) == (0.3, "CONTEXT")


def test_manifest_output_hash_tamper_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("before", encoding="utf-8")
    manifest = {
        "outputs": {
            "artifact": {
                "path": str(artifact),
                "sha256": sha256_file(artifact),
            }
        }
    }
    assert _verified_outputs(manifest, strict_hashes=True)["artifact"] == artifact.resolve()
    artifact.write_text("after", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        _verified_outputs(manifest, strict_hashes=True)
