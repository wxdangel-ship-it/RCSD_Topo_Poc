# P04 SWSD-first Road 直出 POC

本文件是 `p04_road_direct_generation` 的模块阅读入口。P04 在 SWSD 路口和路段语义骨架约束下，研究如何利用 Patch Vector 的 Lane、LaneTopo、Boundary、道路面和道路设施直接生成逻辑自洽的高精 RoadGraph。

## 1. 当前状态

- 生命周期：`Active POC / 成果模块`。
- 当前阶段：历史M1/M2、冻结Directional Road V2和High-Precision Road V3保留为只读对照；当前主线是独立Segment-first SpecKit。Case 1885118当前综合效果最佳的人工审计候选为`p04_segment_first_junction_interior_v75_1885118_20260725T050000`；该版本落实T07人工面优先、T03/T04次选和Road端点严格进入原始accepted surface。
- 当前候选保持330/330 Segment、831/831 Access、371/371 Junction Movement和独立QA 0 violation；三层合同为Baseline 103、Patch资料不足6、RealityChange 1、DirectBuildRequired 96，当前完成86/96。V75没有沿用V69将旁侧邻近Road视为THROUGH接入的错误口径，因此仍为`Active POC / terminal_status=failed`，不得finalize为阶段完成。
- 当前主职责：以 SWSD/T01 保持 Junction—Segment 功能结构，以Patch Road/Lane/LaneTopo/Boundary/RoadSurface实例化高精Road/Node/RoadNextRoad；允许互不重叠的built与`swsd_retained_partial`表达，保持分布式路口portal，并发布几何来源、四态、目标合同、物理走廊决策、旧成果差异及独立QA/QGIS材料。
- 上游：prepared SWSD Road/Node、T01 Segment 语义和 Patch Vector 数据；第二里程碑暂不依赖 SWSD restriction/Laneinfo/RoadSplit。
- 下游：P04 POC Road/Lane/movement 候选及 QA；当前不进入 T05/T06/T09 正式 handoff。

## 2. 文档职责

| 文档 | 承载内容 |
|---|---|
| `SPEC.md` | 模块定位、业务范围、目标流程和对错边界。 |
| `architecture/01-introduction-and-goals.md` | 架构上下文、目标、范围和非目标。 |
| `architecture/02-data-and-domain-model.md` | SWSD 骨架、Vector evidence、RoadCandidate 和 MovementProjection 模型。 |
| `architecture/03-solution-strategy.md` | SWSD-first 五阶段方案。 |
| `architecture/04-evidence-and-audit.md` | formal POC、review-only、internal 和 handoff 证据分层。 |
| `architecture/05-quality-requirements.md` | CRS、拓扑、几何、审计和性能要求。 |
| `architecture/06-risks-and-technical-debt.md` | 字段、数据覆盖、入口和正式化风险。 |
| `architecture/1885118-patch-vector-baseline.md` | 当前 6 个 Patch 的实测数据理解基线。 |
| `architecture/1885118-milestone1-results.md` | 第一里程碑真实运行结论、异常分层和 QGIS 检查方法。 |
| `architecture/1885118-milestone2-road-support-analysis.md` | 第二里程碑参数选择前的 Lane 局部分段、Road 支持和敏感性分析。 |
| `architecture/1885118-milestone2-results.md` | 第二里程碑真实运行、四态、RoadGraph 拓扑、QGIS 与性能终验。 |
| `architecture/1885118-directional-road-v2-results.md` | Directional Road V2 方向拆分、稳定中心、几何 A/B、Portal、QGIS 与性能终验。 |
| `architecture/1885118-high-precision-road-v3-results.md` | High-Precision Road V3 物理走廊、高精来源、LaneTopo、独立 QA、QGIS 与性能终验。 |
| `INTERFACE_CONTRACT.md` | 当前输入边界、状态、入口事实和最小审计要求。 |

## 3. 当前入口位置

- 无 repo 官方 CLI。
- 正式内网执行入口：`scripts/p04_run_segment_first_innernet.py`。它只负责显式参数解析、输入前检和调用`run_segment_first_road_direct(SegmentFirstConfig)`，不复制业务算法。
- Patch输入只接受`--patch-root`目录；SWSD、T01、T07、T03、T04、完整RCSD及可选目标合同均按独立文件路径参数传入，不硬编码本地或内网路径。
- 历史`run_milestone_one(MilestoneOneConfig)`、`run_milestone_two(MilestoneTwoConfig)`、`run_directional_road_v2(DirectionalRoadV2Config)`、`run_high_precision_road_v3(HighPrecisionRoadV3Config)`，以及当前`run_segment_first_road_direct(SegmentFirstConfig)`与`finalize_segment_first_run(...)`继续作为模块callable；只有Segment-first生成入口由上述脚本正式包装。

正式调用方式：

```bash
.venv/bin/python scripts/p04_run_segment_first_innernet.py \
  --patch-root PATCH_ROOT \
  --swsd-road SWSD_ROAD_FILE \
  --swsd-node SWSD_NODE_FILE \
  --t01-road T01_ROAD_FILE \
  --t01-node T01_NODE_FILE \
  --t01-segment T01_SEGMENT_FILE \
  --t07-surface T07_SURFACE_FILE \
  --t03-surface T03_SURFACE_FILE \
  --t04-surface T04_SURFACE_FILE \
  --full-rcsd-road FULL_RCSD_ROAD_FILE \
  --full-rcsd-node FULL_RCSD_NODE_FILE \
  --target-replaceability TARGET_REPLACEABILITY_FILE \
  --target-disposition TARGET_DISPOSITION_FILE \
  --output-dir NEW_OUTPUT_DIR \
  --run-id RUN_ID
```

`--target-replaceability`和`--target-disposition`可选；默认运行成功物化结果即返回0，并在stdout JSON中分别给出`terminal_status/core_gate_pass`。需要业务core gate失败时返回2，可增加`--require-core-pass`。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/1885118-patch-vector-baseline.md`
3. `architecture/1885118-milestone1-results.md`
4. `architecture/1885118-milestone2-road-support-analysis.md`
5. `architecture/1885118-milestone2-results.md`
6. `architecture/1885118-directional-road-v2-results.md`
7. `architecture/1885118-high-precision-road-v3-results.md`
8. `architecture/01-introduction-and-goals.md`
9. `architecture/02-data-and-domain-model.md`
10. `architecture/03-solution-strategy.md`
11. `architecture/04-evidence-and-audit.md`
12. `architecture/05-quality-requirements.md`
13. `architecture/06-risks-and-technical-debt.md`
14. `INTERFACE_CONTRACT.md`

## 5. POC 边界

P04 与现有 relation-first 替换主链并行。当前数据分析、候选状态和未来 POC 输出均不能直接提升为正式 RCSD/F-RCSD 生产真值。
