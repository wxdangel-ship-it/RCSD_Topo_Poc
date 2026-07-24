# 1885118 Patch Vector 数据理解基线

## 1. 文档定位

本文记录 2026-07-20 对 1885118 六个 Patch 的只读实测结果，回答：

1. 哪些 Vector 表有实际数据、结构上表达什么；
2. 哪些字段对 P04 有价值、有哪些限制；
3. Patch 与 SWSD Road `patch_id` 的关系能支持什么结论。

本文是样本基线，不是 Vector 枚举字典。没有正式上游说明的字段只记录结构和值分布，不固化业务码义。

## 2. 输入与可复现性

- Patch 根：`E:\TestData\POC_Data\T10\1885118\Patch_Test`
- Patch ID：`5417631180197676 / 5417631180197788 / 5417631180197930 / 5417631180198122 / 5417631180198182 / 5417631180198407`
- 每个 Patch：70 个 GeoJSON；另有派生 GPKG 文件，共 426 个文件。
- 总大小：`146549520` bytes。
- 按相对路径、文件大小和逐文件 SHA256 生成的目录聚合 SHA256：`c98d8a0fa9c84a47c846829aa5b473e2a017ccf0e48fddfb0ea0d9d63f37620e`。
- SWSD Road：`external_inputs/prepared_swsd_roads/prepared_swsd_roads_slice.gpkg`，SHA256 `f2e8d7859286a1af3d4177ce94325de377fac27b13c134aa1af074bf9a2f917e`。
- SWSD Node：`external_inputs/prepared_swsd_nodes/prepared_swsd_nodes_slice.gpkg`，SHA256 `18c0287561ee930590fd8ef3a0d84db42094eb28f5f0d4b3835a549b2ae14af4`。

## 3. 总体结构结论

- 70 类 GeoJSON 中 29 类有数据、41 类为空。
- 原始空间层为 WGS84 三维，读取表现为 EPSG:4979；`DriveZone_fix/DivStripZone_fix` 为 EPSG:3857。
- `Lane/Road/LaneBoundary/Intersection/ReferenceLane/DriveZone` 等核心几何均非空且在常规二维拓扑下有效。
- 关系表的 geometry 全为空，仅承载 ID 引用；GeoJSON 默认 CRS 对其没有空间意义。
- `TrafficLight/TrafficSign` 是三维竖直矩形，二维投影后退化为线，因此二维 `is_valid=false` 不能直接解释为源数据坏几何。
- 核心实体 ID 在六 Patch 间没有重复；已检查外键全部可在同一 Patch 解析，没有跨 Patch 引用。

## 4. 有数据表、价值字段与限制

### 4.1 Lane 与 LaneTopo 主证据

| 表 | 数量 / 几何 | 结构含义 | 有价值字段 | P04 使用限制 |
|---|---:|---|---|---|
| `Lane` | 2188 / 3D LineString | Lane 级中心线及其旧 Road 归属、路口角色、方向/类型属性 | `Id`、`RoadId`、`Length`、`LaneType`、`TurnType`、`IsIntersectionInLane/OutLane/InnerLane`、`IsLeftmost/IsRightmost`、`IsThereStopLine`、geometry；`Source/*Source/Confidence` 用于来源审计 | `RoadId` 是旧 LaneGroup；`Width` 全为 3.5；左右 Boundary ID 全空；`LaneType/TurnType` 码义待字典确认 |
| `LaneNextLane` | 2941 / 无几何 | LaneTopo 有向后继关系 | `LaneId`、`NextLaneId`、`IsMeet`、`Id` | 主拓扑证据但可能不完备；所有引用仅在 Patch 内，不能用于否定跨 Patch 连接；`IsMeet` 语义待确认 |
| `LaneBoundary` | 6226 / 3D LineString | 车道线/边界几何及线型、颜色、隔离属性 | `Id`、`LineTypeSingle`、`LineTypeColor`、`IsolationType`、`LineGeomConfidence`、`LineTypeConfidence`、`FishBoneType`、geometry | 与 Lane 没有 ID 关联，必须空间匹配；各枚举值待字典确认 |
| `ReferenceLane` | 728 / 3D LineString | 路口进入 Lane 到退出 Lane 的参考 movement 几何 | `Id`、`FromLaneId`、`ToLaneId`、`FlowNum`、`Source`、`Type`、geometry | 全部连接同一 Intersection 的 in->out Lane；710 条也在 LaneNextLane，18 条为独立补充；FlowNum 当前作为轨迹聚合强度弱证据，不解释为精确车流量或合法通行事实 |

Lane 核心观测：

- `Lane.Width=3.5`：2188/2188。
- `Lane.Confidence=0`、`Source=0`、`IsStructured=0`：均为全量常值，当前不具备排序价值。
- `IsIntersectionInLane=true` 580 条，与 `IntersectionInLane` ID 集合完全一致。
- `IsIntersectionOutLane=true` 578 条，与 `IntersectionOutLane` ID 集合完全一致。
- `IsIntersectionInnerLane=false` 2188 条，当前样本没有路口内部 Lane 标记。
- `Length/100` 与 WGS84 几何实测米长的中位绝对差约 0.011 m，当前样本支持长度约为厘米，但仍需字典确认。

P04 的有效 Lane 宽度不读取统一默认 `Width`，而是构造 `inferred_lane_width_m`：沿 Lane 采样局部切线和左右垂线，在同一 SWSD corridor 与修正 DriveZone 内寻找方向相容的左右最近 LaneBoundary，取两侧垂直距离之和。必须同时记录左右 Boundary、双侧命中覆盖率、宽度分位数和波动；单侧缺失或可能跨道路匹配时只形成资料不足/风险证据。

### 4.2 当前 Road/LaneGroup 派生与诊断层

| 表 | 数量 / 几何 | 结构含义 | 有价值字段 | P04 使用限制 |
|---|---:|---|---|---|
| `Road` | 1015 / 3D LineString | 当前 Lane 按 `RoadId` 分组后的代表 Road | `Id`、`Length`、`RcRoadClass`、`RoadFlag`、`RoadType`、`TurnType`、geometry；来源字段供审计 | 不能作为目标 owner；左右宽度全 0、Boundary ID 全空；多数几何复制成员 Lane；码义待字典确认 |
| `RoadNextRoad` | 1147 / 无几何 | 当前 Road 级有向后继关系 | `RoadId`、`NextRoadId`、`TurnType`、`Length`、`TrafficLightControl` | 与 LaneNextLane 按旧 RoadId 投影后的结果完全一致，没有独立目标拓扑信息 |
| `RoadConnect` | 4 / 无几何 | 少量特殊 inRoad->outRoad 关系 | `InRoadId`、`OutRoadId`、`Type`、`TypeSource` | 引用旧 Road；Type 码义未知，只作诊断 |
| `RoadSplit` | 452 / 3D LineString | 独立道路分割/分流线候选 | `Id`、`Source`、geometry | 与 LaneBoundary/Curb/Fence/Lane/Road 无 ID 交集且无完全同形对象；正式业务定义待确认 |
| `RoadTrafficLight` | 157 / 无几何 | TrafficLight 与旧 Road 的关系 | `RoadId`、`TrafficLightId`、`Source` | 需在 P04 中重新映射到 RoadCandidate/movement |
| `RoadRiskArea` | 8 / 无几何 | RiskArea 与旧 Road 的关系 | `RoadId`、`RiskAreaId` | 旧 Road 派生关系，只作空间/来源重投影依据 |
| `SlopePoint` | 63 / 3D Point | 旧 Road 上的坡度/offset 采样 | `RoadId`、`Slope`、`StartOffset`、geometry | 旧 Road 引用，需确认单位并空间重投影 |

Road/LaneGroup 实测：

- 1015 个 Road 均至少有一条 Lane；550 个为单 Lane，465 个为多 Lane，最大 10 Lane。
- 970/1015 个 Road 与某条成员 Lane 在 EPSG:3857 下的 Hausdorff 距离不超过 1 mm。
- 903 个 Road 的 `Length` 与最接近成员 Lane 完全相同。
- 六 Patch 中，将 LaneNextLane 两端按 `Lane.RoadId` 投影、删除同 Road 内部连接并去重后，Road 对与 RoadNextRoad 100% 一致。

因此当前 Road/RoadNextRoad 适合用来解释历史分组和回归差异，不适合作为 P04 目标 RoadGraph 真值。

### 4.3 路口实体与进出关系

| 表 | 数量 / 几何 | 结构含义 | 有价值字段 | P04 使用限制 |
|---|---:|---|---|---|
| `Intersection` | 182 / 3D Polygon | Patch 内识别的路口面及类型/控制属性 | `Id`、`IntersectionType`、`IntersectionSubType`、`NonstandardIntersectionType`、`TrafficLightControl`、`DataTag`、`Source`、geometry | 可作 RC 路口空间证据，不得替代 SWSD 语义路口；类型码义待字典确认 |
| `IntersectionInLane` | 580 / 无几何 | Intersection 与进入 Lane 的关系 | `IntersectionId`、`IntersectionInLaneId` | 与 Lane flag 完全一致；主 Lane-role 结构证据 |
| `IntersectionOutLane` | 578 / 无几何 | Intersection 与退出 Lane 的关系 | `IntersectionId`、`IntersectionOutLaneId` | 与 Lane flag 完全一致；主 Lane-role 结构证据 |
| `IntersectionGoInRoad` | 387 / 无几何 | Intersection 与进入旧 Road 的关系 | `IntersectionId`、`RoadId` | 与 InLane 按旧 RoadId 投影完全一致，只作派生审计 |
| `IntersectionGoOutRoad` | 376 / 无几何 | Intersection 与退出旧 Road 的关系 | `IntersectionId`、`RoadId` | 与 OutLane 按旧 RoadId 投影完全一致，只作派生审计 |

`Intersection.RelatedLayer` 全空；`IntersectionType` 当前全为 1，不代表可据此定义全局码义。

### 4.4 道路面、隔离和边缘证据

| 表 | 数量 / 几何 | 结构含义 | 有价值字段 | P04 使用限制 |
|---|---:|---|---|---|
| `DriveZone` | 978 / 3D Polygon | 原始可通行道路面片段 | `Id`、`Type`、`Source`、geometry | Type 码义待确认；需要 union/coverage 审计，不能直接把每个面当 Road |
| `DriveZone_fix` | 6 / Polygon/MultiPolygon | 与原始 DriveZone 业务语义等价的 T00 修正版道路面 | `patchid`、geometry | 经 repair、dissolve、`+1m/-1m` 和 `0.5m` 简化；per-Patch 是生产与 lineage 范围，不是新的业务分区 |
| `DivStripZone` | 24 / 3D Polygon | 原始路面导流带 | `Id`、geometry | 表示道路面上的导流带，不自动等价于硬隔离 |
| `DivStripZone_fix` | 6 / MultiPolygon | 与原始 DivStripZone 业务语义等价的 T00 修正版路面导流带 | `patchid`、geometry | 经 repair、dissolve 和 `0.5m` 简化；不是 Patch 分区，不与 raw 作为两份独立证据重复计权 |
| `Curb` | 2022 / 3D LineString | 路缘/道路边缘候选 | `Id`、geometry | 缺少类型字段，需要结合道路面、Lane 和方向判断 |
| `Fence` | 3431 / 3D LineString | 护栏/硬隔离候选 | `Id`、`Type`、geometry | Type 码义待确认；空间邻近不自动等于 LaneGroup 边界 |

六 Patch 的 `DriveZone_fix` 面积均大于对应原始 DriveZone union，差异约 0.64 万至 1.81 万平方米；这与 T00 Tool2 的 dissolve、`+1m/-1m` 和简化流程一致。该差异属于同一道路面语义下的修正结果，不表示新增了一类 Patch 级道路分区。

### 4.5 交通控制与道路设施

| 表 | 数量 / 几何 | 结构含义 | 有价值字段 | P04 使用限制 |
|---|---:|---|---|---|
| `Crosswalk` | 365 / 3D Polygon | 人行横道面 | `Id`、geometry | 可辅助路口范围和停止位置，不直接决定 Road 拓扑 |
| `StopLine` | 340 / 3D LineString | 停止线 | `Id`、`Type`、geometry | Type 码义待确认；可辅助入口 arm 定位 |
| `TrafficLight` | 278 / 3D vertical Polygon | 信号灯竖直面及灯组信息 | `Id`、`LightInfo`、`LightTripCnt`、`Confidence`、`Source`、geometry | 二维投影退化；需用 3D/位置/朝向语义，LightInfo 码义待确认 |
| `TrafficSign` | 1351 / 3D vertical Polygon | 交通标牌竖直面 | `Id`、`Type`、`Heading`、`Width`、geometry | 二维投影退化；Type/Heading 单位与码义待确认 |
| `Bump` | 47 / 3D Polygon | 减速设施/路面起伏区域 | `Id`、`Type`、`Confidence`、`BumpLevel`、`BumpSpeed`、`Depth`、geometry | 非 Road 构图主证据；字段单位和码义待确认 |
| `RawEvent` | 314157 / 3D Point | 大量离散原始道路事件点 | `Id`、`Type`、`TypeSource`、geometry | 仅观察到 5 种 `(Type,TypeSource)` 组合；无字典前不得进入规则 |
| `RiskArea` | 3 / 3D Polygon | 风险区域 | `Id`、`Type`、`Confidence`、`Source`、geometry | 样本极少，只作辅助/审计 |

RawEvent 观测组合：`(1,4)=214651`、`(4,4)=37307`、`(1,2)=27668`、`(2,2)=24026`、`(4,2)=10505`。这些数值只用于数据盘点。

## 5. 空表边界

当前 41 个空表：

`ARFindActive`、`AvpKeyPoint`、`AvpKeyPointLabel`、`AvpSignalInfo`、`DoubleBoundary`、`EntryInfo`、`ExperienceSpeed`、`FunctionArea`、`Gate`、`HMILayerInfo`、`IntersectionRoadRender`、`LaneGate`、`LaneInIntersection`、`LaneMessageSign`、`LaneTrafficCondition`、`LaneTrafficLight`、`MessageSign`、`MessageSignTrafficCondition`、`Obstacle`、`OppositeRoad`、`ParkingArea`、`ParkingSpot`、`Pole`、`RestrictionBarriers`、`RestrictionBarriersLane`、`RoadBoundary`、`RoadBump`、`RoadEntryInfo`、`RoadInIntersection`、`RoadMarking`、`RoadParkingSpot`、`RoadPicDensity`、`RoadRef`、`SdRoadToRcRoad`、`SignalGrid`、`SignalGridCellInfo`、`SpeedLimit`、`SpeedLimitRef`、`TrafficCondition`、`TransRelation`、`WheelStopper`。

它们不进入当前 P04 输入契约，也不能因文件存在而假设全量环境一定为空。

## 6. SWSD Patch membership 与 overlap

SWSD Road `patch_id` 解析规则：按逗号拆分、去空、去重，得到 membership 集合。

当前六 Patch 关联到 571 条 SWSD Road：

- 单 Patch：490 条。
- 双 Patch：81 条。
- 双方都在当前六 Patch：24 条。
- 一侧为当前未提供 Patch：57 条，必须保留开放边界。

当前内部 overlap Road 对：

| Patch pair | SWSD Road 数量 |
|---|---:|
| 5417631180197676 - 5417631180198182 | 4 |
| 5417631180197676 - 5417631180198407 | 1 |
| 5417631180197788 - 5417631180198122 | 2 |
| 5417631180197930 - 5417631180198182 | 6 |
| 5417631180197930 - 5417631180198407 | 5 |
| 5417631180198122 - 5417631180198182 | 3 |
| 5417631180198182 - 5417631180198407 | 3 |

24 条 overlap SWSD Road 均与对应双方 `DriveZone_fix` 相交。Vector Road ID 与这些 SWSD Road ID 没有交集，这与用户给出的“只有 Patch 级关系、没有对象级直接关系”一致。

## 7. P04 证据优先级建议

### 7.1 当前可直接作为结构证据

- SWSD Road/Node 身份、方向和 Patch membership。
- Lane/LaneNextLane 几何与外键关系。
- IntersectionInLane/OutLane 结构。
- ReferenceLane 的 from/to 关系和几何；FlowNum 作为轨迹聚合强度弱证据保留。
- DriveZone、Boundary、Curb、Fence 等源几何。

### 7.2 需要空间重建或契约确认

- Lane 实测宽度与左右 Boundary：采用垂直投影距离之和，具体采样间距和有效覆盖阈值后续通过多 Case 验证。
- RoadSplit、Boundary/Fence 各枚举的软硬隔离语义。
- RawEvent、TrafficLight/Sign、Bump 等类型码义。

### 7.3 只作旧成果诊断

- Road、RoadNextRoad、IntersectionGoInRoad/GoOutRoad、RoadTrafficLight、RoadRiskArea 及其它绑定旧 RoadId 的关系。

## 8. 对 Road 直出方案的直接影响

1. 跨 Patch 统一应发生在 SWSD owner/evidence pool 层，而不是旧 Road 端点接边层。
2. Lane 是主证据，但需要 Boundary/道路面/隔离/连续性共同判定伪 Lane和漏资料。
3. LaneNextLane 不能单独承担完整 movement；ReferenceLane 是必要补充证据。
4. 旧 RoadGraph 可用于回归和发现 LaneGroup 问题，但不能决定新图。
5. 最终结果必须完整保留 SWSD Road/movement；资料缺失发布 `sd_only`，高精证据冲突发布 `conflict_retained`，只有 `hp_supported` 子图声明高精 LaneTopo 一致。

## 9. 待用户/上游确认

1. Vector 枚举字典。
2. `RoadSplit` 正式定义。

当前已确认：`DriveZone_fix/DivStripZone_fix` 由 T00 生成且分别与对应 raw 层业务语义等价，表示道路面和路面导流带；FlowNum 可作为轨迹聚合弱证据；`sd_only` Road/movement 必须进入最终完整结果。
