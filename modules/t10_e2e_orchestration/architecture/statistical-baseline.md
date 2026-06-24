# T10 统计基线补充材料

本文件记录已确认的 T10 四 Case 端到端统计基线。它是模块级补充材料，不替代 `01-06` 架构主结构，也不改变 T10 / T06 / T09 的接口契约。

## 1. 基线定位

- 冻结日期：2026-06-24。
- 版本：`a2d9a58`，冻结时 `HEAD = origin/main = a2d9a58`。
- 基线目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_a2d9a58_20260624_174615`
- 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_a2d9a58_20260624_174615/e2e_full`
- 运行入口：`scripts/t10_run_e2e_cases.sh`
- Case package 根目录：`/mnt/e/TestData/POC_Data/T10`
- Case 范围：`1885118`、`609214532`、`74155468`、`991176`。
- T10 总状态：`passed`，4 个 Case 全部完成，失败 Case 数为 0。
- 总耗时：`4140.695845s`。

该基线用于后续优化对比。日常测试输出不得覆盖该目录；新的优化运行应写入独立 run root，再与本目录下的 CSV / JSON 进行比较。

## 2. 基线产物

| 产物 | 用途 |
|---|---|
| `case_stage_status_baseline.csv` | 四个 Case 各阶段通过状态与耗时。 |
| `t06_funnel_baseline.csv` | T06 Step1 / Step2 / Step3 漏斗与 Segment relation 状态。 |
| `t06_rcsd_base_replacement_rate_baseline.csv` | 以 RCSD 为 Base 的 Road 级与里程级可替换率。 |
| `baseline_summary.json` | 机器可读总索引，包含版本、路径、Case、漏斗和替换率摘要。 |
| `BASELINE_FREEZE.md` | 逻辑冻结说明。 |
| `BASELINE_USAGE.md` | 后续按模块复用该基线的边界说明。 |

## 3. T06 漏斗基线

| Case | T01 Segment | Step1 final fusion unit | Step2 replaceable | Step2 ready plan | Step2 raw rejected | Step3 replaced | Step3 retained SWSD | mixed relation | Step3 替换率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 2189 | 1216 | 900 | 797 | 316 | 786 | 1401 | 2 | 35.9068% |
| `609214532` | 1683 | 850 | 615 | 496 | 235 | 510 | 1172 | 1 | 30.3030% |
| `74155468` | 162 | 102 | 77 | 69 | 25 | 69 | 93 | 0 | 42.5926% |
| `991176` | 225 | 161 | 133 | 123 | 28 | 118 | 107 | 0 | 52.4444% |

业务含义：

- `T01 Segment` 是 T06 的 SWSD Segment 输入分母。
- `Step1 final fusion unit` 是前置 relation 与基础锚定满足 T06 继续评估条件的 SWSD Segment。
- `Step2 replaceable` 是 T06 构建 RCSD Segment 后判定具备可替换候选的数量。
- `Step2 ready plan` 是 Step2 replacement plan 中可进入 Step3 执行的计划数量。
- `Step3 replaced` 是最终 Segment relation 中正式落地为 RCSD replacement 的 Segment 数量。
- `Step3 retained SWSD` 是最终仍保留 SWSD 承载的 Segment 数量。
- `mixed relation` 当前只允许作为专项审计对象，不应被当作常规替换成功口径。

## 4. RCSD Base 替换率基线

以下口径来自 T06 Step2 summary 中的 `replaceable_rcsd_road_unique_*` 字段，表达“RCSD Road 在当前 T06 判定下可被替换计划覆盖的唯一 Road / 里程比例”。该口径不把 Step3 生成的 split、补拓扑或挂接 Road 反向混入原始 RCSD 分母。

| Case | RCSD Road 总数 | 可替换 RCSD Road | Road 级替换率 | RCSD 总里程 m | 可替换里程 m | 里程级替换率 |
|---|---:|---:|---:|---:|---:|---:|
| `1885118` | 6432 | 4788 | 74.4403% | 641411.723 | 492625.995 | 76.8034% |
| `609214532` | 5031 | 3325 | 66.0902% | 501021.023 | 335205.114 | 66.9044% |
| `74155468` | 518 | 272 | 52.5097% | 48807.587 | 23104.623 | 47.3382% |
| `991176` | 668 | 451 | 67.5150% | 55737.063 | 39192.318 | 70.3164% |
| `TOTAL` | 12649 | 8836 | 69.8553% | 1246977.396 | 890128.050 | 71.3829% |

## 5. 复用边界

- 如果只修改 T06，应复用本基线中每个 Case 的 `t01`、`t04`、`t05` handoff 输出，只重跑 T06 Step1/2 和 Step3 到新的输出目录。
- 如果只修改 T09，应复用本基线的 T06 输出，只重跑 T09 到新的输出目录。
- 如果修改 T01、T03、T04、T05、T07 或共享字段 / relation 契约，应刷新完整 T10 基线，不应把 downstream-only rerun 与该基线直接混比。
- T10 是运行编排和统计归档模块；T06 Step2 / Step3 是替换可行性、替换计划和最终替换关系的证据归属模块。
- T10 v1 Case runner 不调用 T08；本基线消费的是 Case package 中已经准备好的 SWSD / RCSD 外部输入切片。

## 6. 审计要求

后续对比必须同时给出：

- 对比基线目录和新 run root。
- 对比版本。
- T06 漏斗变化。
- 以 RCSD 为 Base 的 Road 级和里程级替换率变化。
- `topology_connectivity_fail` 与 `surface_topology_fail` 是否新增。
- 若只重跑后续模块，必须说明上游 handoff 来自本基线。
