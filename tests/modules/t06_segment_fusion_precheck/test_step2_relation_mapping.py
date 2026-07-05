from __future__ import annotations

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.relation_mapping import build_relation_map, check_segment_relations


def _rel(target_id: str, base_id, status=0):
    return {"properties": {"target_id": target_id, "base_id": base_id, "status": status}, "geometry": None}


def test_pair_and_junc_relations_are_required() -> None:
    relation_map = build_relation_map([_rel("1", 10), _rel("2", 20), _rel("3", 30)])

    check = check_segment_relations(pair_nodes=["1", "2"], junc_nodes=["3"], relation_map=relation_map)

    assert check.ok
    assert check.rcsd_pair_nodes == ["10", "20"]
    assert check.rcsd_junc_nodes == ["30"]


def test_relation_mapping_reports_pair_failures() -> None:
    missing = check_segment_relations(pair_nodes=["1", "2"], junc_nodes=[], relation_map=build_relation_map([_rel("1", 10)]))
    bad_status = check_segment_relations(pair_nodes=["1", "2"], junc_nodes=[], relation_map=build_relation_map([_rel("1", 10), _rel("2", 20, status=1)]))
    bad_base = check_segment_relations(pair_nodes=["1", "2"], junc_nodes=[], relation_map=build_relation_map([_rel("1", 10), _rel("2", 0)]))

    assert missing.reject_reason == "missing_pair_relation"
    assert missing.rcsd_pair_nodes == ["10"]
    assert bad_status.reject_reason == "invalid_pair_relation_status"
    assert bad_status.rcsd_pair_nodes == ["10"]
    assert bad_base.reject_reason == "invalid_pair_base_id"
    assert bad_base.rcsd_pair_nodes == ["10"]


def test_relation_mapping_rejects_required_junc_failures() -> None:
    missing = check_segment_relations(pair_nodes=["1", "2"], junc_nodes=["3"], relation_map=build_relation_map([_rel("1", 10), _rel("2", 20)]))
    bad_status = check_segment_relations(pair_nodes=["1", "2"], junc_nodes=["3"], relation_map=build_relation_map([_rel("1", 10), _rel("2", 20), _rel("3", 30, status=1)]))
    bad_base = check_segment_relations(pair_nodes=["1", "2"], junc_nodes=["3"], relation_map=build_relation_map([_rel("1", 10), _rel("2", 20), _rel("3", -1)]))

    assert not missing.ok
    assert missing.reject_reason == "missing_junc_relation"
    assert missing.failed_junc_nodes == ["3"]
    assert missing.failed_junc_reasons == {"3": "missing_junc_relation"}
    assert not bad_status.ok
    assert bad_status.reject_reason == "invalid_junc_relation_status"
    assert bad_status.failed_junc_reasons == {"3": "invalid_junc_relation_status"}
    assert not bad_base.ok
    assert bad_base.reject_reason == "invalid_junc_base_id"
    assert bad_base.failed_junc_reasons == {"3": "invalid_junc_base_id"}
