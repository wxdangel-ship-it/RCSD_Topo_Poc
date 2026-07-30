from __future__ import annotations

import geopandas as gpd
import math
import pandas as pd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_path_scoring import (
    build_target_path_metrics,
)


def test_path_metrics_preserve_numeric_and_boolean_coercion() -> None:
    frame = gpd.GeoDataFrame(
        {
            "assignment_score": ["1.5", None, "invalid", math.inf],
            "full_rcsd_anchor_supported": [None, False, True, pd.NA],
            "geometry": [
                LineString([(0.0, 0.0), (2.0, 0.0)]),
                LineString([(2.0, 0.0), (4.0, 0.0)]),
                LineString([(4.0, 0.0), (6.0, 0.0)]),
                LineString([(6.0, 0.0), (8.0, 0.0)]),
            ],
        },
        crs="EPSG:32650",
    )

    metrics = build_target_path_metrics(
        {"road": frame},
        LineString([(0.0, 0.0), (10.0, 0.0)]),
    )["road"]

    assert metrics.finite_assignment_scores == (1.5,)
    assert metrics.full_rcsd_anchor_supported is True
    assert metrics.intervals == (
        (0.0, 2.0),
        (2.0, 4.0),
        (4.0, 6.0),
        (6.0, 8.0),
    )
