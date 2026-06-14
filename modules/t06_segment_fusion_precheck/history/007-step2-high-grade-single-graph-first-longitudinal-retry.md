# 007 - Step2 高等级单向 graph-first 纵向联通重审

- 日期：2026-06-12
- 模块：T06 Segment fusion precheck
- 变更类型：Step2 高等级单向 Segment 裁剪窗口不足兜底口径修正

## 背景

T10 目视与数据分析显示，单向 Segment 尤其是先分歧再合流场景中，SWSD 语义路口与 RCSD 语义路口的纵向位置可能相差较大。旧的高等级单向 adaptive buffer 直接扩大整体 SWSD Segment buffer，虽然能提升部分替换，但存在把横向无关 RCSDRoad 纳入候选的风险。

用户确认的新业务口径为：正常 50m 范围内能处理的仍按既有流程处理；单向 Segment 的 pair node 已建立联系但超过 50m 时，应以 RCSD 的两个 pair 路口沿道路联通关系构建 RCSDSegment，同时必须经过 50m SWSD Segment buffer 内的 RCSD 证据。

## 业务逻辑变更

Step2 将高等级单向受限重审从“整体扩大候选 buffer”修正为“RCSD graph-first 纵向联通”：

1. 仅适用于 `swsd_directionality=single` 且 `swsd_sgrade` 以 `0-0` 或 `0-1` 开头的高等级 Segment。
2. 仅适用于 T05 原始 pair relation 已完整的场景；不消费 `t06_rcsd_repair_candidates`，不替换或回写 T05 pair anchor。
3. 使用 SWSDRoad `snodeid / enodeid / direction` 推导出的 directed RCSD pair 顺序，在全 RCSDRoad 有向图中联通两个 RCSD pair 路口。
4. 联通 path 必须经过基准 50m SWSD Segment buffer 内的 RCSD core；仅“碰到 50m buffer”不足以放行。
5. 新增纵向安全门槛：path / SWSD 长度比例不得超过现有 `max_coarse_length_ratio`，path 首尾离开 50m core 的纵向长度不得超过基准 buffer 距离。
6. 候选 RCSDRoad 不再由 75m/100m 整体 buffer 选入；75m/100m 只作为几何参考覆盖审计距离，用于确认纵向差异可解释。
7. 通过后在 candidates / replaceable / buffer segments 继续复用兼容字段 `adaptive_buffer_status / adaptive_buffer_distance_m / adaptive_buffer_source_reason`；其中 `adaptive_buffer_source_reason` 使用 `single_graph_first_longitudinal_retry:<原失败原因>`。
8. failure business audit 的自动提升建议改为 `single_graph_first_longitudinal_retry`。summary 中 `adaptive_high_grade_single_buffer_retry_count` 保留历史字段名，语义为高等级单向受限重审计数。

## 质量与审计

- CRS 与坐标变换：不新增 CRS 处理，继续复用 T06 Step2 已归一的 EPSG:3857 几何。
- 拓扑一致性：不 silent fix；只使用 RCSDRoad `direction` 构建有向 path，且仍执行 pair 方向、叶子端点、额外 mapped semantic node 与特殊路口组硬审计。
- 几何语义：50m SWSD Segment buffer 只作为必须经过的 core 证据；75m/100m 只作为纵向差异参考覆盖审计，不作为候选 road 横向扩张来源。
- 审计可追溯性：输出保留原失败原因、重审 recommendation、实际参考距离、候选 / retained RCSDRoad 与 summary 计数；本履历记录口径变更时间线。
- 性能可验证性：每个符合条件的失败 Segment 只执行固定一次全图有向最短 path 重审；path 长度比例门槛避免长 detour 误提升。

## 验证

- 新增 helper 测试覆盖：高等级单向 path 虽部分超出 50m，但经过 50m core 且 75m 几何参考通过时，可在原 pair 不变的情况下输出 RCSDSegment。
- 新增 helper 测试覆盖：path 虽经过 50m core，但 path / SWSD 长度比例超过门槛的长 detour 必须拒绝。
- 更新 Step2 runner 测试覆盖：原高等级单向重审用例仍可替换，但 failure business audit recommendation 从 `adaptive_high_grade_single_buffer_retry` 改为 `single_graph_first_longitudinal_retry`，且输出 source reason 带 `single_graph_first_longitudinal_retry:` 前缀。
