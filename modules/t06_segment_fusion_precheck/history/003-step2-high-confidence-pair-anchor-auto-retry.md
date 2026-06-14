# 003 - Step2 高置信 pair anchor 自动重试

- 日期：2026-06-11
- 模块：T06 Segment fusion precheck
- 变更类型：Step2 受限自动兜底

## 背景

T10 复测中，部分 SWSD Segment 在 buffer 范围内存在可解释的 RCSD corridor，但 T05 relation 的 pair anchor 缺失、折叠到同一个 RCSD 语义路口，或锚定到错误端点，导致 Step2 无法构建可替换 RCSDSegment。此前 T06 只把这类 `high_confidence_pair_anchor_candidate` 写入 repair candidates，不参与替换。

用户已授权将这类高置信候选升级为可执行兜底，但要求不能做 case 级补丁、不能猜测字段含义、不能破坏拓扑正确性。

## 业务逻辑变更

Step2 在以下条件全部满足时，可对当前 Segment 执行一次 pair anchor 自动重试：

1. failure business category 为 `pair_anchor_mismatch`。
2. buffer-only probe 输出 `repair_recommendation=high_confidence_pair_anchor_candidate`。
3. probe 非 `ambiguous_corridor`，且 `manual_review_required=false`。
4. 候选 pair 有且仅使用首个高置信 pair，两个端点必须不同。
5. 自动重试只补缺失 pair 端点；如果会替换已有 T05 pair 端点，必须存在短距离 endpoint cluster 证据。
6. 自动重试不回写 T05 relation，只在 T06 当前 Segment 内构造 effective relation。
7. effective relation 仍必须通过原 Step2 buffer candidate、seed pruning、leaf endpoint、single/dual direction、geometry coverage、特殊路口组门控等硬审计。

通过重试的 Segment 进入 `t06_rcsd_segment_candidates / replaceable`；`original_rcsd_pair_nodes` 保留 T05 原始 pair，`rcsd_pair_nodes` 记录实际用于构建的候选 pair。失败或不满足安全门槛的候选仍保持 rejected / 人工复核。

## 质量与审计

- CRS 与坐标变换：不新增 CRS 处理，继续复用输入模块的 EPSG:3857 几何。
- 拓扑一致性：不执行 silent fix；候选 pair 必须重新通过 Step2 原有拓扑硬审计。
- 几何语义：只使用 probe 已有的 buffer 几何、候选端点、endpoint cluster 与 bridge road 证据，不启用新字段语义。
- 审计可追溯性：repair candidates 与 failure business audit 同时记录原始 pair、候选 pair、错误端点、cluster/bridge 证据和 `auto_fix_candidate=true`。
- 性能可验证性：每个失败 Segment 最多执行一次额外 buffer extraction，summary 继续输出替换率、自动提升数量和人工复核数量。

## 验证

- 单元测试覆盖缺失 pair relation 自动补缺失端点并进入 replaceable。
- 单元测试覆盖已有端点可由短距离 endpoint cluster 解释时允许自动重试。
- 单元测试覆盖特殊路口组中邻近 corridor 的不安全候选不会被自动放行。
