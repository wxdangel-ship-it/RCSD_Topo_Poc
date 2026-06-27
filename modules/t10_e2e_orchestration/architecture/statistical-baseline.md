# T10 统计基线补充材料

本文件记录当前有效的 T10 四 Case 统计基线。它是模块级补充材料，不替代 `01-06` 架构主结构，也不改变 T10 / T06 / T09 的接口契约。

## 1. 当前有效基线

- 刷新日期：2026-06-27。
- 版本：`d1fa27f`，刷新时 `main = origin/main = d1fa27f`。
- 基线目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_d1fa27f_20260627_064205`
- 运行根目录：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_d1fa27f_20260627_064205/e2e_full`
- 当前指针文件：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/LATEST_T10_4CASES_BASELINE.txt`
- 执行 worktree：`/mnt/e/Work/RCSD_Topo_Poc`
- 刷新入口：复用冻结基线关键 handoff，重跑 T06 / T09，并刷新 T10 manifest、summary 与统计表。
- Case package 根目录：`/mnt/e/TestData/POC_Data/T10`
- Case 范围：`1885118`、`609214532`、`74155468`、`991176`。
- T10 总状态：`passed`，4 个 Case 全部完成，失败 Case 数为 0。
- 下游刷新耗时：`685.922646s`。
- 上游反馈统计：Segment `527`，pair-anchor endpoint cluster `628`，side-group candidate `15`，side-group endpoint candidate `24`，relation `0`。

本基线替代 `72b27f2` 四 Case 基线。刷新范围只包括 `t06_step12 / t06_step3 / t09_step12 / t09_step3` 与 T10 汇总产物；T01 / T07 / T03 / T04 / T05 的关键 handoff 来自冻结基线拷贝，未在本轮重跑。日常测试输出不得覆盖该目录；新的优化运行应写入独立 run root，再与本目录下的 CSV / JSON 进行比较。

## 2. 旧基线处理

以下旧目录已取消当前有效身份：

- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_72b27f2_20260625_182356`
- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_beb54bf_20260625_055800`
- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_a2d9a58_20260624_174615`

其中 `t10_4cases_72b27f2_20260625_182356` 已被 `d1fa27f` 基线替代并从本地 `outputs/baselines` 清理。后续自动化或人工审计必须优先读取 `LATEST_T10_4CASES_BASELINE.txt`，不得硬编码旧目录。

以下运行仍不注册为正式基线：

- `/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_4cases_72b27f2_20260625_172727`

该运行虽完成，但执行过程中主工作区从 `main` 切换到 `codex/t06-graph-retry-performance`，且 T06 阶段前已有未提交 T06 源码改动。

## 3. 基线产物

| 产物 | 用途 |
|---|---|
| `case_stage_status_baseline.csv` | 四个 Case 各阶段通过状态与耗时；前置阶段行来自冻结 handoff 证据，下游阶段行来自本轮 T06 / T09 刷新。 |
| `t06_funnel_baseline.csv` | T06 Step1 / Step2 / Step3 漏斗与 Segment relation 状态。 |
| `t06_rcsd_base_replacement_rate_baseline.csv` | 以 RCSD 为 Base 的 Road 级与里程级替换率。 |
| `baseline_summary.json` | 机器可读总索引，包含版本、路径、Case、漏斗和替换率摘要。 |
| `BASELINE_REFRESH_NOTE.md` | 本次从旧冻结基线到 `d1fa27f` 的刷新范围说明。 |
| `BASELINE_FREEZE.md` | 当前逻辑冻结说明。 |
| `BASELINE_USAGE.md` | 后续按模块复用该基线的边界说明。 |

## 4. 运行完成口径

| 指标 | 数值 |
|---|---:|
| Case 总数 | 4 |
| 完成 Case | 4 |
| 通过 Case | 4 |
| 失败 Case | 0 |
| 阻塞 Case | 0 |
| 阶段状态行 | 36 |
| 下游刷新耗时 s | 685.922646 |

四个 Case 均具备 `t01 / t07 / t03 / t04 / t05 / t06_step12 / t06_step3 / t09_step12 / t09_step3` 阶段证据。任一后续对比如果只重跑下游阶段，必须说明复用的上游 handoff 来自本基线。

## 5. T06 漏斗基线

| Case | T01 Segment | Step1 final fusion unit | Step2 replaceable | Step2 plan | Step2 ready plan | Step2 raw rejected | Step3 replaced | Step3 retained SWSD | failed relation | mixed relation | Step3 替换率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 2155 | 1220 | 908 | 1010 | 830 | 312 | 874 | 1208 | 2 | 71 | 40.5568% |
| `609214532` | 1646 | 848 | 610 | 675 | 490 | 238 | 594 | 1023 | 3 | 26 | 36.0875% |
| `74155468` | 155 | 103 | 77 | 82 | 72 | 26 | 78 | 76 | 0 | 1 | 50.3226% |
| `991176` | 224 | 162 | 134 | 142 | 125 | 28 | 130 | 90 | 0 | 4 | 58.0357% |

业务含义：

- `T01 Segment` 是 T06 的 SWSD Segment 输入分母。
- `Step1 final fusion unit` 是前置 relation 与基础锚定满足 T06 继续评估条件的 SWSD Segment。
- `Step2 replaceable` 是 T06 构建 RCSD Segment 后判定具备可替换候选的数量。
- `Step2 plan` 是 Step2 replacement plan 覆盖数量；`Step2 ready plan` 是可进入 Step3 执行的计划数量。
- `Step3 replaced` 是最终 Segment relation 中正式落地为 RCSD replacement 的 Segment 数量。
- `Step3 retained SWSD` 是最终仍保留 SWSD 承载的 Segment 数量。
- `failed relation` 与 `mixed relation` 只作为专项审计对象，不纳入常规替换成功口径。

## 6. RCSD Base 替换率基线

正式口径以 T05 `rcsdroad_out.gpkg` 去重 RCSDRoad / 里程为分母，以 Step3 relation 中最终 `source=1` F-RCSD carrier 的原始 RCSDRoad 集合作为落地集合。`t06_rcsd_base_replacement_rate_baseline.csv` 同时保留 Step2 replaceable RCSDRoad 引用集合，作为候选覆盖 reference 口径。

| Case | RCSD Road 总数 | 最终落地 RCSD Road | Road 级替换率 | RCSD 总里程 m | 最终落地里程 m | 里程级替换率 |
|---|---:|---:|---:|---:|---:|---:|
| `1885118` | 6432 | 4721 | 73.3986% | 641411.723 | 485099.577 | 75.6300% |
| `609214532` | 5031 | 3182 | 63.2479% | 501021.023 | 314797.927 | 62.8313% |
| `74155468` | 518 | 270 | 52.1236% | 48807.587 | 22909.090 | 46.9376% |
| `991176` | 668 | 431 | 64.5210% | 55737.063 | 37887.771 | 67.9759% |
| `TOTAL` | 12649 | 8604 | 68.0212% | 1246977.396 | 860694.365 | 69.0225% |

reference 口径的 `TOTAL` 为 Road 级 `69.5707%`、里程级 `71.1831%`。reference 口径只用于说明 Step2 候选覆盖，不替代最终落地口径。

## 7. GIS / 拓扑 / 性能审计状态

- CRS 与坐标变换：抽检关键 T06 / T09 输出 GPKG 均为 `EPSG:3857`，空几何与 null 几何计数为 0；后续对比不得混入不同 CRS 的结果。
- 拓扑一致性：T06 Step2 显式记录 buffer / component / junction gate，Step3 显式记录 topology connectivity audit；本基线不执行 silent fix。
- 几何语义可解释性：SWSD Segment 几何定义替换窗口，RCSD 几何用于候选选取、覆盖判断与保留输出，Step3 只消费 Step2 replacement plan。
- 审计可追溯性：`baseline_summary.json`、各阶段 `*_stage.json`、stdout log、T06 funnel、replacement plan、problem registry、visual check summary 和 Step3 relation 均可由 run root 定位。
- 性能可验证性：`case_stage_status_baseline.csv` 保留阶段耗时；T06 Step2 的 `duration_seconds=recovered` 表示本轮从既有 Step2 输出恢复并重写下游，不代表重新执行 Step2 主循环耗时。

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
