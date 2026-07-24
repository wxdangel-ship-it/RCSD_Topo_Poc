from __future__ import annotations

from pathlib import Path

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd


def _write_graph(
    root: Path,
    name: str,
    *,
    direction: int = 2,
    source: int = 1,
    include_road: bool = True,
    end_node_id: str = "n2",
    end_x: float = 10.0,
    crs: str = "EPSG:3857",
) -> tuple[Path, Path]:
    road_path = root / f"{name}_road.gpkg"
    node_path = root / f"{name}_node.gpkg"
    with fiona.open(
        road_path,
        "w",
        driver="GPKG",
        layer="road",
        crs=crs,
        schema={"geometry": "LineString", "properties": {"id": "str", "snodeid": "str", "enodeid": "str", "direction": "int", "source": "int"}},
    ) as sink:
        if include_road:
            sink.write(
                {
                    "geometry": {"type": "LineString", "coordinates": ((0.0, 0.0), (10.0, 0.0))},
                    "properties": {"id": "r1", "snodeid": "n1", "enodeid": end_node_id, "direction": direction, "source": source},
                }
            )
    with fiona.open(
        node_path,
        "w",
        driver="GPKG",
        layer="node",
        crs=crs,
        schema={"geometry": "Point", "properties": {"id": "str", "source": "int"}},
    ) as sink:
        sink.write({"geometry": {"type": "Point", "coordinates": (0.0, 0.0)}, "properties": {"id": "n1", "source": 1}})
        sink.write({"geometry": {"type": "Point", "coordinates": (end_x, 0.0)}, "properties": {"id": "n2", "source": 1}})
    return road_path, node_path


def test_oracle_is_perfect_and_corruptions_are_detected(tmp_path: Path) -> None:
    truth_road, truth_node = _write_graph(tmp_path, "truth")
    oracle = evaluate_frcsd(truth_road, truth_node, truth_road, truth_node)

    assert oracle["overall_passed"] is True
    assert oracle["road_object"]["f1"] == 1.0
    assert oracle["directed_topology"]["f1"] == 1.0

    scenarios = {
        "deleted": _write_graph(tmp_path, "deleted", include_road=False),
        "direction": _write_graph(tmp_path, "direction", direction=3),
        "source": _write_graph(tmp_path, "source", source=2),
        "moved": _write_graph(tmp_path, "moved", end_x=15.0),
        "broken": _write_graph(tmp_path, "broken", end_node_id="missing"),
    }
    results = {
        name: evaluate_frcsd(candidate_road, candidate_node, truth_road, truth_node)
        for name, (candidate_road, candidate_node) in scenarios.items()
    }

    assert all(not result["overall_passed"] for result in results.values())
    assert results["deleted"]["road_object"]["recall"] == 0.0
    assert results["direction"]["attributes"]["direction_accuracy"] == 0.0
    assert results["source"]["attributes"]["source_accuracy"] == 0.0
    assert results["moved"]["geometry_m"]["node_distance"]["max"] == 5.0
    assert any("missing" in failure for failure in results["broken"]["hard_failures"])


def test_crs_mismatch_is_a_hard_failure(tmp_path: Path) -> None:
    truth_road, truth_node = _write_graph(tmp_path, "truth")
    candidate_road, candidate_node = _write_graph(tmp_path, "candidate", crs="EPSG:32650")

    result = evaluate_frcsd(candidate_road, candidate_node, truth_road, truth_node)

    assert result["overall_passed"] is False
    assert result["crs"]["compatible"] is False
    assert "candidate and truth CRS differ" in result["hard_failures"]
