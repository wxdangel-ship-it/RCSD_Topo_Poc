# T10 统计基线补充材料

本文件记录当前有效的 T10 全量 Case 统计基线。它是模块级补充材料，不替代 `01-06` 架构主结构，也不改变 T10 / T06 / T09 的接口契约。

## 1. 当前有效基线

- 刷新日期：2026-06-30。
- 版本：`c5085f0`，注册时 `main = origin/main = c5085f0`。
- 基线目录：`/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345`
- 运行根目录：`/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345/e2e_full`
- 当前指针文件：`/mnt/e/work/rcsd_topo_poc/outputs/baselines/LATEST_T10_ALL_CASES_BASELINE.txt`、`/mnt/e/work/rcsd_topo_poc/outputs/baselines/LATEST_T10_BASELINE.txt`
- 执行工作区：`/mnt/e/work/rcsd_topo_poc`
- 执行入口：`scripts/t10_run_e2e_cases.sh --package-dir /mnt/e/TestData/POC_Data/T10`
- Case package 根目录：`/mnt/e/TestData/POC_Data/T10`
- Case 范围：`1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176`。
- T10 总状态：`passed`，6 个 Case 全部完成，失败 Case 数为 0。
- T10 summary 耗时：`4203.419684s`。
- shell `time` 观测：`real 3922.38s`、`user 1117.23s`、`sys 301.72s`。
- 上游反馈统计：Segment `701`，pair-anchor endpoint cluster `866`，side-group candidate `24`，side-group endpoint candidate `37`，relation `0`。

本基线替代上一版四 Case 基线 `/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_4cases_08aa76c_20260628_155754`。本轮是从 `/mnt/e/TestData/POC_Data/T10` 全量端到端重跑，不复用旧基线上游 handoff。日常测试输出不得覆盖该目录；新的优化运行应写入独立 run root，再与本目录下的 CSV / JSON 进行比较。

## 2. 旧基线处理

以下旧目录已取消当前有效身份，并已从本地 `outputs/baselines` 清理：

- `/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_4cases_08aa76c_20260628_155754`

旧指针 `LATEST_T10_4CASES_BASELINE.txt` 不再作为有效入口保留。后续自动化或人工审计必须优先读取：

- `/mnt/e/work/rcsd_topo_poc/outputs/baselines/LATEST_T10_ALL_CASES_BASELINE.txt`
- `/mnt/e/work/rcsd_topo_poc/outputs/baselines/LATEST_T10_BASELINE.txt`

## 3. 基线产物

| 产物 | 用途 |
|---|---|
| `case_stage_status_baseline.csv` | 6 个 Case 各阶段通过状态与耗时。 |
| `case_stage_status_compare.csv` | 与上一版四 Case 基线的共享 Case 阶段耗时对比，并标记新增 Case。 |
| `t06_funnel_baseline.csv` | T06 Step1 / Step2 / Step3 漏斗与 Segment relation 状态。 |
| `t06_funnel_compare.csv` | 与上一版四 Case 基线的 T06 漏斗对比，并标记新增 Case。 |
| `t06_rcsd_base_replacement_rate_baseline.csv` | 以 RCSD 为 Base 的 Road 级与里程级替换率。 |
| `t06_rcsd_base_replacement_rate_compare.csv` | 与上一版四 Case 基线的 RCSD Base 替换率对比，并标记新增 Case。 |
| `baseline_summary.json` | 机器可读总索引，包含版本、路径、Case、漏斗、替换率、时间与 QA 摘要。 |
| `BASELINE_REFRESH_NOTE.md` | 本次从旧四 Case 基线到全量 Case 基线的刷新范围说明。 |
| `BASELINE_FREEZE.md` | 当前逻辑冻结说明。 |
| `BASELINE_USAGE.md` | 后续按模块复用该基线的边界说明。 |

## 4. 运行完成口径

| 指标 | 新全量基线 | 上一版四 Case 基线 |
|---|---:|---:|
| Case 总数 | 6 | 4 |
| 完成 Case | 6 | 4 |
| 通过 Case | 6 | 4 |
| 失败 Case | 0 | 0 |
| 阻塞 Case | 0 | 0 |
| T10 summary 耗时 s | 4203.419684 | 3805.168769 |

共享 4 个 Case 的阶段累计耗时从 `3780.804686s` 降到 `3087.225324s`，减少 `693.579362s`。新增 Case `605415675`、`706247` 的阶段累计耗时分别为 `526.604348s`、`565.604291s`。

## 5. T06 漏斗基线

| Case | T01 Segment | Step1 final fusion unit | Step2 replaceable | Step2 plan | Step2 ready plan | Step2 raw rejected | Step3 replaced | Step3 retained SWSD | other relation | topology fail | surface fail | Step3 替换率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 2161 | 1229 | 925 | 1024 | 961 | 304 | 905 | 1251 | 5 | 22 | 5 | 41.8788% |
| `605415675` | 773 | 310 | 239 | 260 | 246 | 71 | 236 | 536 | 1 | 20 | 7 | 30.5304% |
| `609214532` | 1664 | 863 | 622 | 685 | 639 | 241 | 613 | 1050 | 1 | 24 | 8 | 36.8389% |
| `706247` | 748 | 435 | 271 | 311 | 272 | 164 | 258 | 487 | 3 | 11 | 1 | 34.4920% |
| `74155468` | 157 | 102 | 77 | 81 | 76 | 25 | 78 | 79 | 0 | 0 | 0 | 49.6815% |
| `991176` | 224 | 162 | 134 | 142 | 136 | 28 | 130 | 94 | 0 | 0 | 0 | 58.0357% |

与上一版四 Case 基线相比，共享 Case 的 `Step2 replaceable` 均未回退：`1885118 +7`、`609214532 +2`、`74155468 0`、`991176 0`。共享 Case 的 `Step3 replaced` 也未回退：`1885118 +9`、`609214532 +9`、`74155468 0`、`991176 0`。共享 Case 的 `surface fail` 均下降或持平。

业务含义：

- `T01 Segment` 是 T06 的 SWSD Segment 输入分母。
- `Step1 final fusion unit` 是前置 relation 与基础锚定满足 T06 继续评估条件的 SWSD Segment。
- `Step2 replaceable` 是 T06 构建 RCSD Segment 后判定具备可替换候选的数量。
- `Step2 plan` 是 Step2 replacement plan 覆盖数量；`Step2 ready plan` 是可进入 Step3 执行的计划数量。
- `Step3 replaced` 是最终 Segment relation 中正式落地为 RCSD replacement 的 Segment 数量。
- `Step3 retained SWSD` 是最终仍保留 SWSD 承载的 Segment 数量。
- `topology fail` 与 `surface fail` 是专项审计对象，不直接等同于替换失败数。

## 6. RCSD Base 替换率基线

正式统计以 T05 `rcsdroad_out.gpkg` 去重 RCSDRoad / 里程为分母，以 T06 汇总的 `final_replaceable_rcsd_road_ids` 去重集合为覆盖集合。`t06_rcsd_base_replacement_rate_baseline.csv` 同时保留 Step2 reference 覆盖口径，作为候选覆盖参考，不替代正式口径。

| Case | RCSD Road 总数 | 覆盖 RCSD Road | Road 级覆盖率 | RCSD 总里程 m | 覆盖里程 m | 里程级覆盖率 |
|---|---:|---:|---:|---:|---:|---:|
| `1885118` | 6437 | 4805 | 74.6466% | 641411.723 | 496645.471 | 77.4301% |
| `605415675` | 2030 | 1274 | 62.7586% | 197854.748 | 117986.595 | 59.6329% |
| `609214532` | 5034 | 3317 | 65.8919% | 501021.023 | 335303.729 | 66.9241% |
| `706247` | 1664 | 1142 | 68.6298% | 165801.405 | 94984.199 | 57.2879% |
| `74155468` | 518 | 271 | 52.3166% | 48807.587 | 23092.469 | 47.3133% |
| `991176` | 668 | 451 | 67.5150% | 55737.063 | 39622.959 | 71.0891% |
| `TOTAL` | 16351 | 11260 | 68.8643% | 1610633.549 | 1107635.422 | 68.7702% |

上一版四 Case 基线的 `TOTAL` 为 Road 级 `69.8349%`、里程级 `71.3841%`。该差异不能直接按回退理解，因为新基线从 4 个 Case 扩展到 6 个 Case，新增 Case 的 RCSD 覆盖率低于旧四 Case 平均值。共享 4 个 Case 的详细差异以 `t06_rcsd_base_replacement_rate_compare.csv` 为准。

## 7. GIS / 拓扑 / 性能审计状态

- CRS 与坐标变换：T10 visual summary 记录检查图层使用 `EPSG:3857`；基线注册阶段不做坐标或几何变换。
- 拓扑一致性：T06 Step2 显式记录 buffer / component / junction gate，Step3 显式记录 topology connectivity audit；本基线不执行 silent fix。
- 几何语义可解释性：SWSD Segment 几何定义替换窗口，RCSD 几何用于候选选取、覆盖判断与保留输出，Step3 只消费 Step2 replacement plan。
- 审计可追溯性：`baseline_summary.json`、各阶段 `*_stage.json`、stdout log、T06 funnel、replacement plan、problem registry、visual check summary 和 Step3 relation 均可由 run root 定位。
- 性能可验证性：T10 summary、`case_stage_status_baseline.csv` 与 `case_stage_status_compare.csv` 保留总耗时、阶段耗时和共享 Case 对比。

## 8. 复用边界

- 如果只修改 T06，应复用本基线中每个 Case 的 `t01`、`t04`、`t05` handoff 输出，只重跑 T06 Step1/2 和 Step3 到新的输出目录，并与本基线对比。
- 如果只修改 T09，应复用本基线的 T06 输出，只重跑 T09 到新的输出目录。
- 如果修改 T01、T03、T04、T05、T07 或共享字段 / relation 契约，应刷新完整 T10 基线，不应把 downstream-only rerun 与该基线直接混比。
- T10 是运行编排和统计归档模块；T06 Step2 / Step3 是替换可行性、替换计划和最终替换关系的证据归属模块。
- T10 v1 Case runner 不调用 T08；本基线消费的是 Case package 中已经准备好的 SWSD / RCSD 外部输入切片。

## 9. 后续对比要求

后续对比必须同时给出：

- 对比基线目录和新 run root。
- 对比版本。
- T06 漏斗变化。
- 以 RCSD 为 Base 的 Road 级和里程级替换率变化。
- `topology_connectivity_fail` 与 `surface_topology_fail` 是否新增。
- 若只重跑后续模块，必须说明上游 handoff 来自本基线。
