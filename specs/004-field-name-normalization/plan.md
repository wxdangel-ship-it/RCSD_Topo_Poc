# Implementation Plan: 外部数据字段名统一归一化

**Branch**: `codex/004-field-name-normalization` | **Date**: 2026-07-18 | **Spec**: [spec.md](spec.md)

## Summary

新增项目级 `PropertyLookup` 作为唯一字段名归一化能力，先修复 T03/T04 对 1V1 FRCSD camelCase 字段的解析，再迁移活动模块的外部字段读取与重复 helper。保留原始属性和内部精确键契约，对仅大小写不同但值冲突的字段显式失败。

## Technical Context

**Language/Version**: Python 3.10
**Primary Dependencies**: 标准库、Fiona、Shapely、PyProj
**Storage**: GPKG、GeoJSON、CSV、JSON 文件
**Testing**: pytest
**Target Platform**: Windows 工作区；正式 GIS 验证使用 WSL Python 3.10
**Project Type**: 单仓库 Python CLI/模块流水线
**Performance Goals**: 单要素字段索引构建一次、后续 O(1) 查找；45 字段/5 次读取微基准不慢于逐字段线性扫描，并记录真实 1026960 解析耗时
**Constraints**: 不改入口、不改字段值语义、不 silent fix、不触碰 Retired T02 超阈值文件
**Scale/Scope**: Active、Active POC、Support Retained 的外部字段解析路径

## Constitution Check

- Spec/plan/tasks/implement：满足，五类职责已进入 spec。
- 源事实：本任务明确授权仓库级字段规则变更；同步项目数据模型和受影响模块契约。
- 文件体量：任何源码/测试写入前记录当前字节数；不触碰 >=100KB 文件。
- 入口治理：不新增或修改官方入口，无需修改 entrypoint registry。
- 字段语义：只处理名称大小写，不新增字段语义别名。
- GIS：CRS/geometry 算法保持不变；以 T03 邻接和 T04 拓扑解析等价性验证；冲突显式失败并保留运行上下文；执行性能微基准。
- 隔离：在独立 worktree/branch 上实施，不直接修改 main。

## Project Structure

```text
src/rcsd_topo_poc/utils/
└── field_names.py

src/rcsd_topo_poc/modules/
├── t00_utility_toolbox/
├── t01_data_preprocess/
├── t03_virtual_junction_anchor/
├── t04_divmerge_virtual_polygon/
├── t05_junction_surface_fusion/
├── t06_segment_fusion_precheck/
├── t07_semantic_junction_anchor/
├── t08_preprocess/
├── t09_swsd_field_rule_restoration/
├── t10_e2e_orchestration/
└── t11_manual_relation_review/

tests/
├── utils/
└── modules/
```

**Structure Decision**: 共享能力放在项目公共 `utils` 层，不依赖任一业务模块；模块迁移只调整外部数据解析点。

## Delivery Sequence

1. 建立共享契约测试，证明冲突、原属性保留和性能模型。
2. 添加 T03/T04 camelCase 回归并确认旧实现失败。
3. 实现共享能力，修复 T03/T04。
4. 迁移重复 helper 和其余外部字段访问；静态审计剩余精确访问。
5. 同步源事实与模块契约，执行模块测试、跨模块测试、真实 schema smoke 和体量审计。
