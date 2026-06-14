# 005 - Step2 高等级单向 adaptive buffer 重审

- 日期：2026-06-12
- 模块：T06 Segment fusion precheck
- 变更类型：Step2 高等级单向 Segment 裁剪窗口不足兜底

## 背景

T10 复测中，剩余高等级单向失败样本里存在一类与 pair anchor 错误不同的现象：

- T05 原始 pair relation 已完整，且 RCSD 全图中 required semantic nodes 连通、单向有向路径存在。
- 50m buffer 下 retained RCSD 与 SWSD 几何覆盖比例或候选连通窗口不足，导致 Step2 拒绝。
- 将同一原始 relation 在稍大窗口下重新执行完整 buffer / direction / geometry 审计后可通过。

这类现象更符合空间裁剪或高等级单向道路先分歧再合流造成的局部窗口不足，不应通过 repair candidate 替换已有 T05 锚点解决。

## 业务逻辑变更

Step2 新增高等级单向 adaptive buffer 重审安全门：

1. 仅适用于 `swsd_directionality=single` 且 `swsd_sgrade` 以 `0-0` 或 `0-1` 开头的高等级单向 Segment。
2. 仅适用于 T05 原始 pair relation 已完整的场景，不消费 `t06_rcsd_repair_candidates`，不替换已有 pair anchor。
3. 若 50m 失败原因为 `retained_geometry_outside_swsd_buffer_scope` 或 `swsd_geometry_not_covered_by_retained_rcsd`，最多使用 `75m` 重审。
4. 若 50m 失败原因为 `required_semantic_nodes_not_connected_in_buffer`，必须同时满足全图 required nodes 连通且全图单向有向路径存在，最多使用 `75m / 100m` 重审。
5. 重审通过仍必须通过原 Step2 的 buffer candidate、最小 corridor、方向、叶子端点、额外 mapped semantic node、几何覆盖和特殊路口组门控。
6. 通过后写入 `adaptive_buffer_status / adaptive_buffer_distance_m / adaptive_buffer_source_reason`，并在 failure business audit 中记录 `adaptive_high_grade_single_buffer_retry`。

## 质量与审计

- CRS 与坐标变换：不新增 CRS 处理，继续复用 T06 Step2 的 EPSG:3857 处理 CRS。
- 拓扑一致性：不 silent fix；只在全图拓扑支持且原始 relation 不变时重审，最终仍以硬审计为准。
- 几何语义：SWSD 几何仍定义 buffer 审查窗口；adaptive 只扩大当前 Segment 的审查窗口，不用几何覆盖反推字段语义或替换锚点。
- 审计可追溯性：candidates / replaceable / buffer segments / failure business audit / summary 均记录 adaptive buffer 状态、距离和来源失败原因。
- 性能可验证性：每个符合条件的失败 Segment 最多额外尝试固定小集合距离；summary 记录自动重审通过数量，可从输出复算。

## 验证

- 新增单元测试覆盖：高等级单向 `0-1单` Segment 在 50m 下因 retained geometry 超出 SWSD buffer 被拒绝，75m adaptive 重审后通过完整硬审计，且 `original_rcsd_pair_nodes == rcsd_pair_nodes`。
- T10 真实数据实验已确认多个剩余高等级单向样本属于“原始 relation 不变，75m 或 100m 下硬审计通过”的裁剪窗口不足模式；下一轮全链路复测用于确认端到端替换率提升与 restriction 输出稳定性。
