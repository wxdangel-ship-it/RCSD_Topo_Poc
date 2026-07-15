# T10 统计基线补充材料

本文件分别记录当前有效的 T10 6 Case 日常回归基线，以及 T10、T10-Error、T10-Error-2 共 52 Case 的全量统计基线，并明确旧 `ce1cc72` 细分统计只作为历史快照。它是模块级补充材料，不替代 `01-06` 架构主结构，也不改变 T10 / T06 / T09 的接口契约。

## 1. 当前有效基线

### 1.1 T10 6 Case 日常回归基线

- 刷新日期：2026-07-15。
- 业务代码提交：`4b1c496`（契约同步提交为 `3c4d222`，随后以 `4b1c496` 修复生成道路未进入最终唯一归属刷新）。
- 基线目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_six_4b1c496_20260715_070100`
- T10 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_six_4b1c496_20260715_070100/t10/e2e_full`
- 指针文件：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_BASELINE.txt`
- Case 范围：`1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176`。
- 固定 worker 参数：`T10_T03_WORKERS=16`、`T10_T04_WORKERS=1`、`T10_T05_READONLY_WORKERS=1`。
- 运行状态：单次调用 `6/6 passed`、`60/60` 阶段通过，T11 为 audit-only 必经阶段；顶层 run manifest/summary 可代表六案完整运行。
- 视觉检查：`6/6 passed`，正式图层 CRS 为 `EPSG:3857`，缺失图层、端点缺路、SWSD advance-right 重叠异常均为 `0`，不执行 silent fix。
- 性能：六案 T06 Step1/2 + Step3 合计 `550.15s`；上一性能候选为 `551.07s`，比值 `0.9983`。本轮新增正式 advance-right Segment 后仍保持同量级性能。

该基线相对上一性能候选保留全部旧 Segment；逐案新增 relation 数量与新 T01 `advance_right` Segment 数量完全一致。除 `605415675` 外，所有共享 Segment 的 relation status/reason 均不变；`605415675` 有 2 个普通 Segment 从 `retained_swsd` 提升为 `replaced`，另有 2 个保留 Segment 被增强后的 surface 门禁显式标为 `retained_swsd_not_attached_side_road_only`，最终拓扑失败数仍为 `1`，与上一候选一致。这两行是新增审计暴露，不执行自动闭合或静默修复。

### 1.2 T10/T10-Error/T10-Error-2 共 52 Case 全量统计基线

- 刷新日期：2026-07-10。
- 刷新代码提交：`96b0ea5`（完整提交 `96b0ea518ba486db6d72afef79e637a0fad84e93`）。
- 基线目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735`
- T10 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735/t10/e2e_full`
- T10-Error 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735/t10_error/e2e_full`
- T10-Error-2 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735/t10_error2/e2e_full`
- 全量指针文件：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_ALL_CASES_BASELINE.txt`、`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_FULL_BASELINE.txt`
- T10 总状态：`6/6 passed`；T10-Error 总状态：`26/26 passed`；T10-Error-2 总状态：`20/20 passed`。
- 合计状态：`52/52 passed`，失败 Case 数为 `0`，`missing_artifacts=[]`。
- T10 首次全量运行在前两个 Case 完成后中断，其余四个 Case 使用 `--case-id` 写入同一基线根；机器汇总确认六个 Case 的 Case 级输出均完整。

> 兼容说明：该 `96b0ea5` 全量基线生成于 T10 将 T11 设为强制阶段之前。它继续作为 52 Case 的 T01-T06/T09 业务结果与性能对比基线，但不单独证明新工作流已完成 `T06 -> T11 -> T09`；新完成性验收必须同时检查新的 6 Case 基线或另一次全量运行中 passed 的 `t11` stage 与 T11 candidates/summary。

`96b0ea5` 全量基线替代旧登记基线 `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_ce1cc72_20260707_153701`。`ce1cc72` 及更早的 `3cd626d` 细分统计仅作为历史快照引用；日常测试输出不得覆盖基线目录。新的优化运行应写入独立 run root，再按范围选择 6 Case 或 52 Case 指针进行比较。

## 2. 基线产物

| 产物 | 用途 |
|---|---|
| `baseline_summary.json` | 机器可读总索引，记录版本、worker 参数、package 路径、Case 完成数、产物完整性和备注。 |
| `case_stage_status_baseline.csv` | 对应基线范围内各 Case 的阶段状态、耗时和核心输出存在性。 |
| `package_summary_baseline.csv` | 对应基线范围内各 package 的 Case 数、通过数和核心产物计数。 |
| `regression_validation_summary.json` | 6 Case 基线专有的上一候选对比、唯一归属、CRS、拓扑、几何语义和性能验收结论。 |
| `unreplaced_rcsd_attribution_distribution_baseline.csv` | 三套 package 的未替换 RCSD 归因分布快照。 |
| `qgis_update_manifest.csv` / `qgis_update_manifest.json` | QGIS 更新清单及机器可读索引。 |
| `<package>/e2e_full/t10_e2e_run_manifest.json` | 对应 package 的顶层运行输入、handoff 与输出清单；续跑 package 须结合 Case 级 manifest 判断全量完成性。 |
| `<package>/e2e_full/t10_e2e_run_summary.json` | 对应 package 的顶层单次运行状态与汇总；续跑 package 须结合根级基线汇总判断全量完成性。 |

`96b0ea5` 全量基线中的 T10 顶层 run manifest 与 run summary 都只记录最后一次四 Case 续跑，二者均为 `case_count=4`；其 T10 六 Case 完成性必须读取根级汇总和六个 Case 级 manifest。`4b1c496` 六案基线由单次调用完成，顶层 manifest/summary 可直接代表六案。T10-Error 与 T10-Error-2 的顶层 run manifest/summary 仍可直接代表各自单次全量运行。

当前基线根不包含旧 `ce1cc72` 文档列出的 `t06_funnel_baseline.csv`、`t06_rcsd_base_replacement_rate_baseline.csv`、`segment20_metric_summary.json` 等细分汇总；需要此类指标时必须从当前 package 的正式阶段产物重新计算，不能复用历史数字冒充当前结果。

## 3. 运行完成口径

| Package | 输入根 | Case | Passed | Non-passed | Segment GPKG | F-RCSD Road | F-RCSD Node | 未替换归因 GPKG |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| T10 | `/mnt/e/TestData/POC_Data/T10` | 6 | 6 | 0 | 6 | 6 | 6 | 6 |
| T10-Error | `/mnt/e/TestData/POC_Data/T10-Error` | 26 | 26 | 0 | 26 | 26 | 26 | 26 |
| T10-Error-2 | `/mnt/e/TestData/POC_Data/T10-Error-2` | 20 | 20 | 0 | 20 | 20 | 20 | 20 |
| **TOTAL** | - | **52** | **52** | **0** | **52** | **52** | **52** | **52** |

`baseline_summary.json` 记录 `missing_artifacts=[]`。以上表格是当前 `96b0ea5` 全量基线的正式汇总；T10 六案的日常回归完成性以 `4b1c496` 六案基线为准。后续章节中的 `ce1cc72` 细分指标均为历史快照，不属于当前统计。

## 4. 历史 `ce1cc72`：6 Case T06 漏斗快照（非当前基线）

以下表格来自旧登记根 `t10_all_cases_ce1cc72_20260707_153701`，只用于历史解释。当前 `96b0ea5` 基线未登记同口径汇总，使用前必须从当前阶段产物重新计算。

| Case | T01 Segment | Step1 final fusion unit | Step2 replaceable | Step2 plan | Step2 ready plan | Step2 raw rejected | Step3 unit success | Step3 relation replaced | Step3 retained SWSD | mixed / other relation | topology fail | surface fail | Step3 替换率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 2164 | 1256 | 978 | 1079 | 981 | 278 | 981 | 943 | 1202 | 19 | 16 | 5 | 43.5767% |
| `605415675` | 780 | 355 | 265 | 289 | 262 | 90 | 261 | 251 | 522 | 7 | 16 | 8 | 32.1795% |
| `609214532` | 1640 | 904 | 686 | 751 | 680 | 218 | 688 | 671 | 959 | 10 | 19 | 17 | 40.9146% |
| `706247` | 778 | 471 | 324 | 366 | 313 | 147 | 331 | 304 | 462 | 12 | 7 | 4 | 39.0746% |
| `74155468` | 156 | 118 | 92 | 96 | 89 | 26 | 92 | 89 | 65 | 2 | 1 | 2 | 57.0513% |
| `991176` | 214 | 163 | 138 | 147 | 137 | 25 | 137 | 134 | 79 | 1 | 2 | 2 | 62.6168% |
| `TOTAL` | 5732 | 3267 | 2483 | 2728 | 2462 | 784 | 2490 | 2392 | 3289 | 51 | 61 | 38 | - |

在该历史快照当时的对比中，Step3 relation replaced 合计净增 `+164`，retained SWSD 合计减少 `199`，Step3 replacement unit failure `9 -> 0`，topology fail `78 -> 61`；这些变化不代表当前 `96b0ea5` 基线。

## 5. 历史 `ce1cc72`：6 Case RCSD Base 替换率快照（非当前基线）

以下数值沿用旧 `ce1cc72` 快照。其统计口径是 T06 Step2 summary 中 `rcsd_road_coverage_stats_basis = unique_count_and_length_from_final_replaceable_rcsd_road_ids` 的去重 RCSDRoad / 里程口径；当前基线使用该指标时仍须重新计算。

| Case | RCSD Road 总数 | 覆盖 RCSD Road | Road 级替换率 | RCSD 总里程 m | 覆盖里程 m | 里程级替换率 |
|---|---:|---:|---:|---:|---:|---:|
| `1885118` | 6435 | 4868 | 75.6488% | 641411.723 | 504151.243 | 78.6003% |
| `605415675` | 2029 | 1314 | 64.7610% | 197854.748 | 128665.861 | 65.0305% |
| `609214532` | 5034 | 3411 | 67.7592% | 501021.023 | 347596.370 | 69.3776% |
| `706247` | 1664 | 1186 | 71.2740% | 165801.405 | 100289.094 | 60.4875% |
| `74155468` | 518 | 304 | 58.6873% | 48807.587 | 25433.613 | 52.1100% |
| `991176` | 667 | 439 | 65.8171% | 55737.063 | 38802.464 | 69.6170% |
| `TOTAL` | 16347 | 11522 | 70.4839% | 1610633.549 | 1144938.645 | 71.0862% |

旧 `ce1cc72` 快照相对其前序登记基线的 `TOTAL` 变化为：

- 覆盖 RCSD Road `11403 -> 11522`，增加 `119`。
- Road 级替换率 `69.7559% -> 70.4839%`，增加 `0.7280` 个百分点。
- 覆盖里程 `1122570.154m -> 1144938.645m`，增加 `22368.491m`。
- 里程级替换率 `69.6974% -> 71.0862%`，增加 `1.3888` 个百分点。

## 6. 历史 `ce1cc72`：Segment20 专项快照（非当前基线）

本节记录旧 `ce1cc72` 轮次的 T10-Error-2 Segment20 专项结果，原输出位于旧根 `segment20_error2/`。它仅用于解释当时的复杂路口内部替换、sibling subnode bridge、ordered junc connectivity、二度连通兜底和混合挂接收敛规则，不替代当前 `t10_error2/e2e_full` 的 20 Case 产物。

| 口径 | 该历史轮次最初审计输入 | `ce1cc72` Segment20 快照 | 变化 |
|---|---:|---:|---:|
| final F-RCSD source=1 road | 939 | 989 | +50 |
| final F-RCSD source=2 road | 963 | 936 | -27 |
| Step3 relation replaced | 284 | 309 | +25 |
| Step3 relation mixed | 9 | 6 | -3 |
| Step3 relation retained_swsd | 671 | 657 | -14 |
| 未替换 RCSDRoad | 1317 | 1271 | -46 |
| 未替换 RCSDRoad 长度 m | 161313.739 | 157245.041 | -4068.698 |

相对该历史轮次之前的 `visual_conflict_mixed_rollback` 中间结果，Segment20 快照 `mixed` 持平为 `6`，source=1 road `988 -> 989`，未替换 RCSDRoad `1272 -> 1271`。

## 7. 历史 `ce1cc72`：目标用例收敛状态（非当前基线）

`1010443_1026904` 在旧 `ce1cc72` 轮次的最终验证中通过：

- `1010545_1010444` 不再构建为 Segment。
- `1010443_1010444` 为 `replaced`。
- `605947437` 和 `992190` 在 `removed_swsd_roads` 中以 `replaced_swsd_segment` 移除。
- `5387639738007700`、`5387639738007702`、`5387639738007709`、`5396080088450680` 在最终 `t06_frcsd_road.gpkg` 中为 `source=1`。
- `1010443_1010444` 的 topology connectivity audit 为 `pass`。

## 8. 历史 `ce1cc72`：GIS / 拓扑 / 性能审计状态（非当前基线）

以下状态来自旧 `ce1cc72` 快照；当前 `96b0ea5` 基线的完成性以 `baseline_summary.json` 和 `case_stage_status_baseline.csv` 为统一入口。T10 还必须读取六个 Case 级 `t10_e2e_case_run_manifest.json`，其顶层 run manifest / summary 只代表最后四 Case 续跑；T10-Error 与 T10-Error-2 的顶层 run manifest / summary 才能分别代表各自单次全量运行。

- CRS 与坐标变换：该历史快照的 6 Case 与 Segment20 T06 visual summary 均通过；模块 summary 记录 CRS normalized to `EPSG:3857`。
- 拓扑一致性：该历史快照的 T06 Step2 / Step3 显式记录 buffer / component / ordered junc / special junction / bridge fallback / topology connectivity audit，且不执行 silent fix。
- 几何语义可解释性：该历史快照以 SWSD Segment 几何定义替换窗口，RCSD 几何用于候选选取、覆盖判断与保留输出，Step3 只消费 Step2 replacement plan。
- 审计可追溯性：旧根中的 `baseline_summary.json`、各阶段 `*_stage.json`、stdout log、T06 funnel、replacement plan、problem registry、visual check summary、Step3 relation 与 Segment20 summary 构成该历史快照的证据链。
- 性能可验证性：旧根中的 T10 summary、`case_stage_status_baseline.csv` 与 Segment20 run summary 保留该历史快照的总耗时、阶段耗时和共享 Case 对比。

## 9. 复用边界

- 如果只修改 T06，日常六案回归优先复用 `LATEST_T10_BASELINE.txt` 指向基线中的 `t01`、`t04`、`t05` handoff，只重跑 T06 Step1/2 和 Step3 到新的输出目录；需要 52 Case 统计时再使用全量指针。
- 如果只修改 T09，应按目标范围复用六案或全量基线的 T06 输出，只重跑 T09 到新的输出目录。
- 如果修改 T01、T03、T04、T05、T07 或共享字段 / relation 契约，应至少刷新完整 T10 六案基线；在宣布 52 Case 全量无回退前，还必须刷新或完整重放 T10-Error 与 T10-Error-2，不应把 downstream-only rerun 与上游已变化的基线直接混比。
- 全量统计基线同时覆盖 T10 6 Case、T10-Error 26 Case 与 T10-Error-2 20 Case；三者是独立 package，不可相互替代统计口径。六案日常回归基线也不得用于声称 52 Case 全量已通过。
- T10 是运行编排和统计归档模块；T06 Step2 / Step3 是替换可行性、替换计划和最终替换关系的证据归属模块。
- T10 v1 Case runner 不调用 T08；本基线消费的是 Case package 中已经准备好的 SWSD / RCSD 外部输入切片。

## 10. 后续对比要求

后续对比必须同时给出：

- 对比基线目录和新 run root，并说明使用的是六案指针还是 52 Case 全量指针。
- 对比代码版本。
- `case_stage_status_baseline.csv` 与 `package_summary_baseline.csv` 中的完成状态和核心产物变化。
- 如需 T06 漏斗或以 RCSD 为 Base 的 Road 级 / 里程级替换率，必须从所选当前基线的 package 阶段产物重新计算，并同时给出计算脚本、口径和输出路径；不得直接引用第 4-6 节历史数字。
- `topology_connectivity_fail` 与 `surface_topology_fail` 是否新增。
- mixed relation 变化，尤其是 `replaced+retained_swsd` 是否属于 `retained_swsd_topology_supplement` 旧口径。
- 若只重跑后续模块，必须说明上游 handoff 来自六案或全量基线的具体 package / Case 路径。
