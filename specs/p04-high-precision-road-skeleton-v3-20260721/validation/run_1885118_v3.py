from __future__ import annotations

import argparse
from pathlib import Path

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    HighPrecisionRoadV3Config,
    run_high_precision_road_v3,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Case 1885118 P04 V3 core validation replay."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    result = run_high_precision_road_v3(
        HighPrecisionRoadV3Config(
            patch_root=Path(r"E:\TestData\POC_Data\T10\1885118\Patch_Test"),
            swsd_road_path=Path(
                r"E:\TestData\POC_Data\T10\1885118\external_inputs"
                r"\prepared_swsd_roads\prepared_swsd_roads_slice.gpkg"
            ),
            swsd_node_path=Path(
                r"E:\TestData\POC_Data\T10\1885118\external_inputs"
                r"\prepared_swsd_nodes\prepared_swsd_nodes_slice.gpkg"
            ),
            output_dir=args.output_dir,
            run_id=args.run_id,
            t01_road_path=Path(
                r"E:\Work\RCSD_Topo_Poc\outputs\baselines"
                r"\t10_six_4b1c496_20260715_070100\t10\e2e_full\cases"
                r"\1885118\t01\roads.gpkg"
            ),
            t01_segment_path=Path(
                r"E:\Work\RCSD_Topo_Poc\outputs\baselines"
                r"\t10_six_4b1c496_20260715_070100\t10\e2e_full\cases"
                r"\1885118\t01\segment.gpkg"
            ),
            current_rcsd_road_path=Path(
                r"E:\TestData\POC_Data\T10\1885118\external_inputs"
                r"\rcsdroad\rcsdroad_slice.gpkg"
            ),
            frozen_v2_root=Path(
                r"E:\Work\RCSD_Topo_Poc\outputs\_work"
                r"\p04_road_direct_generation\1885118"
                r"\p04_directional_v2_1885118_20260721T154712"
            ),
            expected_parent_road_count=571,
        )
    )
    print(result.summary_path)
    print(f"core_gate_pass={result.core_gate_pass}")
    return 0 if result.core_gate_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
