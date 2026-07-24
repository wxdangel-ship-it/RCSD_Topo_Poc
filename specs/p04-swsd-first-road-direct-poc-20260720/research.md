# P04 Phase 0 Research

## 1. 研究范围与输入

- Patch Vector：`E:\TestData\POC_Data\T10\1885118\Patch_Test`
- SWSD Road：`E:\TestData\POC_Data\T10\1885118\external_inputs\prepared_swsd_roads\prepared_swsd_roads_slice.gpkg`
- SWSD Node：`E:\TestData\POC_Data\T10\1885118\external_inputs\prepared_swsd_nodes\prepared_swsd_nodes_slice.gpkg`
- Patch 数量：6
- Patch 文件数量：426，总大小 `146549520` bytes
- Patch 目录聚合 SHA256：`c98d8a0fa9c84a47c846829aa5b473e2a017ccf0e48fddfb0ea0d9d63f37620e`
- SWSD Road SHA256：`f2e8d7859286a1af3d4177ce94325de377fac27b13c134aa1af074bf9a2f917e`
- SWSD Node SHA256：`18c0287561ee930590fd8ef3a0d84db42094eb28f5f0d4b3835a549b2ae14af4`

本研究只确认当前样本的结构事实和可重复统计，不将观测值自动解释为长期字段语义。

## 2. 决策摘要

### D1：采用 SWSD-first 约束生成，而不是重新拼接当前 Road

**决定**：目标 Road/路口/方向/连接的语义骨架由 SWSD 预生成，Patch Vector 只提供几何、Lane、道路面、分隔和 movement 证据。

**依据**：当前 1015 个 Road 中 970 个与某条成员 Lane 在米制投影下的 Hausdorff 距离不超过 1 mm；Road 宽度全 0、Road Boundary ID 全空，说明当前 Road 大多是成员 Lane 的代表线而非独立走廊拟合。

**未采用**：先生成 Patch RCSD Road，再基于端点、距离和 RoadNextRoad 做跨 Patch 接边。该路径继续受旧 LaneGroup 和 Patch 边界断裂影响。

### D2：以 SWSD Road 身份承担跨 Patch ownership

**决定**：`patch_id` 解析为集合；同一 SWSD Road 的多个 Patch 共同向一个目标语义单元提供证据。

**依据**：571 条相关 SWSD Road 中 81 条包含两个 Patch；24 条同时属于当前 6 个 Patch中的两个 Patch，且均与两侧 `DriveZone_fix` 接触。Vector 的 Lane/Road 关系则全部在单 Patch 内闭合。

### D3：LaneTopo 是主证据，但不是唯一 movement 证据

**决定**：`LaneNextLane` 为主要 Lane movement 证据；`ReferenceLane` 单独保存并参与补充/冲突判断。`FlowNum` 当前作为轨迹聚合强度弱证据参与候选排序和审计，不解释为精确车流量或合法通行事实。

**依据**：728 条 ReferenceLane 全部连接同一 Intersection 的进入与退出 Lane；710 条与 LaneNextLane 重合，18 条为 ReferenceLane-only 且具有 `FlowNum`。

### D4：当前 Road-level 关系只作派生审计

**决定**：`RoadNextRoad`、`IntersectionGoInRoad`、`IntersectionGoOutRoad` 不进入目标拓扑真值层。

**依据**：6 个 Patch 中，RoadNextRoad 与 LaneNextLane 按 `Lane.RoadId` 投影、去内部连接、去重后的 Road 对完全一致；路口进出 Road 表也与进出 Lane 按当前 RoadId 投影完全一致。

### D5：采用约束/图优化为主，学习模型只允许做候选排序

**决定**：P04 核心采用确定性数据契约、图约束、空间候选和可解释评分。若后续有标注数据，模型可以评估 Lane 有效性或证据匹配置信度，但不得直接发布 RoadGraph。

**依据**：SWSD 骨架、Patch ownership、Lane movement 投影和通行规则均存在硬约束；端到端模型难以保证拓扑守恒和完整审计。

### D6：发布完整 SWSD 语义图，并以四态表达高精支持

**决定**：第二里程碑 RoadGraph 完整保留范围内 SWSD Road。Road 全里程获得可信高精证据时为 `hp_supported`，仅部分里程获得支持时为 `partial_hp_supported`，完全没有可用证据时为 `sd_only`，经过输入质检后仍可信的证据与 SWSD 结构矛盾时为 `conflict_retained`。只有 `hp_supported` Road 声明全里程高精支持；`partial_hp_supported` 只对支持区间声明高精支持。

### D7：把 T00 fix 作为同语义修正版，不制造新的业务图层

**决定**：`DriveZone_fix` 与原始 `DriveZone` 业务语义等价，均为道路面；`DivStripZone_fix` 与原始 `DivStripZone` 业务语义等价，均为路面导流带而非 Patch 分区。前者仍记录 T00 Tool2 的 repair、dissolve、`+1m/-1m` 和简化 lineage，后者记录 T00 Tool9 的 repair、dissolve 和简化 lineage。P04 默认消费修正版、保留 raw 属性和修正前几何以便审计，但不把 raw/fix 当成两份独立证据。

### D8：使用 Boundary 垂直投影推导 Lane 实测宽度

**决定**：沿 Lane 采样局部切线和左右垂线，在同一 SWSD corridor/修正 DriveZone 内选择方向相容的左右最近 LaneBoundary，以距离之和计算 `inferred_lane_width_m`。同时保留左右 Boundary、双侧覆盖率、宽度分位数和波动；单侧缺失只形成资料不足证据。

### D9：既有模块只读复用，不兼容能力版本化

**决定**：T00/T08/T01 优先按正式产物和公开契约直接复用；T03-T07/T06 只作 relation-first 对照；T09/T10/T12 优先复用其通行语义、证据组织和图质检能力。P04 不修改任何既有 V1 业务口径；若 Road 直出状态或 handoff 无法被 V1 无损表达，新建显式 V2/适配层并独立验证。

### D10：输入质量与 Road 结构冲突解耦

**决定**：窄 Lane、宽度/Boundary-gap、宽度不稳定、Boundary 资料不足、方向复核和跨 Road 语义节点异常进入独立 `EvidenceQualityFlag`。这些现象可以降低证据可用性或触发人工复核，但不得直接产生 Road `conflict_retained`。Road 冲突只由经过质检后仍可信、且无法与 SWSD Road 结构形成自洽拟合的证据触发。

**依据**：用户确认当前 5 条跨 Road 语义节点异常、29 条方向复核、8 条窄 Lane、131 条宽度/Boundary-gap、133 条宽度不稳定和 Patch `5417631180197930` 的 67 条 Boundary 资料不足 Lane 均属于正常原始数据质量问题，后续将由独立质检体系承接。

### D11：第二里程碑只处理 Road 几何，不提前接入 movement 规则

**决定**：第二里程碑以第一里程碑 Lane owner、LaneBoundary/宽度和道路面证据为诊断基础，但 Road fitting 改用 SWSD 约束下的 Lane 局部片段 owner。第一里程碑整 Lane primary owner 保持不变；同一原始 Lane 可沿自身里程切成多个连续 LaneEvidenceSegment，每个片段唯一归属一个 SWSD Road。SWSD restriction/Laneinfo、RoadSplit 和 movement 合法性投影推迟到后续里程碑。

**依据**：1885118 中整 Lane 单 owner 口径只有 351/571 条 Road 获得证据，而 5m 局部采样与 SWSD 图连续约束识别出 361 条跨多个 SWSD Road 的 Lane，使 433/571 条 Road 获得局部证据；严格/宽松距离角度敏感性下 Road 有证据数量与四态结果稳定。该分段不依赖旧 LaneGroup/Road。

## 3. 已确认的数据事实

- 70 类 GeoJSON 中 29 类有数据、41 类为空。
- 核心实体 ID 在 6 个 Patch 间没有重复；所有已检查外键均可在同 Patch 解析。
- `Lane.Width` 2188 条均为 `3.5`，无法独立承担异常宽度判断；P04 改用左右 LaneBoundary 垂直投影距离之和。
- `Lane.LeftBoundaryId/RightBoundaryId` 与 `Road.LeftBoundaryId/RightBoundaryId` 均为空，需要空间关联。
- `Length / 100` 与几何实测米长高度一致；当前样本支持“约为厘米”的技术判断，但需字段字典确认。
- 原始几何层为 WGS84 三维；`DriveZone_fix/DivStripZone_fix` 为 EPSG:3857。
- 关系表 geometry 为空，只承载外键。
- `TrafficLight/TrafficSign` 为三维竖直矩形，在二维投影中退化，不应按普通二维 Polygon 自动判坏。
- `DriveZone_fix/DivStripZone_fix` 与对应原始层业务语义等价，但并非简单重投影或 union；其几何差异来自 T00 的 per-Patch 修复、dissolve、buffer/简化流程，per-Patch 只描述处理范围和 lineage。
- prepared SWSD Road 的 `segment_id` 全空；Segment 语义需要复用 T01，而非读取该字段。

## 4. 开放问题

1. `LaneType/TurnType/LineTypeSingle/LineTypeColor/IsolationType/RoadFlag/RawEvent.Type` 正式枚举字典。
2. `RoadSplit` 的正式业务定义。

`FlowNum` 的精确统计单位仍未确认，但当前仅作为轨迹聚合弱证据，不阻断 POC；`*_fix` 来源和 `sd_only` 完整发布口径已确认。

这些问题不阻断第二里程碑 Road 几何实现，但阻断相应字段进入强规则；restriction/Laneinfo 和 RoadSplit 本里程碑明确不消费。
