# T10 Case 空间切片证据包任务清单

## Specify

- [x] 确认 shared external inputs 去重不是当前目标。
- [x] 确认 `semantic_junction_id + radius_m` 空间切片是当前修复目标。
- [x] 确认每个 Case 目录独立保存局部外部输入。

## Plan

- [x] 定义空间切片源：`prepared_swsd_nodes`。
- [x] 定义窗口 CRS：`EPSG:3857`。
- [x] 定义输出结构：`cases/<case_id>/external_inputs/<slot>/<slot>_slice.gpkg`。
- [x] 定义 QA 审计字段。

## Implement

- [x] 新增 T10 空间切片模块。
- [x] 接入 Case package build。
- [x] 更新正式脚本默认物化模式。
- [x] 更新模块契约与 README。

## Test

- [x] 覆盖空间切片 Case package。
- [x] 覆盖多 Case 独立目录。
- [x] 覆盖文本 bundle 解包结构。

## QA

- [x] CRS 与坐标变换记录在 manifest。
- [x] 拓扑不 silent fix，记录 invalid geometry。
- [x] 几何语义记录 center / radius / bounds。
- [x] 审计可追溯到每个 source path 与 output path。
- [x] 性能可通过 feature count 与 file size 观察。
