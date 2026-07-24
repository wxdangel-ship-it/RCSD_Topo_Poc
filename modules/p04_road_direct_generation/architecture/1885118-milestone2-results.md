# 1885118 第二里程碑 Road 直出结果

## 1. 权威运行

- run ID：`p04_m2_1885118_20260721T030000`。
- 结果目录：`outputs/_work/p04_road_direct_generation/1885118/p04_m2_1885118_20260721T030000/`。
- terminal status：`passed`；core、QGIS project、独立 PyQGIS 回读、道路面 overlay 和 milestone gate 全部通过。
- 分析 CRS：`EPSG:32650`。
- 输入：1885118 六个 Patch 的原始 Vector、prepared SWSD Road/Node、T01 Road/Segment 正式产物，以及当前 RCSD Road 只读对照。
- 输入审计：431 个文件、151304976 bytes；路径、hash、参数和运行环境见 `p04_input_manifest.json`。

`T010000/T010500/T011000/T012000/T020000/T023000` 是开发中间运行或失败运行，不是本里程碑权威结果。它们保留用于追溯，不覆盖、不伪装为成功终态。

## 2. 真实数据驱动的实例化结果

第二里程碑没有继续把整条 Lane 强行归给一个 Road。它沿 2188 条原始 Lane 以 5 m 采样，在 SWSD Road 走廊、方向和相邻关系约束下形成连续 `LaneEvidenceSegment`：

- Lane 样点 27025 个，成功局部拟合 26618 个，比例 98.493987%。
- `LaneEvidenceSegment` 2576 条；2155 条源 Lane 至少形成一个有效片段。
- 362 条源 Lane 在不同局部里程支持多个相邻 SWSD Road，最大为 7 个；每个证据片段仍只有一个 Road owner。
- 432 条 Road 获得至少一个高精支持区间，139 条 Road 没有可用高精证据但仍完整保留 SWSD 语义。

最终四态守恒为：

| `support_state` | Road 数 | 解释 |
|---|---:|---|
| `hp_supported` | 77 | 全里程达到当前 POC 高精支持口径。 |
| `partial_hp_supported` | 355 | 只在显式支持区间使用高精拟合，缺口保留 SWSD。 |
| `sd_only` | 139 | 没有可用高精证据，完整保留 SWSD 几何和拓扑。 |
| `conflict_retained` | 0 | 本 Case 没有质检后仍可信、足以证明结构冲突的证据。 |
| 合计 | 571 | 未发布 0。 |

`RoadSupportInterval` 共 1341 段，支持/缺口分区长度守恒最大绝对误差为 `5.684341886080802e-14 m`。

## 3. 输入质量与 Road 冲突解耦

以下用户确认的原始数据正常质量问题均进入 `p04_input_quality_flags.csv`，没有直接转化为 `conflict_retained`：

| 已知质量样本 | 数量 |
|---|---:|
| 跨 Road 语义节点异常 | 5 |
| 跨 Road 方向复核 | 29 |
| 窄 Lane | 8 |
| 宽度/Boundary-gap | 131 |
| 宽度不稳定 | 133 |
| Patch `5417631180197930` Boundary 资料不足 Lane | 67 |

本轮全部输入质量标记直接制造 Road conflict 的数量为 0。异常证据只会被降权、排除或送审，并因此改变支持覆盖，不改变 SWSD Road 的语义存在性。

## 4. 几何与 RoadGraph 拓扑

- 发布 Road 几何 571/571 非空、有效且 simple。
- `hp_fitted=76`、`hybrid_fitted=352`、`swsd_retained_no_evidence=139`。
- 4 条拟合候选会形成 non-simple 几何，已显式拒绝拟合并保留 SWSD：`621953173`、`15640652`、`505781185`、`508528764`；逐对象原因见 `p04_road_geometry_qa.csv`。
- 发布 Road 最大横向位移 18.491128 m，Road 最大位移的 p95 为 6.063119 m。该统计用于发现需多 Case 校准的几何风险，不是生产阈值。
- Road 首尾点相对 SWSD 门户最大偏差为 0 m。
- `p04_road_graph.gpkg` 包含 571 Road、79 Junction、1142 Arm；每条 Road 恰有 `s/e` 两个 Arm，无重复、缺失、未知 Road 引用、空 Arm 或无效 Junction 引用，Road—Arm 门户最大偏差为 0 m。

开发终验曾发现仅检查 valid/simple 会允许 Road 端点被 Lane 拟合横向拉离 Arm，最大达 18.58 m。P04 V2 已改为在每个 Road 端点将拟合位移渐变归零，并把 Road—Arm 门户闭合提升为核心门禁；没有对结果执行 silent snap 或事后不可追溯修补。

## 5. QGIS 工程与空间门禁

- QGIS：3.40.14-Bratislava。
- 工程：`p04_milestone2_comparison.qgz`，相对路径；7 个业务分组、24 个图层。
- 工程写入/回读、embedded QGS XML、预览渲染均通过；绝对 datasource 引用为 0。
- 独立 PyQGIS 进程逐层迭代 24/24 图层全部有效，声明要素数与实际迭代数一致。
- 高精证据范围对 `DriveZone_fix` 的自动 overlay：overall 0.992567；`hp_fitted_segments` 0.985516；`lane_evidence_segments` 0.995465，严格门禁通过。
- 全 571 Road 对当前局部 `DriveZone_fix` 的范围诊断比例为 0.756537，诊断门禁失败。该集合包含 139 条 `sd_only`、开放边界和局部道路面资料范围外的 SWSD Road，因此保留为“完整语义图与高精证据范围不同”的范围证据，不拿来否定高精拟合层，也不静默删除 Road。

## 6. 性能与可追溯性

- 核心端到端耗时：81.937 s。
- 峰值 RSS：241.234 MB。
- M1 直接通过内部 callable 从原始输入重新运行；没有读取前期分析 CSV 伪造第二里程碑结果。
- T00 修正版道路面/导流带和 T01 正式语义按产物/公开契约复用；当前 RCSD、旧 Road/LaneGroup 只进入 comparison channel。
- `src/rcsd_topo_poc/cli.py`、`scripts/`、入口 registry 和 T00-T12 V1 均未修改。

## 7. 主要产物

| 产物 | 用途 |
|---|---|
| `p04_lane_evidence_segments.gpkg` | Lane 样点与局部唯一 owner 证据片段。 |
| `p04_input_quality_flags.csv` | 与 Road 四态解耦的输入质量审计。 |
| `p04_road_support_intervals.gpkg` | 支持/缺口区间、混合几何片段和拟合站点。 |
| `p04_road_audit.csv` | 每条 Road 的四态、覆盖、缺口和来源原因。 |
| `p04_road_candidates.gpkg` | 571 条最终 Road 候选。 |
| `p04_road_graph.gpkg` | 571 Road / 79 Junction / 1142 Arm 的完整 RoadGraph。 |
| `p04_run_summary.json` | 核心、QGIS、overlay、性能和终态机器证据。 |
| `p04_milestone2_report.md` | 本次运行的精简业务报告。 |
| `p04_milestone2_comparison.qgz` | SWSD、原始 Vector、旧成果、本轮四态和 QA 的 QGIS 对照工程。 |

## 8. 已证实与待确认边界

已证实的是：当前六 Patch Case 可以在 SWSD 语义骨架上完整发布 571 条 Road，并让高精支持区间、SD 缺口、输入 QA、混合几何和 Road—Arm 拓扑同时守恒。

仍未证实的是生产泛化：5 m 采样、20 m 距离、35°方向、95% 全覆盖率和 10 m 最大缺口均为单 Case POC 参数；`conflict_retained` 只有合成状态机测试，没有真实可信冲突样本；最大横向位移仍需结合人工真值和多场景 Case 校准。

SWSD restriction/Laneinfo、RoadSplit 和 LaneTopo movement 合法性按本里程碑范围明确未消费，留待后续里程碑，不影响本次 Road 几何与 RoadGraph 验收。
