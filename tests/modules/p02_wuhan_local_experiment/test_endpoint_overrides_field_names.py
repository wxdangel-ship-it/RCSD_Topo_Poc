from __future__ import annotations

from pathlib import Path

from rcsd_topo_poc.modules.p02_wuhan_local_experiment.endpoint_overrides import _load_overrides


def test_endpoint_override_csv_accepts_case_variant_headers_and_endpoint_field(tmp_path: Path) -> None:
    override_path = tmp_path / "confirmed_overrides.csv"
    override_path.write_text(
        "Road_ID,Endpoint_Field,Expected_Old_Node_ID,Replacement_Node_ID\n"
        "r1,SNodeId,n1,n2\n",
        encoding="utf-8",
    )

    rows = _load_overrides(override_path)

    assert rows == (
        {
            "road_id": "r1",
            "endpoint_field": "snodeid",
            "expected_old_node_id": "n1",
            "replacement_node_id": "n2",
        },
    )
