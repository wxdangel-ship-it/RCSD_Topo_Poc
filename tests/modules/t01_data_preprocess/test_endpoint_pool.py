from __future__ import annotations

import csv
from pathlib import Path

from rcsd_topo_poc.modules.t01_data_preprocess.endpoint_pool import collect_endpoint_pool_mainnodes


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_collect_endpoint_pool_mainnodes_normalizes_integral_decimal_node_ids(tmp_path: Path) -> None:
    _write_csv(
        tmp_path / "S2" / "endpoint_pool.csv",
        [{"node_id": "100.0", "source_tags": "S2"}],
        ["node_id", "source_tags"],
    )
    _write_csv(
        tmp_path / "STEP4" / "validated_pairs.csv",
        [{"pair_id": "S4:200.0__300.0", "a_node_id": "200.0", "b_node_id": "300.0"}],
        ["pair_id", "a_node_id", "b_node_id"],
    )

    node_ids, source_map = collect_endpoint_pool_mainnodes(
        base_dir=tmp_path,
        source_specs=(
            ("S2", ("S2/endpoint_pool.csv",)),
            ("STEP4", ("STEP4/validated_pairs.csv",)),
        ),
    )

    assert node_ids == {"100", "200", "300"}
    assert source_map["100"] == ("S2",)
    assert source_map["200"] == ("STEP4",)
    assert source_map["300"] == ("STEP4",)
