import json
from dataclasses import replace
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_compiler import compile_jsg_case
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    CarrierRealization,
    DirectionRole,
    DirectionStructure,
    JSGCaseTruth,
    JunctionSegmentRelation,
    JunctionType,
    JunctionUnit,
    ObjectState,
    StandardSegmentUnit,
    StructuralRole,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import write_vector_payloads


def test_compiler_materializes_declared_label_only_r2_ir(tmp_path: Path) -> None:
    road_payload = {
        "id": "r1",
        "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 0.0]]},
        "properties": {"id": "r1", "snodeid": "j1", "enodeid": "j2", "direction": 2, "source": 2},
    }
    node_payloads = [
        {"id": "j1", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "properties": {"id": "j1"}},
        {"id": "j2", "geometry": {"type": "Point", "coordinates": [1.0, 0.0]}, "properties": {"id": "j2"}},
    ]
    road_meta = {"driver": "GPKG", "layer": "road", "crs_wkt": "EPSG:3857", "schema": {"geometry": "LineString", "properties": {"id": "str", "snodeid": "str", "enodeid": "str", "direction": "int", "source": "int"}}}
    node_meta = {"driver": "GPKG", "layer": "node", "crs_wkt": "EPSG:3857", "schema": {"geometry": "Point", "properties": {"id": "str"}}}
    truth_road = tmp_path / "truth_road.gpkg"
    truth_node = tmp_path / "truth_node.gpkg"
    write_vector_payloads(truth_road, [road_payload], meta=road_meta)
    write_vector_payloads(truth_node, node_payloads, meta=node_meta)
    oracle_manifest = tmp_path / "oracle.json"
    road_edits_path = tmp_path / "road_edits.jsonl"
    node_edits_path = tmp_path / "node_edits.jsonl"
    oracle_manifest.write_text("{}\n", encoding="utf-8")
    road_edits_path.write_text("{}\n", encoding="utf-8")
    node_edits_path.write_text("{}\n", encoding="utf-8")
    hashes = tuple(sorted({
        "r2_oracle_manifest": sha256_file(oracle_manifest),
        "road_edits": sha256_file(road_edits_path),
        "node_edits": sha256_file(node_edits_path),
        "truth_road": sha256_file(truth_road),
        "truth_node": sha256_file(truth_node),
    }.items()))
    carrier = CarrierRealization(str(oracle_manifest), "sample", str(road_edits_path), str(node_edits_path), str(truth_road), str(truth_node), hashes)
    junctions = (
        JunctionUnit("j1", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
        JunctionUnit("j2", JunctionType.NORMAL, "1", (), ObjectState.PUBLISHABLE),
    )
    segment = StandardSegmentUnit("s1", ("j1", "j2"), (), DirectionStructure.DIRECTED, "0-1", "UNSPECIFIED", ("r1",), (), False, ObjectState.PUBLISHABLE)
    relations = (
        JunctionSegmentRelation("j1", "s1", StructuralRole.ENDPOINT, DirectionRole.EXIT, ("j1",), (), ObjectState.PUBLISHABLE),
        JunctionSegmentRelation("j2", "s1", StructuralRole.ENDPOINT, DirectionRole.ENTER, ("j2",), (), ObjectState.PUBLISHABLE),
    )
    case = JSGCaseTruth("T10:fixture", "T10", "fixture", "EPSG:3857", "manifest", (), junctions, (segment,), relations, (), (), carrier, ())
    road_edits = [{"sample_id": "sample", "label_only": True, "action": "CREATE", "output_payloads": [road_payload]}]
    node_edits = [{"sample_id": "sample", "label_only": True, "action": "CREATE", "output_payloads": node_payloads}]
    result = compile_jsg_case(case, road_edits, node_edits, tmp_path / "compiled")
    assert result["exact"] is True
    assert result["road_f1"] == 1.0
    assert result["node_f1"] == 1.0
    assert len(result["compiled_graph_signature"]) == 64

    broken_relations = (replace(relations[0], access_legs=("missing",)), relations[1])
    broken_case = replace(case, junction_segment_relations=broken_relations)
    broken = compile_jsg_case(
        broken_case,
        road_edits,
        node_edits,
        tmp_path / "broken_compiled",
    )
    assert broken["exact"] is False
    assert broken["carrier_missing_reference_count"] == 1
