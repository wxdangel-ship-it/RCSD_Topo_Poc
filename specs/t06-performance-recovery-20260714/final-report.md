# T06 六用例业务冻结与性能恢复最终报告

## 1. 执行范围与环境

- 临时工作树：`E:\Work\RCSD_Topo_Poc__wt_t06_perf_compare_20260714`
- 分支：`codex/t06-performance-compare-20260714`
- 基础提交：`c26b760e6d0e945db6e2fc44885841e136b4a78e`
- 运行环境：`Ubuntu-22.04` WSL，仓库 `.venv`，`PYTHONPATH=src`
- 冻结性能基线：`E:\Work\RCSD_Topo_Poc\outputs\baselines\t10_full_96b0ea5_20260710_060735\t10\e2e_full\cases`
- 当前版本业务/性能基线：`E:\Work\RCSD_Topo_Poc__wt_t06_perf_compare_20260714\outputs\_work\t06_perf_recovery_20260714\current_baseline`
- 最终候选：`E:\Work\RCSD_Topo_Poc__wt_t06_perf_compare_20260714\outputs\_work\t06_perf_recovery_20260714\candidate_v25`
- 严格顺序：先完成 `1885118`，通过后按 `605415675 -> 609214532 -> 706247 -> 74155468 -> 991176` 串行回归。

## 2. 初始业务基线

下表指标来自本轮开始时对当前版本的六用例实跑，并作为最终“不回退”判定基线。

| 用例 | Step1 final | Step2 replaceable / ready | Step3 success | relation replaced / mixed | F-RCSD Road / Node | final topology fail | surface fail |
|---|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 1257 | 979 / 912 | 935 | 931 / 4 | 7105 / 7982 | 0 | 7 |
| `605415675` | 355 | 265 / 253 | 248 | 246 / 2 | 2242 / 2535 | 1 | 7 |
| `609214532` | 904 | 686 / 640 | 655 | 652 / 3 | 5309 / 6208 | 0 | 13 |
| `706247` | 471 | 324 / 284 | 297 | 295 / 2 | 1832 / 2210 | 0 | 3 |
| `74155468` | 118 | 92 / 88 | 85 | 85 / 0 | 460 / 527 | 0 | 1 |
| `991176` | 163 | 138 / 131 | 133 | 133 / 0 | 683 / 797 | 0 | 1 |

`605415675` 的 `final topology fail = 1` 是初始业务基线中的既有结果，不是本轮新增回退；最终候选保持完全一致。

## 3. 性能根因

性能回退的主要原因不是 replacement 业务计算量变化，而是 Surface-aware Step3 将候选、回滚与 final hard-gate 的 `2~4` 次业务验证都当成完整正式运行：

1. 每轮重复发布完整 GPKG/CSV/JSON，并重复构建 ownership、construction 与 topology 审计。
2. 不可变输入被多次读取，空间索引、corridor coverage 与 buffer 判定在同一用例内重复计算。
3. validation 与 final publish 生命周期混在一起，导致候选验证承担正式成果发布成本。
4. ownership 结果历史上通过多次完整 Step3 隐式形成 connectivity group 闭包；直接压缩为一次发布会改变审计证据。
5. authoritative transition closure 可能在较早验证轮产生审计，后续已修复状态使最终轮写出空审计，形成“业务已应用、审计轨迹丢失”。

初始当前版本六例耗时为 `1531.60s`，是冻结线 `611.451823s` 的 `2.505x`。

## 4. 架构与性能优化

- validation 与 final publish 分离：验证运行进入 Linux 临时目录，只保留 gate 必需输出；最终候选一次性提升到正式目录。
- ownership、construction 与正式 feature triplet 只在最终候选发布一次。
- final topology、surface topology 和业务回滚仍完整执行，未减少业务 gate 数量。
- 引入有生命周期边界的只读 feature snapshot cache 与 scalar corridor decision cache；不跨运行缓存 Shapely geometry/buffer。
- Surface runtime state 传递最终 F-RCSD、relation、基础输入与审计状态，避免重复回盘。
- connectivity ownership 在一次构建内完成轻量 attachment/group 闭包稳定化，再执行逐道路空间归属和一次写盘，复现旧流程的最终审计结果。
- 保存验证轮最后一份非空 authoritative transition closure 审计，仅在最终候选缺失时补回。
- Step1/2 feature 成果先写 Linux 临时目录再复制到目标目录，降低 Windows 挂载盘小文件写入成本。
- package-level Step3/unreplaced 导出改为惰性加载，减少 Step1/2 不需要的 GeoPandas 启动成本。
- group replacement path 权重按需计算；topology audit 对 validation 使用更小的 junction/targeted gate 路径。
- `step3_surface_aware_plan_release.py` 修复性拆分为主编排与 `step3_surface_release_plan.py`，保持原 callable/CLI 不变。

以下方案经实测后撤销，没有进入最终实现：GPKG 并行发布、Step2 并行输出、跨运行 Shapely buffer cache、NodeCanonicalizer 单值缓存。它们分别导致 IO 争用、耗时增加或峰值内存上升；其中 geometry cache 试验达到约 `973800 KB` RSS，因此未保留。

## 5. 最终性能结果

| 用例 | 当前版本基线总耗时(s) | 冻结线 Step1/2(s) | 最终 Step1/2(s) | 冻结线 Step3(s) | 最终 Step3(s) | 冻结线总耗时(s) | 最终总耗时(s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 524.34 | 37.952625 | 35.85 | 170.562194 | 149.65 | 208.514819 | 185.50 |
| `605415675` | 235.83 | 16.640231 | 15.54 | 69.407987 | 65.50 | 86.048218 | 81.04 |
| `609214532` | 454.84 | 32.434569 | 29.15 | 136.366095 | 130.73 | 168.800664 | 159.88 |
| `706247` | 143.86 | 15.595644 | 13.97 | 51.195332 | 41.63 | 66.790976 | 55.60 |
| `74155468` | 105.32 | 9.142657 | 7.80 | 29.285408 | 28.55 | 38.428065 | 36.35 |
| `991176` | 67.41 | 9.764868 | 8.25 | 33.104213 | 24.45 | 42.869081 | 32.70 |
| **合计** | **1531.60** | **121.530594** | **110.56** | **489.921229** | **440.51** | **611.451823** | **551.07** |

结论：六例逐例 Step1/2、Step3、总耗时均低于冻结线；总耗时比冻结线快 `9.88%`，比当前版本基线下降 `64.02%`。

## 6. 峰值内存

| 用例 | 当前版本 Step3 peak RSS(KB) | 最终 Step3 peak RSS(KB) | 变化 | swap |
|---|---:|---:|---:|---:|
| `1885118` | 685128 | 606892 | -11.4% | 0 |
| `605415675` | 321388 | 307204 | -4.4% | 0 |
| `609214532` | 568844 | 523452 | -8.0% | 0 |
| `706247` | 294996 | 279232 | -5.3% | 0 |
| `74155468` | 187208 | 183420 | -2.0% | 0 |
| `991176` | 202744 | 197396 | -2.6% | 0 |

所有用例均低于当前版本峰值，且未发生 swap。六例串行执行，避免并行叠加内存峰值。

## 7. 业务、GIS 与测试验收

- 六例共比较 `222` 份 CSV，SHA-256 差异为 `0`。
- Step1/Step2/Step3 关键业务计数、relation、ownership、construction、unreplaced attribution 与审计轨迹均不回退。
- `609214532` 的两条 authoritative transition closure 审计恢复并逐字节一致。
- 六例共检查 `216` 份 GPKG：CRS、schema、feature count 与属性全部一致；`90` 份仅因事务式临时发布产生图层名元数据差异，关键 final F-RCSD Road/Node/Relation 几何逐坐标一致。
- 四份 topology connectivity audit 的可视化 geometry 与当前版本基线不逐坐标一致：三份仅为 MultiLineString 分量顺序变化、拓扑完全等价；`706247` 的一条 `pass` 记录改为引用正式发布后的 F-RCSD Road geometry，修正了当前版本基线中审计几何与同一 `swsd_road_id=519813175` 最终道路端点不一致的问题。该记录属性、判定、CSV 和正式 F-RCSD 成果均保持一致，不构成业务回退。
- CRS 继续统一为 `EPSG:3857`；未改变坐标转换、buffer/距离阈值或 topology fail 定义。
- final topology hard gate、surface topology、rollback 与 accepted exception 规则均保留，不存在 silent fix。
- 输入、参数、run root、日志、`/usr/bin/time -v`、输出和运行环境均可定位。
- T06 全量测试：`431 passed in 79.29s`。
- T06 `src/` 与 `tests/` 扫描 `153` 个源码/脚本文件，`>= 61440 bytes` 为 `0`；主编排 `57187` bytes，新拆模块 `19639` bytes。
- `git diff --check` 通过。

## 8. 边界与待办

- 本轮未修改官方 CLI、入口签名、输出 schema、项目级源事实或 T02。
- 本轮未执行内网环境；结论基于同一 WSL/数据/冻结输入的本地六用例实跑，内网部署仍需使用同样的串行与内存监控口径复核。
- 本轮未执行提交、推送、合并或标签操作；所有代码改动均保留在临时工作树。
