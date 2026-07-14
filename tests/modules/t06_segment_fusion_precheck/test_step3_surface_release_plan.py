from pathlib import Path

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_surface_aware_plan_release
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import step3_surface_release_plan


def test_surface_release_split_preserves_compatibility_exports() -> None:
    assert (
        step3_surface_aware_plan_release._surface_release_plan_rows
        is step3_surface_release_plan._surface_release_plan_rows
    )
    assert (
        step3_surface_aware_plan_release._release_allowed
        is step3_surface_release_plan._release_allowed
    )
    assert (
        step3_surface_aware_plan_release._points_by_id
        is step3_surface_release_plan._points_by_id
    )


def test_surface_release_split_stays_below_60_kib() -> None:
    module_root = Path(step3_surface_release_plan.__file__).resolve().parent
    paths = (
        module_root / "step3_surface_aware_plan_release.py",
        module_root / "step3_surface_release_plan.py",
    )
    assert {path.name: path.stat().st_size for path in paths} == {
        path.name: path.stat().st_size for path in paths if path.stat().st_size < 60 * 1024
    }
