"""one-off probe: inspect 706347 / 765050 step5 domains and final_case_polygon topology."""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from shapely.ops import unary_union


def parts(g):
    return list(g.geoms) if hasattr(g, "geoms") else [g]


def show_layer(label, df):
    print(f"=== {label} ===")
    if "scope" in df.columns:
        for scope in ("case", "unit"):
            sub = df[df["scope"] == scope]
            for _, row in sub.iterrows():
                g = row.geometry
                role = getattr(row, "domain_role", "")
                eu = getattr(row, "event_unit_id", "")
                p = parts(g)
                print(f"  [{scope}] {eu:18s} {role:40s} type={g.geom_type} area={g.area:.2f} parts={len(p)}")
    else:
        u = unary_union(list(df.geometry))
        ps = parts(u)
        print(f"  union: type={u.geom_type} area={u.area:.2f} parts={len(ps)}")
        for i, pp in enumerate(ps):
            c = pp.centroid
            print(f"    comp{i}: area={pp.area:.2f} centroid=({c.x:.2f},{c.y:.2f}) bbox={tuple(round(b,2) for b in pp.bounds)}")


def inspect(label, root):
    print(f"\n##### {label}: {root} #####")
    p = Path(root)
    if (p / "step5_domains.gpkg").exists():
        df = gpd.read_file(p / "step5_domains.gpkg", layer="step5_domains")
        show_layer("step5_domains", df)
    if (p / "final_case_polygon.gpkg").exists():
        df = gpd.read_file(p / "final_case_polygon.gpkg")
        show_layer("final_case_polygon", df)


if __name__ == "__main__":
    cases = sys.argv[1:] if len(sys.argv) > 1 else ["706347", "765050"]
    for case_id in cases:
        old = f"outputs/_work/t04_negative_mask_hard_barrier_final/negative_mask_hard_barrier_final_20260503/cases/{case_id}"
        new = f"outputs/_work/t04_six_case_scenario_realign/phase1_bug2_bug5_706347_765050/cases/{case_id}"
        inspect(f"{case_id} OLD", old)
        inspect(f"{case_id} NEW (Bug2+5)", new)
