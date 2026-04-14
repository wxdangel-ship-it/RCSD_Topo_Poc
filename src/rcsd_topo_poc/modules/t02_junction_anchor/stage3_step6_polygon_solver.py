from __future__ import annotations

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_solve import (
    Stage3Step6GeometrySolveInputs,
    build_stage3_step6_geometry_solve_result,
)


def build_stage3_step6_polygon_solver_result(
    inputs: Stage3Step6GeometrySolveInputs,
):
    return build_stage3_step6_geometry_solve_result(inputs)


__all__ = [
    "Stage3Step6GeometrySolveInputs",
    "build_stage3_step6_geometry_solve_result",
    "build_stage3_step6_polygon_solver_result",
]
