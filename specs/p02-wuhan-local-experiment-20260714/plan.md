# P02 武汉局部实验实施计划

**Branch**: `codex/p02-wuhan-local-experiment-20260714` | **Date**: 2026-07-14

## 1. 摘要

在隔离工作树内建立 `p02_wuhan_local_experiment`，同步 `closed_connect` 别名源事实与 T08/T01 契约，实现 Tool5 后人工关系 canonical 转换 callable，并在新的 P02 run root 执行 T08、T01、T05、T06 局部实验。

## 2. 技术上下文

- Python：仓库 `.venv` / Python 3.x。
- 空间依赖：仓库现有 GeoPackage/GeoJSON、Shapely、pyproj、GDAL/Fiona 兼容栈。
- 测试：pytest。
- 输入规模：143/163 SWSD Node/Road，655/469 RCSDNode/RCSDRoad。
- 输出：`outputs/_work/p02_wuhan_local_experiment/<run_id>/`。
- 性能目标：所有阶段在局部数据上完成，并记录阶段 wall time；不设置未经基线证明的绝对速度门槛。

## 3. 宪章与治理检查

- 分层源事实：项目字段语义、模块契约、P02 文档和 SpecKit 工件分别落位；通过。
- Brownfield：先研究、spec、plan、tasks、analyze，再实现；通过。
- 五职责：产品、架构、研发、测试、QA 均已覆盖；通过。
- 入口治理：不新增 repo CLI/root script/长期命令；通过。
- 文件体量：写任何 `.py` 前先检查当前字节数；新文件按 0 字节记录；通过。
- GIS：CRS、拓扑、几何、审计、性能均有任务；通过。

## 4. 变更结构

```text
docs/architecture/02-data-and-domain-model.md
docs/doc-governance/module-lifecycle.md
docs/doc-governance/current-module-inventory.md
docs/doc-governance/module-doc-status.csv
modules/t08_preprocess/{SPEC.md,INTERFACE_CONTRACT.md,architecture/*}
modules/t01_data_preprocess/{SPEC.md,INTERFACE_CONTRACT.md,architecture/*}
modules/p02_wuhan_local_experiment/
src/rcsd_topo_poc/modules/p02_wuhan_local_experiment/
tests/modules/p02_wuhan_local_experiment/
tests/modules/t08_preprocess/
src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_split.py
src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/io.py
specs/p02-wuhan-local-experiment-20260714/
```

运行产物只写到 `outputs/_work`，不纳入 git 源事实。

## 5. 实施阶段

1. 同步字段源事实和模块生命周期。
2. 先写 `closed_connect` 与 relation 转换失败测试。
3. 实现 T08 Tool3 alias normalization 与 P02 relation callable。
4. 运行聚焦测试与治理检查。
5. 运行 Tool1→3→6→4→5。
6. 落盘 raw/converted T11 CSV 和 lineage。
7. 运行 T01、T05、T06。
8. 汇总 GIS/拓扑/性能/业务 funnel。
9. 撤销 P02 local clip，以 Tool1 完整输出重跑 T01/T05/T06，并刷新 QGIS/QA。
10. 按用户确认生成 run06 RCSDRoad 完整工作副本，仅覆盖 `5855295910117569.ENodeId` 与 `5855295910117517.SNodeId`，再从 T08/T01/T05/T06 全流程重跑并刷新 QGIS/QA。
11. 按全量端点审计与用户授权建立 9 项显式覆盖白名单，生成 run07 完整工作副本；复用未变化的 T08/T01 正式产物，从端点覆盖后重跑 T05/T06，刷新 QA、QGIS 和最终验证报告。
12. 基于原始 Road 有序跟踪纠正 run07 的并行通道反向归属，按“正式锚定关系 > required junction 有序相对位置 > 几何距离”修复 T06，生成 run08 并刷新 QA、QGIS 和最终验证报告。

## 6. 风险控制

- Tool5 聚合导致 target 冲突：转换阶段阻断。
- T05 空兼容输入被误解为 T03/T04/T07 成果：manifest 和文件名明确 `unavailable_empty_compat`。
- 缺失端点污染完整性结论：单列原始/工作副本 input integrity audit；不删除 Road、不补造 Node，9 项用户确认覆盖逐项落盘，禁止扩大到清单外端点。
- road-only split 投影失败：保留 T05 audit，进入待补关系，不由 P02 猜测新 road。
- T06 替换率偏低：分开报告 relation 发布、graph consumability、Step2 replaceable 和 Step3 topology，不扁平化为单一成功率。
- 无人工锚定 Segment 被误替换：逐项核对 T05 relation、Step2 replacement plan 与 Step3 relation，确保未锚定对象保持 SWSD。
- 原始 `CrossLid` 与 `SNodeId/ENodeId` 表现不一致：本轮只记录证据，不从局部样本固化字段语义或端点修复规则。
