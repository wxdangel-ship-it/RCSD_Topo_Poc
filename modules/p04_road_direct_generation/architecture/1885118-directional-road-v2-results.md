# 1885118 Directional Road V2 最终结果

## 1. 结论

当前权威 run 为 `p04_directional_v2_1885118_20260721T154712`。该 run 已完成 1885118 六 Patch 的端到端生成、独立发布后几何/拓扑 QA、QGIS 构建与独立回读、DriveZone overlay 和第三轮分层人工复核：

- `terminal_status = passed`；
- core、QGIS 构建、独立 PyQGIS 回读、DriveZone overlay、独立发布后 QA 均为 `true`；
- 571 个父 SWSD Road 语义完整，发布 638 个 Directional Road；
- 50 个双向证据父 Road中 4 个被识别为正反向中心锚点塌缩，均回退为纯 SWSD 父表达，没有构造横向偏移或继续发布方向子 Road；
- 42 条部分高精 Road 的最长无证据区间达到 100 m，完整语义保留，但仅对支持区间声明高精；
- 独立 QA 复核 393 个多端物理节点、339 条支持 Road、278 个 DirectionalMovement 和 50 对双向证据，违规均为 0。

该结论证明当前单 Case POC 已消除本轮目视指出的 Road 断裂、局部 V/S 扭曲和 Movement 接头不协调；不代表参数已经具备多城市生产泛化能力。

## 2. 为什么旧结果不能继续作为权威成果

旧 run `p04_directional_v2_1885118_20260721T121556` 通过了当时由生产器自己汇总的门禁，但门禁覆盖不充分：

1. 物理节点只重点覆盖 confirmed LaneTopo movement 子集，没有复核全部发布 Road 共享的物理 Node。
2. 平滑门禁主要观察横移序列，父 SWSD 的密集顶点会制造厘米级站距并放大局部折线；端点协调又可能在固定短距离内折返。
3. Movement 只保证几何触及 Portal，没有独立复核与两侧 Road 的接头切向。

新增独立 QA 后，`T121556` 被判失败：Movement 接头有 22 个违规；修正 reverse Road 的父几何方向对齐后，支持 Road 仍有 38 条局部转角增量违规。因此它只保留为历史问题基线，不能再被解释为当前通过结果。

## 3. 本轮修正策略

### 3.1 Road 几何

- 拟合站点只使用统一纵向网格，不再把父 Road 的所有原始顶点插入站点序列。
- 横向平滑同时受绝对相邻位移和 `纵向距离 × 最大横向斜率` 约束；当前最大横向斜率参数为 `0.09`。
- 无证据站点继续严格保留 SWSD 横移 0。
- 端点需要协调时，双端修正沿全 Road 平滑插值；单端修正根据位移和横向斜率自适应计算过渡长度，避免固定短距离内返回原线形成 V/S 折线。

### 3.2 物理节点

- 端点协调覆盖所有发布 Road 的 `snode_id/enode_id` 物理节点，不再限于 confirmed LaneTopo movement。
- 节点任一端缺少高精支持时，以父 SWSD 物理节点为稳健目标；全部端点有支持时，以当前端点稳健中心为目标。
- 只有端点离散超过 `0.05 m` 才执行协调，来源和修正量写入审计。

### 3.3 DirectionalMovement

- LaneTopo 证据几何先按来源 Road 终点到目标 Road 起点定向，再截取与两侧 Portal 对应的有效子段。
- 证据连接的接头夹角超过 `10°` 时，显式退回切向连接器。
- 非零间隙的切向连接器按 `0.25 m` 采样；物理共点连接器从两侧 Road 的真实端点线段取切向，避免形式闭合但视觉折断。

### 3.4 双向证据塌缩与长 SD gap

- 对同一双向父 Road 的正反向 provisional 稳定中心锚点按 1 m 采样，独立计算对称中位/P95 间距；要求值为 `max(0.5 m, 0.5 × 较窄侧 Lane 宽度)`。
- 未达要求时，不通过平移制造“两条方向线”，而是撤销相关 LaneEvidenceSegment 的硬几何资格，保留原始 `evidence_quality_state`，父 Road回退为 `sd_parent`。Lane 以 `topology_only_review` 关联该父 Road，确保 LaneTopo lineage 不丢失但不能重新拉动几何。
- `partial_hp_supported` 新增 `high_precision_claim_scope=supported_intervals_only`；最长 SD gap 达到 100 m 时标记 `long_sd_gap_review`。该阈值只用于人工复核和声明边界，不删除 Road，也不把资料缺失提升为 `conflict_retained`。

## 4. 独立发布后 QA

独立 QA 在生产器结束后启动，只读取以下发布工件，不消费生产器内存对象或直接信任其 summary：

- `p04_directional_roads.gpkg`
- `p04_directional_movements.gpkg`
- `p04_directional_road_graph.gpkg`
- `p04_directional_lane_groups.gpkg`
- `p04_directional_support_intervals.gpkg`

输出为：

- `p04_directional_independent_quality.json`
- `p04_directional_independent_quality.gpkg`

独立门禁如下，均为 1885118 单 Case POC 参数：

| 检查 | 门禁 |
|---|---:|
| 空间图层 CRS | EPSG:32650 |
| 多端物理节点最大端点间距 | ≤ 0.05 m |
| 支持 Road 检查站距 | 5 m |
| 支持 Road 相对父 SWSD 的对齐局部转角增量 | ≤ 12° |
| Movement 到两侧 Portal 最大偏差 | ≤ 0.05 m |
| Movement 与两侧 Road 最大接头夹角 | ≤ 10° |
| 正反向锚点/已发布高精片段中位间距 | ≥ `max(0.5 m, 0.5 × 较窄侧 Lane 宽度)` |

最终izer 要求独立 JSON 存在且 `gate_pass=true`；缺失、不可读或失败都不能发布 `terminal_status=passed`。

## 5. 最终真实数据指标

### 5.1 Road 发布与几何

| 指标 | 结果 |
|---|---:|
| 父 SWSD Road | 571 |
| 发布 Directional Road | 638 |
| `hp_supported` | 14 |
| `partial_hp_supported` | 325 |
| `sd_only` | 299 |
| `conflict_retained` | 0 |
| 双向证据审计父 Road | 50 |
| 锚点塌缩父 Road / 降级 LaneEvidenceSegment | 4 / 8 |
| 错误保留的塌缩方向子 Road | 0 |
| 长 SD gap 复核 Road | 42 |
| 拟合站点 | 18,531 |
| 无证据站点 | 10,919 |
| 无证据端点 | 1,185 |
| 无证据站点/端点最大横移 | 0 m |
| 最大相邻横移 | 0.449975543 m |
| 最大高精片段横向振荡 | 6.0 m/100m |
| 最大长度比 | 1.012200174 |
| LaneGroup 包络越界 | 0 |

独立 QA 复核 339 条有高精支持的 Road：CRS、valid/simple、父 SWSD lineage 全部通过；局部转角增量违规 0，最大值 10.285529°，最大局部转角 17.080472°。50 对双向证据违规 0；4 个塌缩候选均无 forward/reverse 子 Road，剩余方向对中最小发布高精间距仍为要求值的 1.92 倍。42 条长 SD gap 声明与独立重算集合完全一致，最长 486.336806 m。

### 5.2 LaneTopo 与拓扑

| 指标 | 结果 |
|---|---:|
| 跨 owner LaneTopo 输入 | 767 |
| confirmed / review | 724 / 43 |
| 聚合 DirectionalMovement | 278 |
| 物理节点 / 复杂语义路口 Movement | 186 / 92 |
| 独立复核多端物理节点 | 393 |
| 物理节点违规 | 0 |
| 最大物理节点端点间距 | 0 m |
| Movement 违规 | 0 |
| 最大 Movement—Portal 偏差 | 0 m |
| 最大 Movement 接头夹角 | 6.915054° |

review 仍保留 29 条方向复核、5 条语义不连通和 9 条方向端点冲突，不参与端点协调，也未被 silent fix。其中塌缩 Lane 只关联回退的 `sd_parent` 以保持可追溯性，不重新启用方向几何。当前只声明 LaneTopo 投影一致性，不声明 restriction/Laneinfo 意义上的完整通行合法性。

### 5.3 与输入 RCSD 的精度差异

多段同向 RCSD 走廊对照为诊断而非生成门禁：

| 指标 | 最终 run |
|---|---:|
| 2 m 覆盖率 | 0.701177204 |
| 5 m 覆盖率 | 0.874093709 |

相较旧 `T121556` 的 0.715375/0.878062，2 m/5 m 覆盖率分别下降约 1.42/0.40 个百分点；同时最大相邻横移由 1.998650 m 降至 0.449976 m，最大长度比由 1.051355 降至 1.012200。人工复核的 RCSD 高差异样本显示，极端差异主要发生在旧 RCSD 候选走廊偏离或 Vector 支持很短的 Road；新结果在有证据区间使用 Lane/LaneBoundary 中心，在缺证据区间回到 SWSD。该差异是可解释的声明边界，并不表示输入 RCSD 是目标真值。

## 6. 三轮独立验收迭代

| run | 独立 QA 结果 | 处置 |
|---|---|---|
| `T144926` | 物理节点 0 违规；Road 38 违规；Movement 22 违规，最大接头 22.47° | 修正 Movement 定向、截取与切向 fallback |
| `T145354` | 物理节点 0；Movement 0；Road 4 违规，最大转角增量 15.134° | 修正全物理节点端点协调和自适应平滑重定向 |
| `T145722` | 物理节点、Road、Movement 均 0 违规；二次人工审计发现 4 个双向高精塌缩父 Road和 42 条长 SD gap 未显式分层 | 降为历史基线 |
| `T153934` | 4 个塌缩父 Road已回退，但 8 条跨 owner LaneTopo 无唯一发布 Road映射，core 失败 | 增加 `topology_only_review` lineage |
| `T154309` | core 与独立硬门通过；独立长 gap 统计误含纯 `sd_only`，声明差异 118 | 统一为仅审计 `partial_hp_supported` |
| `T154712` | core、独立 QA、QGIS、overlay 和第三轮人工审计全部通过 | 当前权威成果 |

每次修复后都重新执行独立 QA；没有通过时未把该 run 提升为最终权威成果。

## 7. QGIS 与自动可视化验收

- QGIS：3.40.14-Bratislava；Python 3.12.12；GDAL 3.12.1；PROJ 9.7.1。
- 工程：`p04_directional_v2_comparison.qgz`，使用相对路径，共 8 个分组、33 个图层。
- 首组默认并列原始 SWSD 571、原始 RCSD 863、新结果 638；完整来源分段默认按 HP/transition/SD gap 三色显示。
- `09_几何与拓扑QA` 增加双向证据塌缩、长 SD gap、独立 Road 平滑、物理 Node 断裂、Movement 接头和双向高精间距图层；最终独立违规层均为空。
- 独立 PyQGIS 回读：33/33 图层有效，声明数量与实际遍历一致，空间 CRS 全部匹配，来源 hash 未变化。
- DriveZone 自动 overlay：383 个高精片段，总长 28,583.9817 m，面内 28,579.5805 m，overall ratio 0.9998460263，通过 0.95 总体门禁。

第三轮人工复核材料：

- `p04_manual_audit_round3_collapsed_parents.png`：4 个塌缩父 Road均只发布 SWSD 父表达，provisional 正反锚点仅作审计。
- `p04_manual_audit_round3_long_sd_gaps.png`：6 条最长 gap Road连续保留 SWSD，HP/过渡/SD 来源分段清晰，无“断裂即缺失”的误表达。
- `p04_manual_audit_round3_smoothness_edge.png`：6 条转角增量最高 Road无 V/S 折线或回钩。
- `p04_manual_audit_round3_endpoint_transitions.png`：6 条最大端点协调位移 Road均为平滑渐变接入。
- `p04_manual_audit_round3_direction_pair_margin.png`：6 对最小通过裕量方向 Road保持物理分离。
- `p04_manual_audit_round3_high_degree_physical_nodes.png`：端点数最高的 6 个物理节点均共点。
- `p04_manual_audit_round3_complex_semantic_junctions.png`：Movement 数最高的 6 个复杂语义路口均由显式 LaneTopo movement 连通。
- `p04_manual_audit_round3_rcsd_divergence.png`：RCSD 差异最大样本的差异来源可解释为旧 RCSD 走廊偏离或缺证据回退，而非高精片段任意偏移。

## 8. 性能、追溯与边界

- 核心端到端耗时 119.555 s；独立发布后 QA 1.084 s。
- 输入路径/hash、参数、环境、Road/Movement 逐对象审计、QGIS 工程和独立 QA 可从 run root 定位。
- Windows 标准 Python 未提供可靠 `ru_maxrss`，峰值 RSS 继续标记为不可用，不猜测。
- M2、T00-T12 V1、repo CLI、root scripts 和入口 registry 均未改变。

仍待后续处理：SWSD restriction/Laneinfo、ReferenceLane 补充、RoadSplit 正式语义、完整 movement 合法性、多 Case/人工真值和生产参数冻结。

## 9. 权威工件

结果根目录：

`outputs/_work/p04_road_direct_generation/1885118/p04_directional_v2_1885118_20260721T154712/`

关键文件：

- `p04_directional_v2_summary.json`
- `p04_directional_v2_report.md`
- `p04_directional_independent_quality.json`
- `p04_directional_independent_quality.gpkg`
- `p04_directional_v2_comparison.qgz`
