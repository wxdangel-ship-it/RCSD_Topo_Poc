# P04 Phase 0 + 第一/第二里程碑 + Directional Road V2 Validation Summary

## 1. 验证环境

- 日期：2026-07-20
- 仓库：`E:\Work\RCSD_Topo_Poc`
- 分支：`codex/p04-road-direct-poc-20260720`
- 标准运行环境：WSL `.venv/bin/python 3.10.12`
- GeoPandas/Shapely/Pandas：`1.1.3 / 2.1.2 / 2.3.3`
- 数据输入与 hash：见 `research.md` 和模块 `1885118-patch-vector-baseline.md`。

## 2. 数据结构复核

| 检查 | 结果 |
|---|---|
| Patch 数量 | 6 |
| GeoJSON 表类型 | 70 |
| 非空表 | 29 |
| 空表 | 41 |
| baseline 对 29 个非空表的名称覆盖 | 29/29，无遗漏 |
| 模块 README/SPEC/CONTRACT/architecture 01-06 | passed |

读取 geometry 为空的关系表时，GDAL 对空坐标发出 `Invalid coord dimension` warning；关系属性仍完整读取。该 warning 与“关系表无空间几何”的基线结论一致。

## 3. 拓扑与派生关系复核

LaneNextLane 按 `Lane.RoadId` 投影、删除同 Road 内部关系并去重后，与 RoadNextRoad 的 Road 对逐 Patch完全一致：

| Patch | 投影后/实际 RoadNextRoad |
|---|---:|
| 5417631180197676 | 215 / 215 |
| 5417631180197788 | 178 / 178 |
| 5417631180197930 | 189 / 189 |
| 5417631180198122 | 211 / 211 |
| 5417631180198182 | 171 / 171 |
| 5417631180198407 | 183 / 183 |

其它关系：

- IntersectionGoIn/GoOutRoad 与 IntersectionIn/OutLane 按旧 RoadId 投影完全一致。
- 728 条 ReferenceLane 全部连接同一 Intersection 的进入 Lane 和退出 Lane。
- 710 条 ReferenceLane 与 LaneNextLane 重合，18 条为 ReferenceLane-only。

## 4. Road/Lane 几何与字段复核

- Road 总数：1015。
- 970 个 Road 与某条成员 Lane 的 EPSG:3857 Hausdorff 距离不超过 1 mm。
- 903 个 Road 与最接近成员 Lane 的 `Length` 完全相同。
- Lane Width 唯一值：3.5。
- Road LeftWidth/RightWidth 唯一值：0。
- Lane/Road 左右 Boundary 非空引用：0。
- `Lane.Length/100` 与 geodesic 长度的绝对差：median 0.0112 m、p95 0.0969 m、max 0.2502 m。

## 5. 几何语义复核

- 六 Patch 的 DriveZone raw union 与 DriveZone_fix 均存在大于 1 平方米的 symmetric difference；T00 契约和实现确认 fix 经 per-Patch repair、dissolve、`+1m/-1m` 和简化生成。
- 278 个 TrafficLight 和 1351 个 TrafficSign 共 1629 个三维 Polygon 的 XY 投影均只有两个唯一点，确认其为竖直面表达。

## 6. SWSD Patch membership 复核

- 与六 Patch 相关 SWSD Road：571。
- 双 Patch membership：81。
- 两侧均为当前六 Patch 的 overlap：24。
- Vector Road ID 与相关 SWSD Road ID 无交集；当前只存在 Patch membership 关系。

## 7. 仓库治理复核

- `git diff --check`：passed。
- P04 模块无模板占位符。
- 生命周期、模块盘点和机器可读状态表均已登记 P04。
- P04 源码按职责拆分，所有 `.py` 均小于 100 KB；写入前已执行体量前置检查。
- 没有修改 `src/rcsd_topo_poc/cli.py`、`scripts/` 或 `entrypoint-registry.md`；新增的是 P04 研究 callable，不是 repo 官方入口。
- 项目正式主链顺序保持不变。

## 8. 结论

P04 Phase 0 的数据理解已经冻结；第一里程碑又完成了 SWSD 骨架、Lane evidence assignment、旧 Road 差异、LaneTopo 准备度和 QGIS 对比闭环。

用户后续确认并已同步：

- `DriveZone_fix` 与原始 `DriveZone` 业务语义等价，均为道路面；`DivStripZone_fix` 与原始 `DivStripZone` 业务语义等价，均为路面导流带而非 Patch 分区。fix 来自 T00 修正，具体 Tool2/Tool9 处理与当前代码/契约一致。
- FlowNum 按轨迹聚合强度弱证据使用，精确单位仍不假设。
- Road 以 `hp_supported / partial_hp_supported / sd_only / conflict_retained` 四态进入最终完整结果；高精冲突只由质检后仍可信的结构矛盾触发。
- Lane 有效宽度可由左右 LaneBoundary 垂直投影距离之和推导，并需双侧覆盖/稳定性审计。

未知枚举和 RoadSplit 强语义仍保持待确认。

## 9. 当前本地数据的验证能力

当前 `1885118/Patch_Test` 六 Patch 足以支持 P04 第一、第二里程碑及 Directional Road V2 迭代闭环：输入 profiler、SWSD semantic skeleton、Patch evidence pool、Lane-Boundary 空间匹配与宽度推导、Lane owner、Road 支持/缺口区间、四态 `support_state`、方向拆分、稳定中心几何、方向 Portal、开放边界和与旧 Road/输入 RCSD/T06/T12 的只读对照。

当前数据尚不足以证明生产级泛化和最终业务验收：

- 本地六个 T10 Case 中只有 `1885118` 具备 Patch Vector；其它五个 Case 只有旧主链输入，不能形成 P04 多 Case Vector 回归。
- 六 Patch 只有 24 条内部 overlap SWSD Road，另有 57 条关联到未提供 Patch，只能验证开放边界表达，不能验证完整外部闭合。
- 70 类 Vector 表有 41 类为空；当前没有覆盖误 Lane、非机动车道、资料缺失、复杂导流带、硬隔离和桥墩等场景的独立真值标签。
- 当前 RCSD、T06/T12 和旧 RoadNextRoad 可用于差异诊断与回归，但都不是 P04 目标 RoadGraph 真值。

因此当前结论为：**足以开始算法实现和单 Case 迭代，不足以形成生产规则或最终验收结论**。点云和原始轨迹不是本阶段阻塞项，因为 P04 以既有 Vector 作为感知结果输入；后续主要缺口是多场景 Patch Vector Case 与可审计真值。

## 10. 既有模块保护

P04 最大化复用 T00-T12 的正式产物、公开契约和兼容通用能力，但不修改任何既有 V1 行为。若 Road 直出无法被现有 handoff 无损表达，则建立显式版本化的 P04 适配层或对应 V2，并保持 V1 输入输出、入口和生产口径不变。

## 11. 第一里程碑端到端验证

- 最终 run：`p04_m1_1885118_20260720T235000`。
- 结果目录：`outputs/_work/p04_road_direct_generation/1885118/p04_m1_1885118_20260720T235000/`。
- 自动化测试：`7 passed`。
- core / QGIS / overlay / milestone gate：全部 `true`，terminal status 为 `passed`。
- 分析 CRS：`EPSG:32650`；Lane 2188/2188 有决策，accepted 1445、review 478、insufficient 265，accepted 缺失唯一 owner 为 0。
- 宽度：nominal 1685、narrow 8、wide/gap 131、unstable 133、partial 70、insufficient 161；异常均保留复核，没有自动删除 Lane。
- 旧 Road 差异：35/1015 个旧 Road 混合多个 SWSD owner；286 个有 accepted Lane 的 SWSD Road 中，176 个跨多个旧 Road 分组。
- LaneTopo 准备度：2919/2941（99.252%）关系符合 Lane end -> NextLane start 最近端点；767 条 accepted 跨 owner 关系中，733 条有向语义节点一致、29 条共享节点但方向需复核、5 条无共享语义节点。
- QGIS 3.40.14：相对路径工程 22/22 图层回读有效，6 个业务分组完整，预览渲染通过；独立 PyQGIS 进程逐层读取无 invalid/unreadable 图层。
- 自动道路面覆盖：2188 条 Lane 总长 118724.34 m，其中 117766.38 m 位于 `DriveZone_fix`，比例 0.991931，严格门禁通过。
- 核心计算耗时约 64 秒，峰值 RSS 约 227 MB；输入、参数、环境、文件 hash、明细决策和 QGIS 图层均可追溯。

详细业务解释见 `modules/p04_road_direct_generation/architecture/1885118-milestone1-results.md`，逐对象明细见最终 run 内 CSV/GPKG/JSON。

## 12. 第二里程碑启动口径（2026-07-21）

- 目标容器固定为 571 条 SWSD Road，四态数量之和必须为 571，未发布数必须为 0。
- `hp_supported` 表示全里程高精支持，`partial_hp_supported` 表示局部里程支持，`sd_only` 表示完全无可用高精支持，`conflict_retained` 表示质检后仍可信的证据与 SWSD 结构冲突。
- 5 条跨 Road 语义节点异常、29 条方向复核、8 条窄 Lane、131 条宽度/Boundary-gap、133 条宽度不稳定和 Patch `5417631180197930` 的 67 条 Boundary 资料不足 Lane 均作为独立输入质量问题，不直接制造 Road conflict。
- 第二里程碑暂不消费 SWSD restriction/Laneinfo 和 RoadSplit，也不发布 movement 合法性结论。
- 实现参数必须来自真实数据分析并保留敏感性审计；单 Case 得出的阈值不升级为生产规格。

## 13. 第二里程碑端到端终验（2026-07-21）

- 权威 run：`p04_m2_1885118_20260721T030000`；结果目录 `outputs/_work/p04_road_direct_generation/1885118/p04_m2_1885118_20260721T030000/`。
- terminal/core/QGIS/独立 PyQGIS 回读/overlay/milestone gate 全部通过。
- 571 条 Road 完整发布：`77 hp_supported + 355 partial_hp_supported + 139 sd_only + 0 conflict_retained`，未发布 0。
- 27025 个 Lane 样点中 26618 个完成局部 SWSD 拟合；形成 2576 条 LaneEvidenceSegment，362 条源 Lane 可沿局部里程支持多个相邻 Road，但每片 owner 唯一。
- 1341 个支持/缺口区间长度守恒最大误差 `5.684341886080802e-14 m`。
- 571/571 Road 几何非空、有效且 simple；4 条 non-simple 拟合候选显式拒绝并保留 SWSD，没有 silent fix。
- RoadGraph 为 571 Road / 79 Junction / 1142 Arm；Arm 无重复/缺失，Junction 引用有效，Road—Arm 门户最大偏差 0 m。
- 5/29/8/131/133 和 Patch `5417631180197930` 的 67 条 Boundary 资料不足样本均进入独立 QA；直接制造 Road conflict 的数量为 0。
- QGIS 3.40.14 工程含 7 组/24 层、使用相对路径；独立进程逐层回读全部有效。高精证据道路面 overlay overall 为 0.992567，严格门禁通过。
- 全 571 Road 对局部道路面的范围诊断为 0.756537，因包含 `sd_only`、开放边界和局部道路面资料范围外的完整 SWSD 语义 Road，保留为范围诊断而不作为高精拟合失败门禁。
- 核心耗时 81.937 s，峰值 RSS 241.234 MB；431 个输入文件、151304976 bytes 的路径/hash/参数/环境可追溯。
- 自动化测试最终为 15 passed；所有 P04 源码、测试和 validation 脚本均低于 100 KB，T00-T12 V1、CLI、scripts 与入口 registry 未修改。

详细结果与生产边界见 `modules/p04_road_direct_generation/architecture/1885118-milestone2-results.md`。第二里程碑只证明单 Case POC 闭环，不证明参数可直接生产化；RoadSplit、restriction/Laneinfo 和 movement 合法性仍留待后续。

## 14. Directional Road V2 独立几何/拓扑终验（2026-07-21）

- 当前权威 run：`p04_directional_v2_1885118_20260721T154712`。旧 `T121556` 被独立几何门否决，`T145722` 被二次人工审计发现双向证据塌缩和长 SD gap 声明缺口，均降级为历史基线。
- terminal/core/独立发布后 QA/QGIS/独立 PyQGIS 回读/DriveZone overlay gate 全部通过。
- 571 个父 SWSD Road发布为 638 个成果 Road；四态为 `14 hp_supported + 325 partial_hp_supported + 299 sd_only + 0 conflict_retained`，非 `sd_only` 双向单对象为 0。
- 50 个双向证据父 Road中 4 个未达到宽度相对间距要求，8 个 LaneEvidenceSegment 撤销硬几何资格并仅保留 LaneTopo lineage；4 个父 Road均回退为 SWSD 表达，错误发布的塌缩方向子 Road为 0。
- 18,531 个拟合站点中 10,919 个无证据站点和 1,185 个无证据端点均保持 SWSD 横移 0；包络越界 0，最大相邻横移 0.449976 m，最大高精片段振荡 6.0 m/100m，最大长度比 1.012200。
- 42 条部分高精 Road进入 `long_sd_gap_review`，最长 486.336806 m；独立重算集合与发布声明完全一致，仍保留完整 SWSD 语义。
- 767 条跨 owner LaneTopo 守恒为 724 confirmed + 43 review（29 方向、5 语义不连通、9 方向端点冲突），confirmed 聚合为 278 个 Movement（186 物理节点、92 复杂语义路口）。
- 独立 QA 仅从发布 GPKG 读取并复核：393 个多端物理节点、339 条支持 Road、278 个 Movement 和 50 对双向证据，违规均为 0；最大父 SWSD 对齐转角增量 10.285529°、最大 Movement 接头夹角 6.915054°。
- 迭代留痕新增 `T153934` LaneTopo 映射失败与 `T154309` 长 gap 口径不一致；两者均未提升为权威成果，`T154712` 完整通过。
- RCSD 多段同向走廊审计的 2 m/5 m 覆盖率为 0.701177/0.874094；RCSD comparison 仍只用于精度差异解释，不是目标真值或生成门禁。
- QGIS 3.40.14 工程为相对路径，8 组/33 层双重回读全部有效；首组三网显式显示 SWSD 571、RCSD 863、新结果 638，并加入完整来源分段、塌缩、长 gap 和四类独立 QA 图层；来源 hash 变化 0。
- 383 个高精片段的 DriveZone 覆盖率为 0.999846，严格 overlay 门禁通过；第三轮人工审计覆盖塌缩父 Road、长 gap、平滑临界、端点过渡、方向间距、最高度物理 Node、复杂语义路口和 RCSD 高差异样本。
- 核心耗时 119.555 s；Windows 标准 Python 不提供 `ru_maxrss`，peak RSS 明确为不可用而非猜测。P04 自动化测试为 29 passed，M2、T00-T12 V1、CLI、scripts 与入口 registry 未修改。

详细结果见 `modules/p04_road_direct_generation/architecture/1885118-directional-road-v2-results.md`。该终验确认 1885118 单 Case 的 Road 断裂、局部扭曲和 Movement 接头问题通过独立机器验收，不替代多 Case 人工真值、restriction/Laneinfo 完整合法性和生产正式化验收。
