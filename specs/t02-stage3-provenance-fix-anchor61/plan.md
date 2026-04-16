# Plan

## 断链位置

- `build_stage3_terminal_contracts()` 已产出 `step6_result.primary_solved_geometry`。
- `run_t02_virtual_intersection_poc()` 仍用旧的 `virtual_polygon_geometry` 做 export/render。

## 最小修复点

1. 在 `virtual_intersection_poc.py` 中引入 `final_virtual_polygon_geometry`。
2. 最终 `write_vector(...)` 改为写 `final_virtual_polygon_geometry`。
3. terminal contracts 之后的最终 PNG 重写改为使用 `final_virtual_polygon_geometry`。
4. 不修改 Step7/root cause/tri-state 语义。

## 最小测试

1. `test_stage3_step6_regularization.py`
2. `test_stage3_step6_geometry_controller.py`
3. `test_stage3_step6_scaleout_anchor_cases.py`
4. `test_anchor61_baseline.py`

## 重点验证

- rerun `584253 / 705817 / 10970944`
- 快速确认 `698330 / 706389 / 520394575`
