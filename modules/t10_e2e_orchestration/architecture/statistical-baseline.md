# T10 统计基线补充材料

本文件记录当前有效的 T10 四 Case 端到端统计基线。它是模块级补充材料，不替代 `01-06` 架构主结构，也不改变 T10 / T06 / T09 的接口契约。

## 1. 当前有效基线

- 冻结日期：2026-06-25。
- 版本：`72b27f2`，冻结时 `origin/main = 72b27f2`。
- 基线目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_72b27f2_20260625_182356`
- 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_72b27f2_20260625_182356/e2e_full`
- 执行 worktree：`/mnt/e/Work/RCSD_Topo_Poc_clean_72b27f2`
- 运行入口：`scripts/t10_run_e2e_cases.sh`
- Case package 根目录：`/mnt/e/TestData/POC_Data/T10`
- Case 范围：`1885118`、`609214532`、`74155468`、`991176`。
- T10 总状态：`passed`，4 个 Case 全部完成，失败 Case 数为 0。
- 总耗时：`3692.85296s`。
- 上游反馈统计：Segment `541`，pair-anchor endpoint cluster `636`，side-group candidate `15`，side-group endpoint candidate `24`，relation `0`。

本基线使用干净 detached worktree 执行，避免主工作区后续分支切换或未提交改动影响统计口径。日常测试输出不得覆盖该目录；新的优化运行应写入独立 run root，再与本目录下的 CSV / JSON 进行比较。

## 2. 旧基线处理

以下历史基线已取消当前有效身份，仅保留为历史对照：

- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_beb54bf_20260625_055800`
- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_a2d9a58_20260624_174615`

上述目录均写入 `BASELINE_SUPERSEDED.md`，其 `superseded_by` 指向当前 `72b27f2` 基线。

以下运行不注册为正式基线：

- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_72b27f2_20260625_172727`

该运行虽完成，但执行过程中主工作区从 `main` 切换到 `codex/t06-graph-retry-performance`，且 T06 阶段前已有未提交 T06 源码改动；目录内已写入 `BASELINE_NOT_REGISTERED.md`。

## 3. 基线产物

| 产物 | 用途 |
|---|---|
| `case_stage_status_baseline.csv` | 四个 Case 各阶段通过状态与耗时。 |
| `t06_funnel_baseline.csv` | T06 Step1 / Step2 / Step3 漏斗与 Segment relation 状态。 |
| `t06_rcsd_base_replacement_rate_baseline.csv` | 以 RCSD 为 Base 的 Road 级与里程级可替换率。 |
| `t06_funnel_compare_vs_beb54bf.csv` | 与上一轮 `beb54bf` 基线的 T06 漏斗差异。 |
| `t06_rcsd_base_replacement_rate_compare_vs_beb54bf.csv` | 与上一轮 `beb54bf` 基线的 RCSD Base 替换率差异。 |
| `baseline_summary.json` | 机器可读总索引，包含版本、路径、Case、漏斗和替换率摘要。 |
| `BASELINE_FREEZE.md` | 逻辑冻结说明。 |
| `BASELINE_USAGE.md` | 后续按模块复用该基线的边界说明。 |

## 4. 运行完成口径

| 指标 | 数值 |
|---|---:|
| Case 总数 | 4 |
| 完成 Case | 4 |
| 通过 Case | 4 |
| 失败 Case | 0 |
| 阶段状态行 | 36 |
| 总耗时 s | 3692.85296 |

四个 Case 均完成 `t01 / t07 / t03 / t04 / t05 / t06_step12 / t06_step3 / t09_step12 / t09_step3`。任一后续对比如果只重跑下游阶段，必须说明复用的上游 handoff 来自本基线。

## 5. T06 漏斗基线

| Case | T01 Segment | Step1 final fusion unit | Step2 replaceable | Step2 plan | Step2 ready plan | Step2 raw rejected | Step3 replaced | Step3 retained SWSD | failed relation | mixed relation | Step3 替换率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 2155 | 1220 | 908 | 1010 | 813 | 312 | 884 | 1268 | 0 | 3 | 41.0209% |
| `609214532` | 1646 | 848 | 610 | 675 | 484 | 238 | 567 | 1075 | 3 | 1 | 34.4471% |
| `74155468` | 155 | 103 | 77 | 82 | 72 | 26 | 75 | 80 | 0 | 0 | 48.3871% |
| `991176` | 224 | 162 | 134 | 142 | 124 | 28 | 125 | 99 | 0 | 0 | 55.8036% |

业务含义：

- `T01 Segment` 是 T06 的 SWSD Segment 输入分母。
- `Step1 final fusion unit` 是前置 relation 与基础锚定满足 T06 继续评估条件的 SWSD Segment。
- `Step2 replaceable` 是 T06 构建 RCSD Segment 后判定具备可替换候选的数量。
- `Step2 plan` 是 Step2 replacement plan 覆盖数量；`Step2 ready plan` 是可进入 Step3 执行的计划数量。
- `Step3 replaced` 是最终 Segment relation 中正式落地为 RCSD replacement 的 Segment 数量。
- `Step3 retained SWSD` 是最终仍保留 SWSD 承载的 Segment 数量。
- `failed relation` 与 `mixed relation` 只作为专项审计对象，不纳入常规替换成功口径。

## 6. RCSD Base 替换率基线

以下口径来自 T06 Step2 summary 中的 `replaceable_rcsd_road_unique_*` 字段，表达“RCSD Road 在当前 T06 判定下可被替换计划覆盖的唯一 Road / 里程比例”。该口径不把 Step3 生成的 split、补拓扑或挂接 Road 反向混入原始 RCSD 分母。

| Case | RCSD Road 总数 | 可替换 RCSD Road | Road 级替换率 | RCSD 总里程 m | 可替换里程 m | 里程级替换率 |
|---|---:|---:|---:|---:|---:|---:|
| `1885118` | 6432 | 4793 | 74.5180% | 641411.723 | 493084.065 | 76.8748% |
| `609214532` | 5031 | 3281 | 65.2157% | 501021.023 | 331734.028 | 66.2116% |
| `74155468` | 518 | 272 | 52.5097% | 48807.587 | 23104.623 | 47.3382% |
| `991176` | 668 | 454 | 67.9641% | 55737.063 | 39714.722 | 71.2537% |
| `TOTAL` | 12649 | 8800 | 69.5707% | 1246977.396 | 887637.438 | 71.1831% |

`t06_rcsd_base_replacement_rate_baseline.csv` 同时保留 reference 口径，`TOTAL` 为 reference road level `72.8674%`、reference mileage `72.9284%`。

## 7. GIS / 拓扑 / 性能审计状态

- CRS 与坐标变换：Case package 空间切片与 T06 漏斗审计均记录 `EPSG:3857`，后续对比不得混入不同 CRS 的结果。
- 拓扑一致性：T06 Step2 显式记录 buffer / component / junction gate，Step3 显式记录 topology connectivity audit；本基线不执行 silent fix。
- 几何语义可解释性：SWSD Segment 几何定义替换窗口，RCSD 几何用于候选选取、覆盖判断与保留输出，Step3 只消费 Step2 replacement plan。
- 审计可追溯性：`baseline_summary.json`、各阶段 `*_stage.json`、stdout log、T06 funnel、replacement plan、problem registry 和 Step3 relation 均可由 run root 定位。
- 性能可验证性：`case_stage_status_baseline.csv` 保留每阶段耗时，`t10_e2e_run_summary.json` 保留总耗时与 Case 完成状态。

## 8. 复用边界

- 如果只修改 T06，应复用本基线中每个 Case 的 `t01`、`t04`、`t05` handoff 输出，只重跑 T06 Step1/2 和 Step3 到新的输出目录。
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
