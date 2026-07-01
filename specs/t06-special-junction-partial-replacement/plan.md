# Implementation Plan: T06 特殊路口局部替换策略

**Branch**: `codex/t06-special-junction-partial-replacement` | **Date**: 2026-07-01 | **Spec**: `specs/t06-special-junction-partial-replacement/spec.md`

## Summary

将 T06 Step2 的特殊路口门控从“全组可替换才允许替换”改为“全通过、局部通过、全阻断”三态。Step2 保留已可替换 Segment，并只让全通过特殊组发布内部 RCSD 替换计划；partial 组依赖标准/path-corridor 可执行计划和 Step3 语义路口分组表达端点关系。

## Technical Context

**Language/Version**: Python 3.10
**Primary Dependencies**: 既有 Shapely/GeoPandas/Fiona 读写封装
**Storage**: GPKG / CSV / JSON 审计产物
**Testing**: pytest
**Target Platform**: Windows + WSL 路径互通、本地 Codex 工作树
**Performance Goals**: special junction gate 仍为线性扫描，不新增空间索引或二次拓扑推断
**Constraints**: 不新增 CLI/脚本入口；不改 T05/T10 对外契约；源码/脚本文件不得超过 100KB；不根据单 case 反推新字段语义
**Scale/Scope**: T06 Step2/Step3 局部策略与审计口径，目标基准覆盖既有复杂路口 case 和单测环岛 fixture

## Constitution Check

- **Product**: 用户已明确环岛与复杂路口的 partial 替换口径，并确认环岛 partial 保留 SWSD 内部 road，不保留 RCSD 内部端点间 road。
- **Architecture**: Step2 只发布全通过特殊组内部 RCSD 计划；Step3 继续执行 replacement plan，并通过 semantic junction group 表达 partial 端点语义。
- **Development**: 修改范围限定在 T06 special gate、Step2 summary/plan closeout、T06 模块源事实和测试。
- **Testing**: 用单测覆盖环岛 partial、blocked、复杂组 partial；用既有基准 case 做修改前后对比。
- **QA**: 回归报告必须说明 CRS/拓扑/几何语义/审计追溯/性能指标。

## Project Structure

```text
src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/
├── step2_special_junctions.py
├── step2_extract_rcsd_segments.py
└── replacement_plan.py

tests/modules/t06_segment_fusion_precheck/
├── test_step2_special_junctions.py
├── test_special_junction_partial_replacement_plan.py
└── test_runner_outputs.py

modules/t06_segment_fusion_precheck/
├── SPEC.md
├── INTERFACE_CONTRACT.md
└── architecture/
```

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 无 | 本轮只调整既有 T06 Step2 门控与审计口径 | 不适用 |
