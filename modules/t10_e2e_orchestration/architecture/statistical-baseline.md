# T10 统计基线补充材料

本文件记录当前有效的 T10 全量 Case 统计基线，以及本轮同步登记的 T10-Error-2 Segment20 专项回归基线。它是模块级补充材料，不替代 `01-06` 架构主结构，也不改变 T10 / T06 / T09 的接口契约。

## 1. 当前有效基线

- 刷新日期：2026-07-07。
- 刷新代码提交：`ce1cc72`。
- 基线目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_ce1cc72_20260707_153701`
- 6 Case 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_ce1cc72_20260707_153701/e2e_full`
- Segment20 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_ce1cc72_20260707_153701/segment20_error2`
- 当前指针文件：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_ALL_CASES_BASELINE.txt`、`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_BASELINE.txt`、`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_ERROR2_SEGMENT20_BASELINE.txt`
- 执行工作树：`/mnt/c/Users/admin/.codex/worktrees/t06-semantic-junction-bridge-20260707/RCSD_Topo_Poc`
- 6 Case 执行入口：`scripts/t10_run_e2e_cases.sh --package-dir /mnt/e/TestData/POC_Data/T10`
- Segment20 执行入口：`scripts/t10_run_e2e_cases.sh --package-dir /mnt/e/TestData/POC_Data/T10-Error-2`
- 6 Case 范围：`1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176`。
- Segment20 范围：`/mnt/e/TestData/POC_Data/T10-Error-2` 下 20 个 Segment case。
- 6 Case T10 总状态：`passed`，6 个 Case 全部完成，失败 Case 数为 0。
- Segment20 T10 总状态：`passed`，20 个 Case 全部完成，失败 Case 数为 0。
- 6 Case T10 summary 耗时：`3326.831330s`；case stage 累计耗时：`3296.602980s`。
- Segment20 T10 summary 耗时：`1982.421408s`。

本基线替代旧登记基线 `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_3cd626d_20260701_214807`。旧目录保留为历史对照；日常测试输出不得覆盖当前基线目录。新的优化运行应写入独立 run root，再与本目录下的 CSV / JSON 进行比较。

## 2. 基线产物

| 产物 | 用途 |
|---|---|
| `case_stage_status_baseline.csv` | 6 个 Case 各阶段通过状态与耗时。 |
| `case_stage_status_compare.csv` | 与旧登记基线的共享 Case 阶段耗时对比。 |
| `t06_funnel_baseline.csv` | 6 Case T06 Step1 / Step2 / Step3 漏斗与 Segment relation 状态。 |
| `t06_funnel_compare.csv` | 与旧登记基线的 T06 漏斗对比。 |
| `t06_rcsd_base_replacement_rate_baseline.csv` | 6 Case 以 RCSD 为 Base 的 Road 级与里程级替换率。 |
| `t06_rcsd_base_replacement_rate_compare.csv` | 与旧登记基线的 RCSD Base 替换率对比。 |
| `segment20_t06_funnel_baseline.csv` | Segment20 T06 漏斗与 Segment relation 状态。 |
| `segment20_t06_funnel_compare.csv` | Segment20 相对本轮最初审计输入的 T06 漏斗对比。 |
| `segment20_t06_rcsd_base_replacement_rate_baseline.csv` | Segment20 以 RCSD 为 Base 的 Road 级与里程级替换率。 |
| `segment20_t06_rcsd_base_replacement_rate_compare.csv` | Segment20 相对本轮最初审计输入的 RCSD Base 替换率对比。 |
| `segment20_metric_summary.json` | Segment20 source、mixed relation、未替换 RCSDRoad 汇总。 |
| `baseline_summary.json` | 机器可读总索引，包含版本、路径、Case、漏斗、替换率、Segment20、QA 和性能摘要。 |
| `BASELINE_REFRESH_NOTE.md` | 本次基线刷新范围说明。 |
| `BASELINE_FREEZE.md` | 当前逻辑冻结说明。 |
| `BASELINE_USAGE.md` | 后续按模块复用该基线的边界说明。 |

## 3. 运行完成口径

| 指标 | 新基线 | 旧登记基线 | 变化 |
|---|---:|---:|---:|
| 6 Case 总数 | 6 | 6 | 0 |
| 6 Case 通过 | 6 | 6 | 0 |
| 6 Case 失败 | 0 | 0 | 0 |
| Segment20 总数 | 20 | 未登记 | - |
| Segment20 通过 | 20 | 未登记 | - |
| Segment20 失败 | 0 | 未登记 | - |
| 6 Case T10 summary 耗时 s | 3326.831330 | 3840.283633 | -513.452303 |
| 6 Case stage 累计耗时 s | 3296.602980 | 3811.207862 | -514.604882 |

## 4. 6 Case T06 漏斗基线

| Case | T01 Segment | Step1 final fusion unit | Step2 replaceable | Step2 plan | Step2 ready plan | Step2 raw rejected | Step3 unit success | Step3 relation replaced | Step3 retained SWSD | mixed / other relation | topology fail | surface fail | Step3 替换率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 2164 | 1256 | 978 | 1079 | 981 | 278 | 981 | 943 | 1202 | 19 | 16 | 5 | 43.5767% |
| `605415675` | 780 | 355 | 265 | 289 | 262 | 90 | 261 | 251 | 522 | 7 | 16 | 8 | 32.1795% |
| `609214532` | 1640 | 904 | 686 | 751 | 680 | 218 | 688 | 671 | 959 | 10 | 19 | 17 | 40.9146% |
| `706247` | 778 | 471 | 324 | 366 | 313 | 147 | 331 | 304 | 462 | 12 | 7 | 4 | 39.0746% |
| `74155468` | 156 | 118 | 92 | 96 | 89 | 26 | 92 | 89 | 65 | 2 | 1 | 2 | 57.0513% |
| `991176` | 214 | 163 | 138 | 147 | 137 | 25 | 137 | 134 | 79 | 1 | 2 | 2 | 62.6168% |
| `TOTAL` | 5732 | 3267 | 2483 | 2728 | 2462 | 784 | 2490 | 2392 | 3289 | 51 | 61 | 38 | - |

相对旧登记基线，Step3 relation replaced 合计净增 `+164`，retained SWSD 合计减少 `199`，Step3 replacement unit failure `9 -> 0`，topology fail `78 -> 61`。

## 5. 6 Case RCSD Base 替换率基线

正式统计以 T06 Step2 summary 中 `rcsd_road_coverage_stats_basis = unique_count_and_length_from_final_replaceable_rcsd_road_ids` 的去重 RCSDRoad / 里程口径为准。

| Case | RCSD Road 总数 | 覆盖 RCSD Road | Road 级替换率 | RCSD 总里程 m | 覆盖里程 m | 里程级替换率 |
|---|---:|---:|---:|---:|---:|---:|
| `1885118` | 6435 | 4868 | 75.6488% | 641411.723 | 504151.243 | 78.6003% |
| `605415675` | 2029 | 1314 | 64.7610% | 197854.748 | 128665.861 | 65.0305% |
| `609214532` | 5034 | 3411 | 67.7592% | 501021.023 | 347596.370 | 69.3776% |
| `706247` | 1664 | 1186 | 71.2740% | 165801.405 | 100289.094 | 60.4875% |
| `74155468` | 518 | 304 | 58.6873% | 48807.587 | 25433.613 | 52.1100% |
| `991176` | 667 | 439 | 65.8171% | 55737.063 | 38802.464 | 69.6170% |
| `TOTAL` | 16347 | 11522 | 70.4839% | 1610633.549 | 1144938.645 | 71.0862% |

与旧登记基线相比，`TOTAL` 变化为：

- 覆盖 RCSD Road `11403 -> 11522`，增加 `119`。
- Road 级替换率 `69.7559% -> 70.4839%`，增加 `0.7280` 个百分点。
- 覆盖里程 `1122570.154m -> 1144938.645m`，增加 `22368.491m`。
- 里程级替换率 `69.6974% -> 71.0862%`，增加 `1.3888` 个百分点。

## 6. Segment20 专项基线

Segment20 是本轮 T10-Error-2 质量闭环的专项回归基线，输出已复制到 `segment20_error2/`。该基线用于后续验证本轮涉及的复杂路口内部替换、sibling subnode bridge、ordered junc connectivity、二度连通兜底和混合挂接收敛规则。

| 口径 | 本轮最初审计输入 | 当前 Segment20 基线 | 变化 |
|---|---:|---:|---:|
| final F-RCSD source=1 road | 939 | 989 | +50 |
| final F-RCSD source=2 road | 963 | 936 | -27 |
| Step3 relation replaced | 284 | 309 | +25 |
| Step3 relation mixed | 9 | 6 | -3 |
| Step3 relation retained_swsd | 671 | 657 | -14 |
| 未替换 RCSDRoad | 1317 | 1271 | -46 |
| 未替换 RCSDRoad 长度 m | 161313.739 | 157245.041 | -4068.698 |

相对上一轮 `visual_conflict_mixed_rollback` 中间结果，当前 Segment20 基线 `mixed` 持平为 `6`，source=1 road `988 -> 989`，未替换 RCSDRoad `1272 -> 1271`。

## 7. 目标用例收敛状态

`1010443_1026904` 在本轮最终验证中通过：

- `1010545_1010444` 不再构建为 Segment。
- `1010443_1010444` 为 `replaced`。
- `605947437` 和 `992190` 在 `removed_swsd_roads` 中以 `replaced_swsd_segment` 移除。
- `5387639738007700`、`5387639738007702`、`5387639738007709`、`5396080088450680` 在最终 `t06_frcsd_road.gpkg` 中为 `source=1`。
- `1010443_1010444` 的 topology connectivity audit 为 `pass`。

## 8. GIS / 拓扑 / 性能审计状态

- CRS 与坐标变换：6 Case 与 Segment20 的 T06 visual summary 均通过；模块 summary 记录 CRS normalized to `EPSG:3857`。
- 拓扑一致性：T06 Step2 / Step3 显式记录 buffer / component / ordered junc / special junction / bridge fallback / topology connectivity audit；本基线不执行 silent fix。
- 几何语义可解释性：SWSD Segment 几何定义替换窗口，RCSD 几何用于候选选取、覆盖判断与保留输出，Step3 只消费 Step2 replacement plan。
- 审计可追溯性：`baseline_summary.json`、各阶段 `*_stage.json`、stdout log、T06 funnel、replacement plan、problem registry、visual check summary、Step3 relation 与 Segment20 summary 均可由基线目录定位。
- 性能可验证性：T10 summary、`case_stage_status_baseline.csv` 与 Segment20 run summary 保留总耗时、阶段耗时和共享 Case 对比。

## 9. 复用边界

- 如果只修改 T06，应复用本基线中每个 Case 的 `t01`、`t04`、`t05` handoff 输出，只重跑 T06 Step1/2 和 Step3 到新的输出目录，并与本基线对比。
- 如果只修改 T09，应复用本基线的 T06 输出，只重跑 T09 到新的输出目录。
- 如果修改 T01、T03、T04、T05、T07 或共享字段 / relation 契约，应刷新完整 T10 基线，不应把 downstream-only rerun 与该基线直接混比。
- Segment20 专项基线只代表 T10-Error-2 本轮 20 个 Segment case，不替代 `/mnt/e/TestData/POC_Data/T10` 的 6 Case 主基线。
- T10 是运行编排和统计归档模块；T06 Step2 / Step3 是替换可行性、替换计划和最终替换关系的证据归属模块。
- T10 v1 Case runner 不调用 T08；本基线消费的是 Case package 中已经准备好的 SWSD / RCSD 外部输入切片。

## 10. 后续对比要求

后续对比必须同时给出：

- 对比基线目录和新 run root。
- 对比代码版本。
- T06 漏斗变化。
- 以 RCSD 为 Base 的 Road 级和里程级替换率变化。
- `topology_connectivity_fail` 与 `surface_topology_fail` 是否新增。
- mixed relation 变化，尤其是 `replaced+retained_swsd` 是否属于 `retained_swsd_topology_supplement` 旧口径。
- 若只重跑后续模块，必须说明上游 handoff 来自本基线。
