# Implementation Plan: T06 上游化替换计划与问题回流

**Branch**: `codex/t10-rcsd-replacement-quality-20260614` | **Date**: 2026-06-15 | **Spec**: `specs/t06-upstream-replacement-planning-20260615/spec.md`

## Summary

本轮先把 T06 的执行边界收敛：Step2 作为替换可行性与诊断阶段，统一发布 replacement plan 与 problem registry；Step3 优先消费 replacement plan，仅保留旧产物回退兼容。随后用 problem registry 驱动 T03/T04/T05/T01/T07/T08 的后续迭代，不再把所有增强沉淀在 Step3。

## Technical Context

**Language/Version**: Python 3.10  
**Primary Dependencies**: Shapely、GeoPandas/Fiona 既有读写封装  
**Storage**: GPKG / CSV / JSON 文件产物  
**Testing**: pytest  
**Target Platform**: Windows + WSL 路径互通、本地 Codex 工作树、内网脚本由用户环境执行  
**Project Type**: Python CLI/callable GIS processing pipeline  
**Performance Goals**: 不增加 Step2/Step3 主循环复杂度；新增 plan/registry 基于既有内存行表线性生成  
**Constraints**: 单文件源码/脚本不得超过 100KB；不新增 repo CLI；不修改 T08 调用策略；不根据局部样本反推字段语义  
**Scale/Scope**: T10 4 Case 本地回归，全量由内网脚本消费同一产物契约

## Constitution Check

- Source-of-truth：模块契约改动落在 `modules/t06_segment_fusion_precheck/INTERFACE_CONTRACT.md` 与 architecture/history，项目级不重复模块细节。
- Entry points：不新增 CLI、scripts、Makefile 入口。
- File size：新增小模块承载 plan/registry，避免向接近 100KB 的 Step2 主文件追加大块逻辑。
- Data semantics：只消费已在 T01/T05/T06 契约启用的字段，不新增强字段语义推断。
- GIS/Topology：summary 和契约说明 CRS、拓扑一致性、几何语义、审计追溯、性能可验证。

## Project Structure

```text
src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/
├── replacement_plan.py
├── schemas.py
├── step2_extract_rcsd_segments.py
├── step3_group_replacement.py
└── step3_segment_replacement.py

tests/modules/t06_segment_fusion_precheck/
├── test_replacement_plan.py
└── test_step3_segment_replacement.py

modules/t06_segment_fusion_precheck/
├── INTERFACE_CONTRACT.md
├── architecture/
└── history/
```

**Structure Decision**: 新增 `replacement_plan.py` 承载 Step2 closeout 产物构建，`step2_extract_rcsd_segments.py` 只做轻量调用，`step3_*` 只做 plan 解析与兼容 fallback。

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 跨 Step2/Step3 契约调整 | 当前漏斗口径已失真，Step3 实际执行范围大于 replaceable | 只改统计字段不能消除 Step3 继续解释 audit 的架构问题 |
