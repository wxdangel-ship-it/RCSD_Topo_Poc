# 014 高等级 junc-only 拖垮节点脱挂与局部 carrier 保留

- 时间：2026-06-13
- 模块：T06 Segment Fusion Precheck / Step1 + Step3
- 变更类型：高等级 Segment 主通道资格判定收敛；Step3 detached junc 局部 SWSD carrier 保留

## 根因

T10 991176 审计发现，部分高等级 SWSD Segment 的 `pair_nodes` 已具备主通道构建条件，但 T01 聚合出的 `junc_nodes` 中包含附属、侧挂或空间裁剪边缘节点。这些 junc-only 节点不一定参与 pair-to-pair 主通道，却在 Step1 被纳入 `has_evd / is_anchor` 硬门槛，导致 Segment 没有机会进入 Step2 的 relation、buffer、方向与拓扑硬审计。

典型现象包括：

- `991164_991176`：pair 两端均已锚定，但 `503668214 / 508668432` 作为 junc-only 节点 `is_anchor=no`，Step1 以 `is_anchor_not_eligible` 拒绝。
- `1019779_1026330`：pair 两端均已锚定，但 `1022910` 作为 junc-only 节点 `has_evd=no`，Step1 以 `has_evd_not_yes` 拒绝。
- `81524140_81524145`：同时存在 pair 端点缺失与 junc-only 拖垮；junc-only 脱挂后，既有 Step2 pair anchor 受限重试才有机会验证主通道。

## 业务逻辑变更

### Step1：junc-only 拖垮节点脱挂

Step1 对 `sgrade` 属于 `0-0* / 0-1*` 的高等级 Segment 增加受限 junc 脱挂：

1. `pair_nodes` 仍必须通过原有 `has_evd / is_anchor` 或已存在的高等级 Step2 probe 放行规则。
2. 仅当失败节点属于 `junc_nodes`，且失败原因为 `has_evd_missing / has_evd_not_yes / is_anchor_missing / is_anchor_not_eligible` 时，才允许脱挂。
3. 脱挂节点从 final fusion unit 的 `junc_nodes / semantic_node_set` 中移除，不参与 Step2 relation 主通道输入。
4. 脱挂节点写入 `detached_junc_nodes / detached_junc_reasons`，供后续审计追踪。
5. `t06_step1_summary.json` 增加 `detached_junc_segment_count / detached_junc_node_count / detached_junc_reason_counts`。

### Step3：detached junc 局部 carrier 保留

Step1 脱挂只表示该 junc-only 节点不参与 pair-to-pair 主通道审计，不表示其触达的原 SWSDRoad 可以全部删除。991176 端到端复测发现，若 Step3 继续按 T01 原始 Segment 的 `roads` 删除全部 SWSDRoad，T09 对 detached junc 显式 restriction 的 arm carrier 会从原 `retained_swsd source=2` 变成空映射，导致合法 restriction 丢失。

Step3 对 replaceable Segment 增加局部保留规则：

1. 对比 T01 原始 `junc_nodes` 与 Step1/Step2 replaceable 的 `swsd_junc_nodes`，识别 detached junc。
2. 若原 SWSDRoad 的 `snodeid / enodeid` 命中 detached junc，则该 Road 不进入删除集合，以 `source=2` 留在 F-RCSD。
3. 替换单元与 Segment relation 输出 `detached_junc_nodes / retained_detached_swsd_road_ids`。
4. Segment relation 使用 `relation_status=replaced+retained_swsd`，`frcsd_road_ids` 同时包含 `source=1` 的 RCSD 主通道 Road 与 `source=2` 的 detached junc 局部 carrier。
5. `swsd_to_frcsd_node_map` 为 detached junc 增加 `identity_retained_swsd`，仅表达局部 SWSD carrier 保留，不宣称 RCSD 锚定成功。
6. `t06_step3_summary.json` 增加 `detached_junc_retained_segment_count / detached_junc_retained_swsd_road_count`。

## 安全边界

- 不适用于 `pair_nodes`；pair 端点失败仍按原规则拒绝或进入既有高等级 Step2 probe。
- 不适用于 `kind_2 in {64,128}` 特殊语义路口，避免绕过特殊组门控。
- 不新增输入字段，不反推 `kind_2` 新语义，不修改 T01/T05 输出，不回写 T05 relation。
- Step2 仍以 pair relation、50m buffer core、direction、topology、geometry、special group 等硬审计决定是否可替换。
- Step3 detached carrier 保留只针对 detached junc 触达的原 SWSDRoad，不扩大 Step2 replaceable 集合，不处理 Step2 rejected Segment。
- `identity_retained_swsd` 不得被下游解释为 SWSD-RCSD 节点映射成功；后续若要重新锚定 detached junc，必须回到 T05/T06 对应模块做显式关系构建。

## GIS / 拓扑检查

- CRS 与坐标变换：Step1 不新增几何计算，继续沿用输入层 EPSG:3857 处理链路。
- 拓扑一致性：不 silent fix；仅调整 Step1 final fusion unit 的语义节点集合，最终 RCSD 拓扑仍由 Step2 硬审计证明。
- 几何语义可解释性：脱挂节点只代表“不作为本 Segment 主通道约束”，不代表该节点不存在或已正确锚定。
- 审计可追溯性：每个脱挂节点记录节点 ID 与失败 reason，summary 记录数量与原因分布。
- Step3 拓扑一致性：主通道仍由 Step2 retained RCSDRoad 承载；detached junc 的原 SWSDRoad 只作为局部 carrier 保留，避免 T09 arm lookup 断链。
- Step3 几何语义可解释性：局部保留 Road 维持原 SWSD 几何，不参与 RCSD 主通道 geometry 通过结论。
- Step3 审计可追溯性：replacement unit、Segment relation、summary 同时记录 detached junc 与保留 Road。
- 性能可验证性：脱挂逻辑只在 Step1 的当前 Segment 节点列表内做常数级判断，不增加图搜索。

## 回归

- 新增 `test_step1_detaches_high_grade_failed_junc_without_weakening_pair_or_special_junctions`：
  - 高等级 `junc_nodes` 的 `has_evd_not_yes / is_anchor_missing / is_anchor_not_eligible` 可脱挂并写审计字段。
  - final `junc_nodes / semantic_node_set` 不再包含脱挂节点。
  - 低等级 Segment、pair 端点失败、`kind_2=64` 特殊路口失败仍保持 rejected。
- 新增 `test_step3_retains_detached_junc_swsd_roads_as_local_carriers`：
  - detached junc 触达的原 SWSDRoad 以 `source=2` 保留。
  - 主通道原 SWSDRoad 仍被删除并由 RCSDRoad 替换。
  - Segment relation 标记 `replaced+retained_swsd`，并输出 `identity_retained_swsd` node map。
