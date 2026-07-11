from __future__ import annotations

from functools import partial
from pathlib import Path
from threading import Barrier, Lock

import pytest
from shapely.geometry import Point, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import LayerFeature, read_vector_layer
from rcsd_topo_poc.modules.t03_virtual_junction_anchor import t03_batch_closeout
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_streamed_results import (
    T03StreamedCaseResult,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.parallel_output import run_output_jobs


def test_run_output_jobs_uses_bounded_concurrency() -> None:
    barrier = Barrier(2)
    lock = Lock()
    completed: list[int] = []

    def job(value: int) -> None:
        barrier.wait(timeout=2.0)
        with lock:
            completed.append(value)

    run_output_jobs((partial(job, 1), partial(job, 2)), max_workers=2)

    assert sorted(completed) == [1, 2]


def test_run_output_jobs_propagates_failures() -> None:
    def fail() -> None:
        raise RuntimeError("expected output failure")

    with pytest.raises(RuntimeError, match="expected output failure"):
        run_output_jobs((fail,))


def test_virtual_polygon_closeout_reuses_fresh_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run"
    streamed_result = T03StreamedCaseResult(
        case_id="100001",
        representative_node_id="100001",
        representative_mainnodeid="100001",
        template_class="center_junction",
        association_class="A",
        association_state="established",
        step6_state="geometry_established",
        step7_state="accepted",
        visual_class="V1 认可成功",
        reason="accepted_by_formal_step7",
        note="",
        root_cause_layer=None,
        root_cause_type=None,
        source_png_path="",
        final_polygon_path=str(run_root / "cases" / "100001" / "step7_final_polygon.gpkg"),
    )
    shared_nodes = (
        LayerFeature(
            properties={
                "id": "100001",
                "mainnodeid": "100001",
                "kind_2": 4,
                "grade_2": 1,
            },
            geometry=Point(0.0, 0.0),
        ),
    )

    def unexpected_read(*args, **kwargs):
        raise AssertionError("fresh geometry must avoid reopening the case GeoPackage")

    monkeypatch.setattr(t03_batch_closeout, "read_vector_layer", unexpected_read)
    output_path = t03_batch_closeout.write_virtual_intersection_polygons(
        run_root=run_root,
        shared_nodes=shared_nodes,
        streamed_results={"100001": streamed_result},
        final_polygon_geometries={"100001": box(0.0, 0.0, 1.0, 1.0)},
    )

    output_features = read_vector_layer(output_path).features
    assert len(output_features) == 1
    assert output_features[0].properties["mainnodeid"] == "100001"
    assert output_features[0].geometry.equals(box(0.0, 0.0, 1.0, 1.0))
