from __future__ import annotations

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import PairRecord
from rcsd_topo_poc.modules.t01_data_preprocess.step2_segment_poc import _prune_candidate_channel


def test_prune_candidate_channel_keeps_unique_bridge_between_pair_endpoints() -> None:
    pair = PairRecord(
        pair_id="S:1__4",
        a_node_id="1",
        b_node_id="4",
        strategy_id="S",
        reverse_confirmed=True,
        forward_path_node_ids=("1", "2", "3", "4"),
        forward_path_road_ids=("r12", "r23", "r34"),
        reverse_path_node_ids=("4", "3", "2", "1"),
        reverse_path_road_ids=("r34", "r23", "r12"),
        through_node_ids=("2", "3"),
    )
    road_endpoints = {
        "r12": ("1", "2"),
        "r23": ("2", "3"),
        "r34": ("3", "4"),
        "leaf": ("2", "5"),
    }

    remaining_road_ids, branch_cut_infos, disconnected_after_prune = _prune_candidate_channel(
        pair,
        candidate_road_ids={"r12", "r23", "r34", "leaf"},
        road_endpoints=road_endpoints,
        terminate_ids={"5"},
        hard_stop_node_ids=set(),
    )

    assert remaining_road_ids == {"r12", "r23", "r34"}
    assert disconnected_after_prune is False
    assert branch_cut_infos == [
        {
            "road_id": "leaf",
            "cut_reason": "branch_leads_to_other_terminate",
            "from_node_id": "5",
            "to_node_id": "2",
        }
    ]
