"""Probe: build the assembly_canvas_mask for 706347 and inspect what splits it."""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

sys.path.insert(0, str(Path("src").resolve()))

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (  # noqa: E402
    DEFAULT_PATCH_SIZE_M,
    _binary_close,
    _binary_dilation,
    _build_grid,
    _mask_to_geometry,
    _rasterize_geometries,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._rcsd_selection_support import (  # noqa: E402
    _normalize_geometry,
)


def _components(mask: np.ndarray) -> list[np.ndarray]:
    visited = np.zeros_like(mask, dtype=bool)
    out: list[np.ndarray] = []
    rows, cols = mask.shape
    for r0 in range(rows):
        for c0 in range(cols):
            if not mask[r0, c0] or visited[r0, c0]:
                continue
            stack = [(r0, c0)]
            comp = np.zeros_like(mask, dtype=bool)
            while stack:
                r, c = stack.pop()
                if r < 0 or r >= rows or c < 0 or c >= cols:
                    continue
                if visited[r, c] or not mask[r, c]:
                    continue
                visited[r, c] = True
                comp[r, c] = True
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    stack.append((r + dr, c + dc))
            out.append(comp)
    return out


def main(case_id: str, run_id: str = "phase1_bug2_bug5_706347_765050") -> None:
    base = Path(f"outputs/_work/t04_six_case_scenario_realign/{run_id}/cases/{case_id}")
    df = gpd.read_file(base / "step5_domains.gpkg", layer="step5_domains")
    case = df[df["scope"] == "case"]

    def role(name: str):
        sub = case[case["domain_role"] == name]
        if len(sub) == 0:
            return None
        return _normalize_geometry(unary_union(list(sub.geometry)))

    allowed = role("case_allowed_growth_domain")
    must_cover = role("case_must_cover_domain")
    forbidden = role("case_forbidden_domain")
    cuts = role("case_terminal_cut_constraints")
    cut_buffer = cuts.buffer(0.75, cap_style=2, join_style=2) if cuts is not None else None

    print("allowed:", allowed.geom_type, "area=", allowed.area)
    print("must_cover:", must_cover.geom_type, "area=", must_cover.area)
    print("forbidden:", forbidden.geom_type, "area=", forbidden.area)
    print("cuts:", cuts.geom_type if cuts is not None else None, "len=", cuts.length if cuts is not None else 0)

    from shapely.geometry import Point as _Pt
    cx = (allowed.bounds[0] + allowed.bounds[2]) / 2
    cy = (allowed.bounds[1] + allowed.bounds[3]) / 2
    grid = _build_grid(_Pt(cx, cy), patch_size_m=DEFAULT_PATCH_SIZE_M, resolution_m=0.5)
    print("grid shape:", getattr(grid, "mask_shape", None) or getattr(grid, "shape", None))

    allowed_mask = _rasterize_geometries(grid, [allowed])
    forbid_mask = _rasterize_geometries(grid, [forbidden])
    cut_mask = _rasterize_geometries(grid, [cut_buffer]) if cut_buffer is not None else np.zeros_like(allowed_mask, dtype=bool)
    must_mask = _rasterize_geometries(grid, [must_cover])

    canvas = allowed_mask & ~forbid_mask & ~cut_mask
    print("\nallowed_mask cells:", int(allowed_mask.sum()))
    print("forbidden_mask cells:", int(forbid_mask.sum()))
    print("cut_mask cells:", int(cut_mask.sum()))
    print("canvas cells:", int(canvas.sum()))

    print("\nallowed_mask components:", len(_components(allowed_mask)))
    print("must_cover_mask components:", len(_components(must_mask)))
    print("canvas components:", len(_components(canvas)))

    # Try variants
    canvas_close1 = _binary_close(canvas, iterations=1) & allowed_mask & ~forbid_mask & ~cut_mask
    canvas_close2 = _binary_close(canvas, iterations=2) & allowed_mask & ~forbid_mask & ~cut_mask
    canvas_close3 = _binary_close(canvas, iterations=3) & allowed_mask & ~forbid_mask & ~cut_mask
    canvas_close5 = _binary_close(canvas, iterations=5) & allowed_mask & ~forbid_mask & ~cut_mask
    print("close1 (with cut barrier) components:", len(_components(canvas_close1)))
    print("close2 (with cut barrier) components:", len(_components(canvas_close2)))
    print("close3 (with cut barrier) components:", len(_components(canvas_close3)))
    print("close5 (with cut barrier) components:", len(_components(canvas_close5)))

    # without cut barrier (simulate: would close if cuts allowed bridging)
    canvas_nocut = allowed_mask & ~forbid_mask
    print("\nallowed & ~forbidden (no cut) components:", len(_components(canvas_nocut)))
    canvas_nocut_close1 = _binary_close(canvas_nocut, iterations=1) & allowed_mask & ~forbid_mask
    print("allowed & ~forbidden close1 components:", len(_components(canvas_nocut_close1)))

    # without forbidden
    canvas_noforbid = allowed_mask & ~cut_mask
    print("allowed & ~cut (no forbidden) components:", len(_components(canvas_noforbid)))

    canvas_only_allowed = allowed_mask
    print("allowed only components:", len(_components(canvas_only_allowed)))


if __name__ == "__main__":
    case_id = sys.argv[1] if len(sys.argv) > 1 else "706347"
    run_id = sys.argv[2] if len(sys.argv) > 2 else "phase1_bug2_bug5_706347_765050"
    main(case_id, run_id)
