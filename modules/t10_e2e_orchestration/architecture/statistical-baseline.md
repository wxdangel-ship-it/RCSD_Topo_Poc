# T10 统计基线补充材料

本文件记录当前有效的 T10 全量 Case 统计基线。它是模块级补充材料，不替代 `01-06` 架构主结构，也不改变 T10 / T06 / T09 的接口契约。

## 1. 当前有效基线

- 刷新日期：2026-07-01。
- 刷新版本：`3cd626d`。归档校验时当前 `HEAD` 为 `1130d7c`，但差异只涉及 T11 / QGIS 插件相关文件，不涉及本次 T10 / T06 基线执行链路。
- 基线目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_3cd626d_20260701_214807`
- 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_3cd626d_20260701_214807/e2e_full`
- 当前指针文件：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_ALL_CASES_BASELINE.txt`、`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_BASELINE.txt`
- 执行工作区：`/mnt/e/Work/RCSD_Topo_Poc`
- 执行入口：`scripts/t10_run_e2e_cases.sh --package-dir /mnt/e/TestData/POC_Data/T10`
- Case package 根目录：`/mnt/e/TestData/POC_Data/T10`
- Case 范围：`1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176`。
- T10 总状态：`passed`，6 个 Case 全部完成，失败 Case 数为 0。
- T10 summary 耗时：`3840.283633s`，旧基线为 `4203.419684s`，减少 `363.136051s`，约 `8.6391%`。
- Case stage 累计耗时：`3811.207862s`，旧基线为 `4179.433963s`，减少 `368.226101s`，约 `8.8104%`。
- 上游反馈统计：Segment `685`，pair-anchor endpoint cluster `864`，side-group candidate `24`，side-group endpoint candidate `37`，relation `0`。

本基线替代旧全量基线 `/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345`。日常测试输出不得覆盖该目录；新的优化运行应写入独立 run root，再与本目录下的 CSV / JSON 进行比较。

## 2. 旧基线处理

旧基线指针已全部切换到新目录：

- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_ALL_CASES_BASELINE.txt`
- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_BASELINE.txt`

旧目录已清理所有可删除内容，但仍有 3 个 `gpkg` 文件被 Windows 外部进程占用，无法删除或改名。归档时观察到占用进程为 `qgis-ltr-bin.exe pid=38780`：

- `/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345/e2e_full/cases/605415675/t01/roads.gpkg`
- `/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345/e2e_full/cases/605415675/t01/segment.gpkg`
- `/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345/e2e_full/cases/605415675/t04/t04/nodes.gpkg`

关闭该 QGIS 会话后，可重新执行 `rm -rf /mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345` 完成物理删除。该残留不影响当前有效基线指针。

## 3. 基线产物

| 产物 | 用途 |
|---|---|
| `case_stage_status_baseline.csv` | 6 个 Case 各阶段通过状态与耗时。 |
| `case_stage_status_compare.csv` | 与旧全量基线的共享 Case 阶段耗时对比。 |
| `t06_funnel_baseline.csv` | T06 Step1 / Step2 / Step3 漏斗与 Segment relation 状态。 |
| `t06_funnel_compare.csv` | 与旧全量基线的 T06 漏斗对比。 |
| `t06_rcsd_base_replacement_rate_baseline.csv` | 以 RCSD 为 Base 的 Road 级与里程级替换率。 |
| `t06_rcsd_base_replacement_rate_compare.csv` | 与旧全量基线的 RCSD Base 替换率对比。 |
| `baseline_summary.json` | 机器可读总索引，包含版本、路径、Case、漏斗、替换率、时间、QA 摘要和旧目录清理状态。 |
| `BASELINE_REFRESH_NOTE.md` | 本次全量基线刷新范围说明。 |
| `BASELINE_FREEZE.md` | 当前逻辑冻结说明。 |
| `BASELINE_USAGE.md` | 后续按模块复用该基线的边界说明。 |

## 4. 运行完成口径

| 指标 | 新全量基线 | 旧全量基线 | 变化 |
|---|---:|---:|---:|
| Case 总数 | 6 | 6 | 0 |
| 完成 Case | 6 | 6 | 0 |
| 通过 Case | 6 | 6 | 0 |
| 失败 Case | 0 | 0 | 0 |
| 阻塞 Case | 0 | 0 | 0 |
| T10 summary 耗时 s | 3840.283633 | 4203.419684 | -363.136051 |
| Case stage 累计耗时 s | 3811.207862 | 4179.433963 | -368.226101 |

## 5. T06 漏斗基线

| Case | T01 Segment | Step1 final fusion unit | Step2 replaceable | Step2 plan | Step2 ready plan | Step2 raw rejected | Step3 unit success | Step3 relation replaced | Step3 retained SWSD | failed relation | other relation | topology fail | surface fail | Step3 替换率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 2161 | 1229 | 924 | 1023 | 959 | 305 | 930 | 903 | 1253 | 0 | 5 | 22 | 5 | 41.7862% |
| `605415675` | 773 | 310 | 241 | 262 | 247 | 69 | 241 | 237 | 535 | 0 | 1 | 20 | 7 | 30.6598% |
| `609214532` | 1664 | 863 | 631 | 695 | 643 | 232 | 627 | 617 | 1046 | 0 | 1 | 24 | 8 | 37.0793% |
| `706247` | 748 | 435 | 271 | 313 | 274 | 164 | 276 | 259 | 485 | 1 | 3 | 12 | 1 | 34.6257% |
| `74155468` | 157 | 102 | 80 | 84 | 79 | 22 | 82 | 81 | 76 | 0 | 0 | 0 | 0 | 51.5924% |
| `991176` | 224 | 162 | 135 | 143 | 137 | 27 | 134 | 131 | 93 | 0 | 0 | 0 | 0 | 58.4821% |

与旧全量基线相比，Step3 relation replaced 合计净增 `+8`：`1885118 -2`、`605415675 +1`、`609214532 +4`、`706247 +1`、`74155468 +3`、`991176 +1`。`topology_connectivity_fail` 仅 `706247 +1`，`surface_topology_fail` 全部持平。

业务含义：

- `T01 Segment` 是 T06 的 SWSD Segment 输入分母。
- `Step1 final fusion unit` 是前置 relation 与基础锚定满足 T06 继续评估条件的 SWSD Segment。
- `Step2 replaceable` 是 T06 构建 RCSD Segment 后判定具备可替换候选的数量。
- `Step2 plan` 是 Step2 replacement plan 覆盖数量；`Step2 ready plan` 是可进入 Step3 执行的计划数量。
- `Step3 relation replaced` 是最终 Segment relation 中正式落地为 RCSD replacement 的 Segment 数量。
- `topology fail` 与 `surface fail` 是专项审计对象，不直接等同于替换失败数。

## 6. RCSD Base 替换率基线

正式统计以 T05 `rcsdroad_out.gpkg` 去重 RCSDRoad / 里程为分母，以 T06 汇总的 `final_replaceable_rcsd_road_ids` 去重集合为覆盖集合。`t06_rcsd_base_replacement_rate_baseline.csv` 同时保留 Step2 reference 覆盖口径，作为候选覆盖参考，不替代正式口径。

| Case | RCSD Road 总数 | 覆盖 RCSD Road | Road 级替换率 | RCSD 总里程 m | 覆盖里程 m | 里程级替换率 |
|---|---:|---:|---:|---:|---:|---:|
| `1885118` | 6435 | 4827 | 75.0117% | 641411.723 | 497584.139 | 77.5764% |
| `605415675` | 2029 | 1294 | 63.7753% | 197854.748 | 120439.686 | 60.8728% |
| `609214532` | 5034 | 3407 | 67.6798% | 501021.023 | 345943.997 | 69.0478% |
| `706247` | 1664 | 1145 | 68.8101% | 165801.405 | 95029.581 | 57.3153% |
| `74155468` | 518 | 276 | 53.2819% | 48807.587 | 23601.839 | 48.3569% |
| `991176` | 667 | 454 | 68.0660% | 55737.063 | 39970.912 | 71.7133% |
| `TOTAL` | 16347 | 11403 | 69.7559% | 1610633.549 | 1122570.154 | 69.6974% |

与旧全量基线相比，`TOTAL` 变化为：

- RCSD Road 分母 `16351 -> 16347`，减少 `4`。
- 覆盖 RCSD Road `11260 -> 11403`，增加 `143`。
- Road 级替换率 `68.8643% -> 69.7559%`，增加 `0.8916` 个百分点。
- 覆盖里程 `1107635.422m -> 1122570.154m`，增加 `14934.732m`。
- 里程级替换率 `68.7702% -> 69.6974%`，增加 `0.9272` 个百分点。

## 7. 605415675 人工审计收益

本节区分 T11 完整人工 Relation 审计消费结果与 T10 feedback 迭代结果。二者输入来源不同，不能混用为同一类“带人工审计”口径。

| 版本 | 归档位置 | 状态 | 关键结论 |
|---|---|---|---|
| 不带人工审计信息 | `case_variants/605415675_no_audit`，完整工件在 `e2e_full/cases/605415675` | `passed` | Step2 replaceable `241`，Step3 relation replaced `237`，RCSD Road 级替换率 `63.7753%`，里程级替换率 `60.8728%`。 |
| 完整 T11 人工审计 Relation 消费版 | `outputs/_work/t11_manual_rerun_605415675_t06_topology_buffer_supplement_20260701T115841Z` | 实验对比通过，用于收益评估 | 消费 `24` 条完整人工正向 Relation 后，Step2 replaceable `267`，Step3 relation replaced `267`，RCSD Road 级替换率 `66.4703%`，里程级替换率 `65.6936%`。 |
| T10 feedback 迭代版 | `case_variants/605415675_with_feedback_audit/full_run` | `failed` | 该版本 `upstream_feedback_relation_count=0`，不是完整人工 Relation 审计消费结果；`feedback_regression_guard_passed=False`，不作为优于无审计版的结果。 |

完整 T11 人工审计 Relation 消费版相对无审计基线的收益：

- Step1 final fusion unit `310 -> 341`，增加 `31`。
- manual anchor override Segment `0 -> 32`；manual evidence override Segment `0 -> 3`。
- Step2 replaceable `241 -> 267`，增加 `26`。
- Step2 ready replacement plan `247 -> 278`，增加 `31`。
- Step3 replacement unit success `241 -> 271`，增加 `30`。
- Step3 relation replaced `237 -> 267`，增加 `30`；retained SWSD `535 -> 505`，减少 `30`。
- RCSD Road 覆盖数 `1294 -> 1354`，增加 `60`；after 版分母因 T05 人工消费输出从 `2029` 变为 `2037`，Road 级替换率 `63.7753% -> 66.4703%`，增加 `2.6950` 个百分点。
- RCSD 覆盖里程 `120439.686m -> 129978.000m`，增加 `9538.314m`；里程级替换率 `60.8728% -> 65.6936%`，增加 `4.8209` 个百分点。
- Step3 attribution 口径下，未替换 RCSDRoad `628 -> 550`，减少 `78`；未替换 RCSDRoad 长度 `72389.073m -> 60029.887m`，减少 `12359.186m`。

T10 feedback 迭代版只作为负例保留：

- baseline replacement plan `257 -> 258`，但 replaced `238 -> 237`。
- 新增 replacement plan Segment：`1614138_97243413`、`97243413_97243414`。
- 移除 replacement plan / replaced Segment：`1642712_1614138`。
- 新增 replaced Segment：无。
- 因存在 replaced 回退，`feedback_regression_guard_passed=False`。

## 8. GIS / 拓扑 / 性能审计状态

- CRS 与坐标变换：T06 Step summaries 记录 CRS normalized to `EPSG:3857`；基线归档阶段不做坐标或几何变换。
- 拓扑一致性：T06 Step2 显式记录 buffer / component / junction gate，Step3 显式记录 topology connectivity audit；本基线不执行 silent fix。
- 几何语义可解释性：SWSD Segment 几何定义替换窗口，RCSD 几何用于候选选取、覆盖判断与保留输出，Step3 只消费 Step2 replacement plan。
- 审计可追溯性：`baseline_summary.json`、各阶段 `*_stage.json`、stdout log、T06 funnel、replacement plan、problem registry、visual check summary 和 Step3 relation 均可由 run root 定位。
- 性能可验证性：T10 summary、`case_stage_status_baseline.csv` 与 `case_stage_status_compare.csv` 保留总耗时、阶段耗时和共享 Case 对比。

## 9. 复用边界

- 如果只修改 T06，应复用本基线中每个 Case 的 `t01`、`t04`、`t05` handoff 输出，只重跑 T06 Step1/2 和 Step3 到新的输出目录，并与本基线对比。
- 如果只修改 T09，应复用本基线的 T06 输出，只重跑 T09 到新的输出目录。
- 如果修改 T01、T03、T04、T05、T07 或共享字段 / relation 契约，应刷新完整 T10 基线，不应把 downstream-only rerun 与该基线直接混比。
- T10 是运行编排和统计归档模块；T06 Step2 / Step3 是替换可行性、替换计划和最终替换关系的证据归属模块。
- T10 v1 Case runner 不调用 T08；本基线消费的是 Case package 中已经准备好的 SWSD / RCSD 外部输入切片。

## 10. 后续对比要求

后续对比必须同时给出：

- 对比基线目录和新 run root。
- 对比版本。
- T06 漏斗变化。
- 以 RCSD 为 Base 的 Road 级和里程级替换率变化。
- `topology_connectivity_fail` 与 `surface_topology_fail` 是否新增。
- 若只重跑后续模块，必须说明上游 handoff 来自本基线。
