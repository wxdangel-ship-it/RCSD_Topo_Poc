# Research: P04 高精骨架优先 Road Direct V3

## 1. 冻结基线

唯一 V2 基线为 `p04_directional_v2_1885118_20260721T154712`：571 个父 SWSD Road发布为 638 条 Road；393 个多端物理节点、339 条支持 Road和 278 个 Movement 的独立 QA 违规均为 0。

冻结成果 hash：

| 文件 | SHA256 |
|---|---|
| `p04_directional_roads.gpkg` | `b325d391f41813946d2815cdf807652ea8ea4442b9ed6e5a3ed372be3ce91c74` |
| `p04_directional_movements.gpkg` | `1ddda37d30bbc1327a6b350edeef2920fad6b5a985547f3397ad5fbeeeff523e` |
| `p04_directional_road_graph.gpkg` | `43ef3d1868517415e57388b2da234a8ab637134b8682b81f3630a295ffd160ed` |
| `p04_directional_support_intervals.gpkg` | `061db541afde0b7a2e51a262e9cd5425b818fb12fb6735dd5ac7c76787b32c7a` |

## 2. V2 数据事实

| 指标 | V2 实测 |
|---|---:|
| Road 总长度 | 87,808.443 m |
| `hp_observed` 等价的直接高精中心段 | 28,583.982 m / 32.553% |
| HP—SWSD transition | 10,477.808 m / 11.933% |
| SWSD gap | 48,746.289 m / 55.515% |
| 无高精声明 Road | 299 / 638 |
| 无证据站点 | 10,919 / 18,531 |
| 自动方向表达 | 293 forward + 67 reverse + 278 sd_parent |

V2 的 `unsupported_gap_retained_on_swsd` 与 `unsupported_endpoint_retained_on_swsd` 是硬门禁。因此“偏向 SWSD”是算法结构结果，不是 QGIS 渲染问题。

## 3. 简单补间不足

只把同一 Road首末直接高精片段之间的内部缺口改为补间，理论上只能把高精控制长度从 32.553% 提升到 35.723%；在有证据 Road内部也只有 58.400%。因此 V3 不能只做“内部 gap 插值”，还必须在可审计约束下处理端部和长缺口：

- 直接 Lane/Boundary 中心观测；
- 稳定锚点趋势；
- DriveZone 包络；
- SWSD 纵向语义和 Portal 拓扑；
- 横向斜率、振荡和长度膨胀门禁；
- 开放 Patch 边界限制。

这些约束只能扩大 `hp_constrained_interpolation`，不得扩大 `hp_observed`。

## 4. 技术决策

### D1：规则与确定性图约束优先

本轮不训练神经网络。上游 Vector 已是多年生产的感知结果，当前问题是语义骨架与几何实例化；真实标注不足以支持模型拥有发布权。

### D2：物理走廊先于方向对象

双向字段不再直接产生两个对象。先对同一父 Road评估正反方向 Lane 集合是否形成两条稳定、持续、空间可分的中心走廊；通过才拆分，否则建立共享物理中心。

### D3：SWSD 局部坐标系

继续沿父 SWSD 建立固定站距和法向横截面，SWSD 仅提供纵向参数化。每个站点的横向位置由 Lane/Boundary/道路面证据决定，避免直接复制 SWSD 几何。

### D4：中心证据优先级

1. 覆盖连续、质量可用、横向居中的稳定 Lane；
2. 中间两 Lane 的可追溯共享 Boundary；
3. 多 Lane 横向位置的稳健中心观测；
4. 高精锚点约束补间；
5. SWSD fallback。

DriveZone 只作为包络和延伸合法性约束，不直接决定单 Road owner 或中心线。

### D5：三类几何来源不可混用

- `hp_observed`：站点存在可复算的源 Lane/Boundary 直接观测；
- `hp_constrained_interpolation`：没有直接观测，但受高精锚点和道路面/拓扑门禁控制；
- `swsd_fallback`：上述门禁不成立，显式保留 SWSD。

### D6：条件拆分的最低证据

拆分要求：双侧均有 `usable` 方向证据；各自形成稳定中心；宽度相对间距门禁通过；存在足够纵向共同覆盖；发布高精片段不会塌缩。具体数值是 V3 manifest 的 POC 参数，不升级为生产真值。

### D7：端点和 Movement

Road 端点优先由高精骨架趋势与共享物理 Node共同协调。复杂语义路口继续使用显式 Movement，review LaneTopo 不参与协调。任何 fallback 记录几何来源和原因。

### D8：隔离实现

新增 `HighPrecisionRoadV3Config`、`run_high_precision_road_v3` 和独立输出包。V2、M2、T00-T12 V1、repo CLI、root scripts保持不变。

## 5. 被否决方案

| 方案 | 否决原因 |
|---|---|
| 自动 forward/reverse 拆分 | 对象数量增加不等于高精骨架；缺证据段会重复或重合。 |
| 继续以 SWSD 为全程底线后局部横移 | 结构性保持 55.5% SWSD gap，不能满足目标。 |
| 只连接直接高精片段之间的内部 gap | 实测理论覆盖仅 35.7%，不足。 |
| 使用旧 RCSD 几何补缺 | 旧 RCSD 存在最左 Lane、LaneGroup 和 Patch 接边质量问题，只能对照。 |
| 将插值标记为直接高精 | 破坏审计语义并虚增覆盖。 |
| 使用 DriveZone 几何中心直接造 Road | Patch dissolve 面不是单 Road owner，可能跨道路吸收。 |

## 6. 仍不在本轮确认的内容

- Vector 枚举正式字典；
- RoadSplit 正式语义；
- restriction/Laneinfo 与 ReferenceLane 补充 movement 合法性；
- 多城市生产阈值；
- P04 正式化和主链接入。
