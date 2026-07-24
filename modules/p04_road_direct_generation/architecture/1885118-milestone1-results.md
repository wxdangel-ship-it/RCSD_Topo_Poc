# 1885118 第一里程碑真实数据结果

## 1. 结果定位

本结果对应 `p04_m1_1885118_20260720T235000`，覆盖六个 Patch，流程为：

`SWSD semantic skeleton -> Patch evidence pool -> Lane-Boundary width -> Lane assignment -> LaneTopo readiness audit -> QGIS comparison`

当前产物是 POC candidate，不是完整 RoadGraph，也不进入 T00-T12 正式主链。阈值来自单 Case 原始数据分布，只用于证据分层和复核队列，不是生产规则。

结果目录：`outputs/_work/p04_road_direct_generation/1885118/p04_m1_1885118_20260720T235000/`。

## 2. 端到端门禁

| 门禁 | 结果 |
|---|---:|
| 输入 Patch / Vector 类型 | 6 / 70 |
| 非空 / 空 Vector 类型 | 29 / 41 |
| SWSD RoadSection / Junction / Arm | 571 / 79 / 1142 |
| 内部 overlap / 外部开放边界 Road | 24 / 57 |
| Lane 决策覆盖 | 2188 / 2188 |
| accepted Lane 缺少唯一 owner | 0 |
| QGIS 工程回读图层 | 22 / 22 |
| Lane 长度位于 DriveZone_fix 内比例 | 99.1931% |
| 终态 | passed |

分析 CRS 为 `EPSG:32650`；QGIS 项目展示 CRS 为 `EPSG:3857`，各证据层保留自身 CRS并由 QGIS 显式转换。

## 3. Lane owner 与宽度证据

- Lane decision：accepted 1445、review_required 478、insufficient_evidence 265。
- owner：accepted 1806、review_required 247、insufficient_evidence 135。
- width：nominal 1685、narrow_candidate 8、wide_or_boundary_gap 131、unstable 133、partial 70、insufficient_evidence 161。
- 双侧 Boundary 全采样覆盖 1843 条；Boundary 资料不足 161 条。
- 道路面覆盖低于 0.8 的 Lane 为 39 条，其中 36 条进入 insufficient、3 条进入 review，没有被静默接受。

`narrow_candidate` 只表示几何宽度复核候选，不自动判定误 Lane或非机动车道；`wide_or_boundary_gap` 同时覆盖真实宽路幅、边界缺口和误匹配可能，必须结合 QGIS 和后续资料复核。

Patch 间差异明显：

| Patch | Lane | accepted | review | insufficient | Boundary insufficient | DriveZone < 0.8 |
|---|---:|---:|---:|---:|---:|---:|
| 5417631180197676 | 585 | 389 | 155 | 41 | 19 | 1 |
| 5417631180197788 | 316 | 220 | 62 | 34 | 14 | 5 |
| 5417631180197930 | 245 | 115 | 55 | 75 | 67 | 4 |
| 5417631180198122 | 478 | 365 | 91 | 22 | 11 | 18 |
| 5417631180198182 | 242 | 168 | 31 | 43 | 26 | 6 |
| 5417631180198407 | 322 | 188 | 84 | 50 | 24 | 5 |

因此后续 Road 实例化必须允许 `sd_only`：例如 Patch `5417631180197930` 的主要限制是 Boundary 资料缺失，而不是 SWSD 结构缺失。

## 4. SWSD-first 相对旧 Road 的价值证据

- 1015 个旧 Road/LaneGroup 中，898 个只对应一个高置信 SWSD owner，82 个无支持 owner，35 个混合多个 owner。
- 286 个有 accepted Lane 的 SWSD Road 中，176 个被拆到多个旧 Road 分组，占 61.54%。

这说明旧 Road 既可能把不同语义路段混在一起，也大量把同一 SWSD 路段拆碎。P04 不把旧 Road 当目标真值；它只作为 comparison channel 帮助定位分组差异。

## 5. LaneTopo 一致性准备度

- 2941 条 LaneNextLane 均能关联到两端 Lane 几何；其中 2919 条（99.252%）的最近端点关系为 `Lane end -> NextLane start`，支持把 Lane 几何方向作为当前 Case 的高置信观测。
- 1549 条关系两端 Lane 均 accepted：782 条处于同一 SWSD owner，767 条跨 owner。
- 767 条跨 owner 关系中，733 条满足 SWSD 语义节点有向 `end -> start`，29 条共享语义节点但方向需复核，5 条不共享 SWSD 语义节点。
- 5 条不共享语义节点关系的 Lane 端点间距为约 25.0–36.7 m，且 `IsMeet=false`；它们保留为 QGIS 红色冲突层，不自动接通。

如果只比较 SWSD 物理 Node，会把同一路口的多物理节点错误放大为 371 条“不连通”；使用 `mainnodeid` 归并后的语义 Junction，才收敛为 5 条。这是本轮 SWSD-first 路口先验的直接价值证据。

当前审计是 movement projection 的输入准备度，不等于 T020 已完成。29 条方向复核和 5 条语义异常属于原始数据质检体系，不直接制造 Road 冲突；restriction/Laneinfo 留待后续 movement 里程碑。

## 6. SD 完整性与 T01 复用边界

- 571 条 SWSD Road 中，389 条至少有一个 Lane owner，286 条至少有一个 accepted Lane，285 条当前没有 accepted Lane。
- 570/571 条 SWSD Road 关联到 T01 Segment；唯一未关联 Road 为 `61553339`，位于 Patch `5417631180197930`，保留 `sd_only`，不删除。
- 当前六 Patch 外仍有 57 条开放边界 Road，保持开放审计，不推断缺失相邻 Patch。

## 7. QGIS 检查方式

打开结果目录内 `p04_milestone1_comparison.qgz`。工程使用相对路径，包含六个图层组：

1. `00_本轮目标结果`：accepted/review/insufficient、窄宽异常。
2. `01_SWSD语义骨架`：RoadSection、Junction、T01 Segment。
3. `02_Lane证据明细`：owner rank1、Boundary 采样。
4. `03_原始Vector`：Lane、LaneBoundary、DriveZone/DivStripZone raw 与 fix。
5. `04_当前RCSD与旧Road`：旧 Patch Road、当前 RCSD 只读对照、35 个 mixed-owner 旧 Road。
6. `09_QA与冲突`：733 条跨 Road 节点一致 LaneTopo、5 条语义冲突和冲突表。

默认视图用于全域态势；复核时优先打开红色 `LaneTopo｜跨 Road 语义冲突`、紫红色 `旧 Road｜混合多个 SWSD owner`、宽度异常以及原始 Boundary/DriveZone 图层。

## 8. 当前可进入与不可进入的下一步

可以进入第二里程碑：以 571 条 SWSD Road 为完整容器，将质检后可用 Lane 投影为支持区间，实例化 `hp_supported / partial_hp_supported / sd_only / conflict_retained` 四态 Road geometry candidate。原始质量异常单独输出 QA，不直接作为 Road conflict。

不能据此直接固化生产阈值或发布完整 RCSD：当前只有一个具备 Patch Vector 的 Case，也没有多场景真值回归。RoadSplit、restriction/Laneinfo 和未知 Vector 枚举不进入第二里程碑强规则。
