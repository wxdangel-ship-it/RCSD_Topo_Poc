# Clarify

## 最终 GPKG geometry 来源

- 当前最终 GPKG 仍从 `virtual_intersection_poc.py` 内部的 `virtual_polygon_geometry` 写出。
- `step6_result.primary_solved_geometry` 已经在 terminal contracts 中生成，但没有回灌给最终 export sink。

## PNG render 读取来源

- 当前 PNG render 也读取 `virtual_polygon_geometry`。
- review/failure overlay 只是样式重写，没有改变 geometry 来源。

## 当前断链点

- 断链发生在 `terminal_contracts.step6_result` 生成之后。
- improved geometry 进入了 `stage3_audit_record.step6 / cluster eval`，但没有进入：
  - `virtual_intersection_polygon.gpkg`
  - 最终 `_rendered_maps/*.png`
