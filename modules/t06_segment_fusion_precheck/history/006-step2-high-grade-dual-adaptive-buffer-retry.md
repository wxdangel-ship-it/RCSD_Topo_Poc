# 006 - Step2 高等级双向 adaptive buffer 重审

- 日期：2026-06-12
- 模块：T06 Segment fusion precheck
- 变更类型：Step2 高等级双向 Segment 裁剪窗口不足兜底

## 背景

在 005 高等级单向 adaptive buffer 规则落地后，继续分析 T10 剩余失败时发现：

- 剩余高等级单向 rejected 在原始 pair relation 不变、buffer 扩大到 200m 的实验下，仍没有新的可替换样本。
- repair candidate 中除既有 endpoint cluster 安全门外，剩余候选要么替换已有 T05 端点且无短桥 cluster 证据，要么候选 pair 重新硬审计失败，不能自动化。
- 但部分 `0-0* / 0-1*` 高等级双向 Segment 的 T05 原始 pair relation 完整，全图 required nodes 已双向可达，只是 50m candidate 窗口漏掉反向 corridor 或几何覆盖范围不足。

## 业务逻辑变更

Step2 将 adaptive buffer 重审从高等级单向扩展到高等级双向：

1. 仅适用于 `swsd_sgrade` 以 `0-0` 或 `0-1` 开头的高等级 Segment。
2. 仅适用于 T05 原始 pair relation 已完整的场景，不消费 `t06_rcsd_repair_candidates`，不替换已有 pair anchor。
3. 双向 Segment 必须满足全图 required nodes 连通且全图 pair 双向可达。
4. 对几何覆盖失败、`required_semantic_nodes_not_connected_in_buffer`、`rcsd_not_bidirectional_for_swsd_dual`，最多使用 `75m / 100m / 125m` 重审。
5. 重审通过仍必须通过原 Step2 的 buffer candidate、最小 corridor、双向可达、叶子端点、额外 mapped semantic node、几何覆盖和特殊路口组门控。
6. 通过后在 summary 中分别记录 `adaptive_high_grade_buffer_retry_count`、`adaptive_high_grade_single_buffer_retry_count`、`adaptive_high_grade_dual_buffer_retry_count`，并在 failure business audit 中记录 `adaptive_high_grade_dual_buffer_retry`。

## 质量与审计

- CRS 与坐标变换：不新增 CRS 处理，继续复用 T06 Step2 的 EPSG:3857 处理 CRS。
- 拓扑一致性：不 silent fix；只在全图双向可达且原始 relation 不变时重审，最终仍以硬审计为准。
- 几何语义：SWSD 几何仍定义 buffer 审查窗口；adaptive 只扩大当前 Segment 的审查窗口，不用几何覆盖反推字段语义或替换锚点。
- 审计可追溯性：candidates / replaceable / buffer segments / failure business audit / summary 均记录 adaptive buffer 状态、距离、方向分组和来源失败原因。
- 性能可验证性：每个符合条件的失败 Segment 最多额外尝试固定小集合距离；summary 记录自动重审通过数量，可从输出复算。

## 验证

- 新增单元测试覆盖：高等级双向 `0-0双` Segment 在 50m 下只覆盖单向通路、以 `rcsd_not_bidirectional_for_swsd_dual` 拒绝，125m adaptive 重审后通过完整双向硬审计，且 `original_rcsd_pair_nodes == rcsd_pair_nodes`。
- T10 真实数据直接 Step2 实验确认：`1885118` 新增 2 条高等级双向替换，`609214532` 新增 2 条高等级双向替换；`74155468 / 991176` 不变。新增样本均保持 T05 原始 pair 不变。
