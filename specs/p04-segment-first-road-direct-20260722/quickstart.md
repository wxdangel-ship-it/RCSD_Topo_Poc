# Quickstart: P04 Segment-first Road 直出

## 1. 当前状态

Segment-first callable已在P04版本域内实现，仍不新增repo官方入口，也不接入T01–T12正式主链。调用方必须显式传入全部数据路径、全新输出目录和稳定run ID。

## 2. 当前 callable

```python
from pathlib import Path

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    SegmentFirstConfig,
    finalize_segment_first_run,
    run_segment_first_road_direct,
)

config = SegmentFirstConfig(
    patch_root=Path("<Patch_Test>"),
    swsd_road_path=Path("<prepared_swsd_roads.gpkg>"),
    swsd_node_path=Path("<prepared_swsd_nodes.gpkg>"),
    t01_road_path=Path("<t01/roads.gpkg>"),
    t01_node_path=Path("<t01/nodes.gpkg>"),
    t01_segment_path=Path("<t01/segment.gpkg>"),
    t07_surface_path=Path("<t07 accepted surface.gpkg>"),
    t03_surface_path=Path("<t03 accepted surface.gpkg>"),
    t04_surface_path=Path("<t04 accepted surface.gpkg>"),
    full_rcsd_road_path=Path("<full RCSD Road.gpkg>"),
    full_rcsd_node_path=Path("<full RCSD Node.gpkg>"),
    target_replaceability_path=Path("<optional frozen T06 replaceability.gpkg>"),
    target_disposition_path=Path("<optional confirmed target disposition.json>"),
    output_dir=Path("<new empty output directory>"),
    run_id="p04_segment_first_<case>_<timestamp>",
    frozen_v3_root=Path("<optional frozen V3 root>"),
    analysis_crs="EPSG:32650",
)
result = run_segment_first_road_direct(config)
assert result.terminal_status == "technical_passed"
print(result.summary_path)
print(result.qgis_project_path)

# 完成QGIS覆盖、真实PyQGIS回读、重复运行确定性和人工审计后：
final_result = finalize_segment_first_run(
    config.output_dir,
    config.output_dir / "p04_segment_first_acceptance_manifest.json",
)
assert final_result.terminal_status == "passed"
```

所有路径均是参数，不允许把当前Case绝对路径固化到实现。`output_dir`必须不存在或为空，且不能与任何输入目录重叠。

`target_disposition_path`只在启用闭域目标合同且业务例外已确认时传入。清单必须使用`p04-target-disposition-v1`，默认资格为`direct_build_required`；每条例外均需原因、证据、确认状态、来源和review人。它只能改变DirectBuild硬分母，不能删除Baseline或正式发布对象。

## 3. 执行顺序

1. 运行输入preflight并确认schema/CRS/hash。
2. 执行Segment-first生成器。
3. 执行独立发布后QA；该步骤只读取输出GPKG。
4. 构建带相对数据源、分组和显式样式的QGIS工程；默认只显示新结果、原始SWSD和原始完整RCSD。
5. 生成器只允许写`technical_passed`；完成QGIS覆盖、真实PyQGIS回读、确定性和人工审计证据后运行finalizer，才允许`passed`。
6. 打开QGIS按类型人工审计并记录结论。

## 4. 不允许的调用方式

- 不直接运行内部helper作为正式流程。
- 不复用V3 run ID或覆盖V3输出目录。
- 不省略独立QA后直接宣布passed。
- 不通过临时hard-coded脚本替代参数化callable。
- 不把P04输出传入T10/T09正式链。

## 5. 验收阅读顺序

1. `p04_segment_first_summary.json`
2. `p04_segment_first_independent_quality.json`
3. `p04_segment_first_report.md`
4. `p04_segment_first_comparison.qgz`
5. `p04_segment_first_audit.gpkg`中的hard/soft层

任何聚合summary都必须能下钻到逐Segment、逐Road、逐Junction、逐LaneTopo明细。

当前1885118上一轮回归run为：

`outputs/_work/p04_road_direct_generation/1885118/p04_segment_first_junction_carrier_1885118_20260723T020000`

该路径是上一轮全量发布与拓扑事实，不是当前83核心+20提右高精收敛目标的验收终态，也不是默认输入或正式入口参数。旧run `p04_segment_first_member_1885118_20260722T211000`仅保留为被业务审计否决的对照。
