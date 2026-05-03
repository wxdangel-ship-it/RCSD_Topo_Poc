"""Find which unrelated RCSDRoad/RCSDNode actually cuts allowed_growth_domain into multiple components."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path("src").resolve()))


def parts(g):
    if g is None or g.is_empty:
        return []
    return list(g.geoms) if hasattr(g, "geoms") else [g]


def main(case_id: str, run_id: str = "phase1_c2_706347_765050"):
    base = Path(f"outputs/_work/t04_six_case_scenario_realign/{run_id}/cases/{case_id}")
    df = gpd.read_file(base / "step5_domains.gpkg", layer="step5_domains")
    case = df[df["scope"] == "case"]
    allowed = unary_union(list(case[case["domain_role"] == "case_allowed_growth_domain"].geometry))
    forbidden = unary_union(list(case[case["domain_role"] == "case_forbidden_domain"].geometry))

    with open(base / "step5_status.json", encoding="utf-8") as f:
        status = json.load(f)
    channels = status.get("negative_mask_channels", {})
    unrelated_rcsd_road_ids = list(channels.get("unrelated_rcsd", {}).get("road_ids", []))
    unrelated_rcsd_node_ids = list(channels.get("unrelated_rcsd", {}).get("node_ids", []))

    # Read RCSDRoad/RCSDNode source from case-package
    pkg = Path(r"E:/TestData/POC_Data/T02/Anchor_2") / case_id
    rr = gpd.read_file(pkg / "rcsdroad.gpkg")
    rn = gpd.read_file(pkg / "rcsdnode.gpkg")
    print(f"RCSDRoad columns: {rr.columns.tolist()}")
    rr_id_col = "id" if "id" in rr.columns else rr.columns[0]
    rn_id_col = "id" if "id" in rn.columns else rn.columns[0]
    rr["__id"] = rr[rr_id_col].astype(str)
    rn["__id"] = rn[rn_id_col].astype(str)

    # baseline component count of allowed alone
    print(f"allowed.area={allowed.area:.2f}  parts={len(parts(allowed))}")
    print(f"allowed - forbidden  parts={len(parts(allowed.difference(forbidden)))}  area={allowed.difference(forbidden).area:.2f}")

    # Try removing each unrelated road buffer and see if components reduce
    BUFFER = 1.0  # STEP5_NEGATIVE_MASK_BUFFER_M (default 1.0 from contract)
    print("\nProbing each unrelated_rcsd road individually:")
    for road_id in unrelated_rcsd_road_ids:
        sub = rr[rr["__id"] == road_id]
        if len(sub) == 0:
            continue
        rgeom = unary_union(list(sub.geometry))
        if rgeom is None or rgeom.is_empty:
            continue
        rbuf = rgeom.buffer(BUFFER, cap_style=2, join_style=2)
        intersection_with_allowed = rbuf.intersection(allowed)
        if intersection_with_allowed.is_empty:
            continue
        forbidden_minus_road = forbidden.difference(rbuf)
        new_components = parts(allowed.difference(forbidden_minus_road))
        if len(new_components) < len(parts(allowed.difference(forbidden))):
            print(f"  road {road_id}: REDUCES components -> {len(new_components)} (intersection_with_allowed_area={intersection_with_allowed.area:.2f})")
        else:
            # Check if the road's buffer is inside allowed
            ratio = intersection_with_allowed.area / max(rbuf.area, 1e-9)
            if intersection_with_allowed.area > 0.1:
                print(f"  road {road_id}: in allowed area={intersection_with_allowed.area:.2f}, ratio={ratio:.2%}")

    # Also try removing all unrelated_rcsd roads at once
    print("\nProbing all unrelated_rcsd roads union:")
    all_rcsd_geoms = []
    for road_id in unrelated_rcsd_road_ids:
        sub = rr[rr["__id"] == road_id]
        if len(sub) > 0:
            g = unary_union(list(sub.geometry))
            if g is not None and not g.is_empty:
                all_rcsd_geoms.append(g.buffer(BUFFER, cap_style=2, join_style=2))
    if all_rcsd_geoms:
        all_rcsd_buf = unary_union(all_rcsd_geoms)
        ne_forbidden = forbidden.difference(all_rcsd_buf)
        nc = parts(allowed.difference(ne_forbidden))
        print(f"  remove all unrelated_rcsd roads -> components = {len(nc)}")

    # Now probe SWSD side
    swsd_road_ids = list(channels.get("unrelated_swsd", {}).get("road_ids", []))
    swsd_node_ids = list(channels.get("unrelated_swsd", {}).get("node_ids", []))
    rd = gpd.read_file(pkg / "roads.gpkg")
    nd = gpd.read_file(pkg / "nodes.gpkg")
    rd["__id"] = rd["id"].astype(str)
    nd["__id"] = nd["id"].astype(str)

    print(f"\nProbing each unrelated_swsd road individually (top hits in allowed):")
    candidates = []
    for rid in swsd_road_ids:
        sub = rd[rd["__id"] == rid]
        if len(sub) == 0:
            continue
        g = unary_union(list(sub.geometry))
        if g is None or g.is_empty:
            continue
        buf = g.buffer(BUFFER, cap_style=2, join_style=2)
        inter = buf.intersection(allowed)
        if inter.area > 0.1:
            ne_forbidden = forbidden.difference(buf)
            nc = parts(allowed.difference(ne_forbidden))
            candidates.append((rid, inter.area, len(nc), nc))
    candidates.sort(key=lambda r: -r[1])
    for rid, area, nc_count, _ in candidates[:8]:
        marker = "REDUCES" if nc_count < 2 else "no-reduce"
        print(f"  road {rid}: in_allowed_area={area:.2f}, removed_components={nc_count} {marker}")

    print(f"\nProbing each unrelated_swsd node individually (top hits in allowed):")
    nc_candidates = []
    for nid in swsd_node_ids:
        sub = nd[nd["__id"] == nid]
        if len(sub) == 0:
            continue
        g = unary_union(list(sub.geometry))
        if g is None or g.is_empty:
            continue
        buf = g.buffer(BUFFER)
        inter = buf.intersection(allowed)
        if inter.area > 0.05:
            ne_forbidden = forbidden.difference(buf)
            nc = parts(allowed.difference(ne_forbidden))
            nc_candidates.append((nid, inter.area, len(nc)))
    nc_candidates.sort(key=lambda r: -r[1])
    for nid, area, nc_count in nc_candidates[:10]:
        marker = "REDUCES" if nc_count < 2 else "no-reduce"
        print(f"  node {nid}: in_allowed_area={area:.2f}, removed_components={nc_count} {marker}")

    # Try removing all unrelated_swsd roads + nodes union
    swsd_all = []
    for rid in swsd_road_ids:
        sub = rd[rd["__id"] == rid]
        if len(sub) > 0:
            swsd_all.append(unary_union(list(sub.geometry)).buffer(BUFFER, cap_style=2, join_style=2))
    for nid in swsd_node_ids:
        sub = nd[nd["__id"] == nid]
        if len(sub) > 0:
            swsd_all.append(unary_union(list(sub.geometry)).buffer(BUFFER))
    if swsd_all:
        swsd_buf = unary_union(swsd_all)
        ne_forbidden = forbidden.difference(swsd_buf)
        nc = parts(allowed.difference(ne_forbidden))
        print(f"\n  remove all unrelated_swsd (roads+nodes) -> components = {len(nc)}")

    # Combined: remove unrelated_rcsd + unrelated_swsd
    if all_rcsd_geoms or swsd_all:
        combo = unary_union((all_rcsd_geoms or []) + (swsd_all or []))
        ne_forbidden = forbidden.difference(combo)
        nc = parts(allowed.difference(ne_forbidden))
        print(f"  remove ALL unrelated (swsd+rcsd) -> components = {len(nc)}")

    print("\nProbing each unrelated_rcsd node individually:")
    for node_id in unrelated_rcsd_node_ids:
        sub = rn[rn["__id"] == node_id]
        if len(sub) == 0:
            continue
        ngeom = unary_union(list(sub.geometry))
        if ngeom is None or ngeom.is_empty:
            continue
        nbuf = ngeom.buffer(BUFFER)
        intersection_with_allowed = nbuf.intersection(allowed)
        if intersection_with_allowed.area > 0.1:
            forbidden_minus_node = forbidden.difference(nbuf)
            new_components = parts(allowed.difference(forbidden_minus_node))
            if len(new_components) < len(parts(allowed.difference(forbidden))):
                print(f"  node {node_id}: REDUCES components -> {len(new_components)} (in_allowed_area={intersection_with_allowed.area:.2f})")
            else:
                print(f"  node {node_id}: in allowed area={intersection_with_allowed.area:.2f} (does not split)")


if __name__ == "__main__":
    case_id = sys.argv[1] if len(sys.argv) > 1 else "706347"
    run_id = sys.argv[2] if len(sys.argv) > 2 else "phase1_c2_706347_765050"
    main(case_id, run_id)
