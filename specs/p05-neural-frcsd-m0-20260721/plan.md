# Implementation Plan: P05 神经网络 F-RCSD 直出 POC M0

**Branch**: `codex/p05-neural-road-poc-20260721` | **Date**: 2026-07-21 | **Spec**: [spec.md](spec.md)

## Summary

新增 P05 POC 的 M0 数据与度量层：扫描限定的 `POC_Data` Case，按用户确认的 `1.0/0.7/0.3` 规则建立训练样本与标签 lineage；从显式 baseline root 解析 canonical T01-T06 handoff；按业务 ID 生成无泄漏五折；提供 T06 F-RCSD Road/Node identity-first、geometry-fallback 评估器及 Oracle/破坏测试。M0 不训练模型、不增加 ML 依赖、不修改 T01-T06。

## Technical Context

**Language/Version**: Python `3.10.x`  
**Dependencies**: 现有 `fiona`、`shapely`、`pyproj`、标准库；不新增依赖  
**Storage**: 只读 GPKG/GeoJSON/JSON/CSV；输出 CSV/JSON/Markdown  
**Testing**: pytest 单元/契约/集成测试；本地 689 单点 manifest、52 个 T10 package 与 canonical baseline 审计  
**Platform**: 当前 PowerShell/Windows；路径通过既有 runtime normalization 兼容 manifest 中 WSL 路径  
**Performance Goal**: 本地清点与 label lineage 构建在可测量时间内完成；逐阶段记录 scan/hash/evaluate/write 耗时和对象量  
**Constraints**: 仅 `E:\TestData\POC_Data`；不 silent fix；不新增正式入口；源码/测试单文件 `<100KB`

## Constitution Check

| Gate | 结论 | 证据 / 处理 |
|---|---|---|
| 分层源事实 | PASS | SpecKit 承载变更；P05 模块源事实与项目生命周期同轮同步。 |
| Brownfield 研究 | PASS | 已核对 T01-T06/T10 契约、52 Case baseline、T03/T04/T10 manifest。 |
| 非破坏性 | PASS | 外部输入和 baseline 只读；新 run root 拒绝覆盖。 |
| 入口治理 | PASS | M0 只有模块 callable；无 CLI、root script 或 Makefile 目标。 |
| 文件体量 | PASS | 新源码写入前按 0 字节确认，目标单文件 `<60KiB`，完成后全量审计。 |
| GIS 五项 | PASS | CRS、拓扑、几何、lineage、性能进入输出与验收。 |
| 五类职责 | PASS | 下文与 tasks 覆盖产品、架构、研发、测试、QA。 |

## Architecture and Responsibilities

### 产品视角

- M0 的价值是建立可信训练尺子，不以模型 loss 或已有 baseline passed 代替真值质量。
- 强/中/弱标签必须分开报告，`0.3` 不能掩盖 `1.0/0.7` 的效果。

### 架构视角

- `inventory` 负责 Case 与 manifest；`labels` 负责 baseline handoff；`splits` 负责 group；`evaluation` 负责 RoadGraph；`runner/outputs` 负责不可变运行。
- P05 输入契约独立于 T10 编排，不把 P05 放入正式主链。

### 研发视角

- 源码拆成 models/inventory/labels/splits/evaluation/outputs/runner，单文件保持小而可测。
- 不复制 T01-T06 算法，只读取对外产物。
- 所有排序、hash、fold 和 CSV 字段确定性。

### 测试视角

- 合成 fixture 覆盖三类 scope、重复版本、缺失 manifest、wrong-root、label 缺失和 split 泄漏。
- 小型 RoadGraph 覆盖 Oracle 与缺失/方向/source/端点/拓扑破坏。
- 本地真实数据只作为验证，不写入版本库 fixture。

### QA 视角

- CRS：记录源 CRS，缺失或不一致显式阻断/异常。
- 拓扑：读取和比较，不修复；Road endpoint/Node 引用可定位。
- 几何：保留原始对象 ID、长度、端点、匹配原因和距离。
- 审计：路径、hash、baseline repo head、权重、split、异常可追溯。
- 性能：记录文件/feature 数、阶段耗时、峰值范围说明。

## Project Structure

```text
src/rcsd_topo_poc/modules/p05_neural_road_generation/
├── __init__.py
├── models.py
├── inventory.py
├── labels.py
├── splits.py
├── evaluation.py
├── outputs.py
└── runner.py

tests/modules/p05_neural_road_generation/
├── test_inventory.py
├── test_labels_and_splits.py
├── test_evaluation.py
└── test_runner.py
```

## Delivery Phases

1. 冻结 SpecKit、数据模型、输出合同和模块源事实。
2. 先写 inventory/label/split/evaluation 失败测试。
3. 实现 M0 模块 callable 与不可变输出。
4. 运行合成测试、Oracle/破坏测试。
5. 对本地全部范围数据运行，检查 `SC-001~SC-010`。
6. 更新项目源事实、生命周期、盘点与 code-size audit，完成逐项审计。

