# 1885118 High-Precision Road V3 结果

## 1. 结论

权威 V3 POC run 为 `p04_hp_v3_1885118_20260721T180655`。该 run 以 `p04_directional_v2_1885118_20260721T154712`（638 Road）作为唯一冻结 V2 对照，在不修改 M2、Directional V2、T00-T12 V1、repo CLI 和 root script 的前提下完成端到端发布，最终 `terminal_status=passed`。

V3 的主要变化不是继续复制 `forward/reverse` 对象，而是将 SWSD 限制为 Road/Junction 语义身份、ownership、完整性和缺资料兜底；有证据 Road 的几何优先由稳定中心 Lane、固定站点观测、DriveZone 约束和平滑 Portal 过渡决定。只有双侧独立高精走廊同时满足纵向持续性和宽度相对物理间距时才发布两个物理方向走廊。

## 2. 发布规模

| 指标 | V3 实测 |
|---|---:|
| SWSD 父 Road | 571 |
| V3 Road | 603 |
| 条件 split 父 Road | 32 |
| shared physical 父 Road | 265 |
| 无可用高精证据 fallback 父 Road | 274 |
| Portal / Arm | 1206 / 1206 |
| LaneTopo 输入 | 767 |
| confirmed / review | 733 / 34 |
| Road Movement | 284 |

571 个父语义单元与 571 个物理走廊决策一一对应。32 个 split 均有 `forward + reverse` 两个独立走廊；不存在只反转坐标的重复对象，也不存在 split 后整段塌缩到同一中心线。

## 3. 高精骨架与来源

独立发布后 QA 从最终 GPKG 复算：

| 几何来源 | 长度 | 全网占比 |
|---|---:|---:|
| `hp_observed` | 31,367.730 m | 38.997% |
| `hp_constrained_interpolation` | 17,041.231 m | 21.185% |
| `swsd_fallback` | 32,027.541 m | 39.817% |
| 合计 | 80,436.502 m | 100% |

- 有原始中心观测 Road 的高精控制覆盖率为 88.550%，高于 80% 门槛。
- 全网 SWSD fallback 为 39.817%，低于 40% 门槛。
- 1267 个高精受控片段在 DriveZone 道路面内的长度占比为 98.364583%。
- 来源区间分割、最终 Road 覆盖、字段声明、直接观测支撑和约束补间支撑的独立违规均为 0。
- 支持状态为 `329 partial_hp_supported + 274 sd_only`；本 Case 没有可信真实 `conflict_retained` 样本。V3 没有把局部约束补间冒充完整直接观测，因此没有 `hp_supported` 全直接观测 Road。

冻结 V2 逐 Road 形态对照独立发布在 `p04_hp_v3_frozen_v2_comparison.gpkg`。603/603 条 V3 Road 均匹配到同一 `parent_swsd_unit_id` 下的冻结 V2 Road，其中 290 条命中同 `travel_side`，313 条 shared/fallback Road 使用同父语义最近 V2 对照；V3→V2 5 m 采样平均距离的 Road 级中位数为 0.133 m，Road 级 P95 采样距离的 P95 为 4.870 m。该差异只描述形态，不作为 V3 正确性门禁，也不把冻结 V2 当真值。

## 4. 平滑与 Portal 协调

V3 使用稳定中心 Lane 作为主基准，只有主基准在当前站点不可用时才回到同 Road 的稳健 LaneGroup 中心；横向序列经过固定 5 m 站距平滑、Lane 包络、最大横向斜率和有效/simple 门禁。Portal 协调只作用于局部端点过渡，不再把同时修正两端的 Road 整体平移。

对 603 条最终 Road 的独立结果：

- valid/simple：603/603；
- 需要局部端点协调的 Road：306；
- 394 个多端物理节点最大端点间距：0 m；
- 支持 Road 相对父 SWSD 的 5 m 对齐额外转角最大值：25.043613°，当前 26° POC 门槛违规 0；
- 32 个 split 的最终物理间距审计违规：0。

26° 是针对路口、匝入和弯道实际样本确定的单 Case POC 复核参数，不是生产容差。人工复核了额外转角最大的 9 条 Road和间距最接近门槛的 9 组 split，未见站点级锯齿、整段塌缩或反向克隆；详见 run root 的 `p04_hp_v3_manual_audit.md` 与两张人工审计拼图。

## 5. LaneTopo 与 RoadGraph

- 767 条跨 owner LaneTopo 全部保留：733 confirmed、34 review；review 为 29 条方向复核和 5 条语义不连通复核。
- confirmed link 全部聚合到 284 个 Road Movement，link 守恒差异为 0。
- 152 个同物理节点 Movement 使用触及共享 Portal 的跨 Portal 连接；132 个复杂语义路口 Movement 显式连接不同物理 Portal。
- Movement 最大 Portal 偏差 0 m，最大接头角 9.803260°，未知 Road 引用、无效/非 simple 和接头违规均为 0。
- 1206 个 Portal 与 1206 个 Arm 完整、唯一并与 Road 端点闭合。

该结果只证明当前 LaneTopo 投影与 V3 RoadGraph 一致。restriction/Laneinfo、ReferenceLane 补充、RoadSplit 和完整 movement 合法性仍未接入。

## 6. QGIS 与可重复性

QGIS 工程 `p04_hp_v3_four_network_comparison.qgz` 固定提供四网对比：

1. 原始 SWSD；
2. 原始 RCSD；
3. 冻结 Directional V2；
4. High-Precision Road V3。

V3 主图层按 `support_state` 分类，来源分段按 `hp_observed / hp_constrained_interpolation / swsd_fallback` 分类。QGIS 3.40.14 构建和独立回读均通过：26/26 图层有效、项目和空间图层 CRS 均为 EPSG:32650、四个 comparison role 齐全、数据源为相对路径、绝对数据源引用 0、源 GPKG hash 变化 0。

## 7. 性能

同一 Windows 环境下正式核心运行耗时 116.065 s，其中复用并重跑 M2 为 84.071 s，高精走廊与几何为 23.043 s，movement/topology 为 6.664 s，成果写盘为 2.152 s。

为补齐峰值内存证据，独立性能 replay `p04_hp_v3_perf_replay_1885118_20260721T183631` 从进程启动即按 200 ms 采样，并读取 Windows lifetime peak：核心耗时 110.969 s，lifetime peak working set 219.414 MiB，采样 peak private 904.094 MiB。replay 的 571/603/32 Road、三类几何长度、733+34 LaneTopo、284 Movement 与 603 条 V2 对照均与权威 run 一致，core gate 通过；它没有执行 QGIS/人工审计，因此只作性能证据，不替代权威 run。完整记录见 `p04_hp_v3_performance_replay_audit.json`。性能事实绑定本 Case、当前依赖版本和参数，不外推到全城规模。

## 8. 边界

- 本结果仍是 1885118 六 Patch POC，不是正式 RCSD/F-RCSD。
- 1.5 m DriveZone 容差、物理走廊间距、局部端点过渡比例、26°平滑门槛及 80%/40% 覆盖门槛均需多 Case 冻结。
- 输入空坐标、Lane 宽度/Boundary gap、资料不足等正常质量问题仍由独立输入 QA 承载，不直接制造 Road `conflict_retained`。
- 冻结 V2 四个核心文件 hash 全部保持授权值；V3 输出位于独立 run root。
