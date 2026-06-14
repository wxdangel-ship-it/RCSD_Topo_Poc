# 016 Step1 0-2双虚拟 T 型 pair 延迟放行

- 时间：2026-06-14
- 模块：T06 Segment Fusion Precheck / Step1
- 变更类型：虚拟锚定路口进入 Step2 probe 的受限扩展

## 根因

T10 `991176` 中 `23612484_23612492` 与 `23612489_23612493` 均为 `sgrade=0-2双`，两个 pair 端点均已有 `has_evd=yes`，但 `is_anchor=no`、`kind_2=2048`。T07 明确不为 `kind_2=2048` 建立 SWSD-RCSD 成功 relation，交由 T03 虚拟锚定；因此这类 Segment 在 Step1 被 `is_anchor_not_eligible` 拦截后，Step2 的 relation-independent buffer probe 与正式硬审计完全没有机会判断 RCSDRoad 是否能构建 RCSDSegment。

离线用全量 T01 Segment 直接喂 Step2 的探针结果显示，`23612484_23612492` 能通过现有 Step2 硬审计构建 RCSD Segment，而 `23612489_23612493` 仍因候选方向性不足保持 rejected。因此根因不是某个 Case ID 缺补丁，而是 Step1 对 `0-2双` 虚拟 T 型 pair 的门槛过早，导致可由 Step2 证明的候选被提前过滤。

## 业务逻辑变更

Step1 新增独立于高等级 junc 脱挂的受限放行：

1. 仅适用于 `sgrade=0-2双`。
2. 仅适用于两个 `pair_nodes.kind_2` 均为 `2048` 的虚拟 T 型 pair。
3. 两个 pair 端点仍必须已有 `has_evd=yes`。
4. `is_anchor` 必须明确为非可用 anchor；缺失 `is_anchor` 不放行。
5. 仅放行 pair 主通道进入 Step2 probe，不扩大 `junc_nodes` 的 `kind_2` 放行，也不扩大 Step1 detached junc 规则。
6. 不适用于 `0-2单`，不适用于混合 `kind_2` pair。
7. Step2 仍必须通过 relation mapping / buffer-only probe / formal retry / direction / topology / geometry / special group 等全部硬审计后才能输出 replaceable；未通过的 Segment 保持 rejected。

## GIS / 拓扑检查

- CRS 与坐标变换：Step1 不新增空间计算，继续携带 `EPSG:3857` 几何供 Step2 审计。
- 拓扑一致性：不 silent fix；Step1 只改变进入 Step2 probe 的候选分母，不构造 RCSD 拓扑。
- 几何语义：虚拟 T 型 pair 的最终几何合理性仍由 Step2 的 50m buffer、RCSD graph、方向与覆盖审计决定。
- 审计可追溯性：Step1 summary、final fusion units 与 rejected 继续记录 `sgrade / pair_nodes / failed_node_attrs`；本履历记录 0-2双放行边界。
- 性能可验证性：放行条件只检查两个 pair node 属性；额外 Step2 开销限定在命中该窄条件的 Segment。

## 验证

- 新增 `test_step1_allows_only_dual_0_2_virtual_t_pair_nodes_for_step2_probe`，覆盖 `0-2双 + 两端 kind_2=2048` 可进入 final fusion units，同时验证 `0-2单`、混合 `kind_2` pair 与 `0-2双` junc 失败仍被拒绝。
