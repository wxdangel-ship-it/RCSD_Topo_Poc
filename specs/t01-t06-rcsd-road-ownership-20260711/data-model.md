# T01/T06 RCSD Road 归属升级数据模型

## 1. SWSD Segment

新增稳定类型：

```text
segment_type = normal | advance_right
```

### normal

- 使用现有 `pair_nodes / junc_nodes / roads / sgrade`；
- Pair 与非豁免 Junc 都参与锚定与替换门禁；
- 进入 T06 Step1/Step2。

### advance_right

- `roads` 全部满足 SWSD 提右属性；
- 不与普通 Road 混合；
- 不参与 Pair/Junc 锚定；
- 直接交由 T06 Step3 提右逻辑消费；
- 替换结果单独统计，避免改变旧普通 Segment 分母。

## 2. RCSD Road Ownership

以原始 T05 `rcsdroad_out` 的 `id` 为唯一键，一条原始 RCSD Road 恰好一条记录。

| 字段 | 语义 |
|---|---|
| `rcsd_road_id` | 原始 RCSD Road id，唯一 |
| `owner_type` | `single_segment / multi_segment_connectivity / reality_change / unresolved_exception` |
| `owner_key` | Segment id、connectivity group id、reality change id 或 unresolved id |
| `owner_segment_id` | single owner 时唯一 Segment id |
| `owner_segment_type` | `normal / advance_right` |
| `related_segment_ids` | connectivity group 关联 Segment；不表示重复 owner |
| `candidate_segment_ids` | 归属过程中产生的候选，不计正式 owner |
| `ownership_status` | `resolved / unresolved` |
| `ownership_confidence` | `exact / high / review_required / unresolved` |
| `ownership_evidence_types` | relation、拓扑走廊、端点挂接、Segment geometry、排他边界等 |
| `ownership_reason` | 人可读根因 |
| `replacement_status` | `used / not_used / blocked` |
| `replacement_action` | `replace_segment / replace_main_retain_side / include_connectivity / hold` |
| `final_road_ids` | copy-on-write 切分后的最终 F-RCSD Road id |
| `risk_flags` | 风险与人工复核标记 |

不允许一个 `rcsd_road_id` 生成多条 ownership 记录。多 Segment 关系只能放在单条记录的 `related_segment_ids`。

## 3. Multi-Segment Connectivity Group

| 字段 | 语义 |
|---|---|
| `connectivity_group_id` | 稳定 group id |
| `rcsd_road_ids` | 组内原始 RCSD Road，彼此不重复 |
| `related_segment_ids` | 两端或多端关联 Segment |
| `terminal_node_ids` | 连通组端点 |
| `terminal_attachment_evidence` | 每个端点挂接到哪个 Segment/Road 的证据 |
| `connectivity_kind` | `second_degree_bridge / uturn_connector / parallel_road_connector / other_reviewed` |
| `connectivity_status` | `attachable / unattachable / ambiguous` |
| `replacement_status` | `used / not_used` |
| `blocked_reason` | 开放端点、非线性、触达保护锚点、候选歧义等 |
| `count_in_rcsd_road_metric` | attachable 且 used 时为 true |
| `count_in_segment_metric` | 固定 false |

`connectivity_status=ambiguous` 且无法确定 `related_segment_ids` 时，不生成正式 group，转入 `unresolved_exception`。

## 4. Segment Construction Audit

普通 Segment 每个 id 一条：

| 字段 | 语义 |
|---|---|
| `swsd_segment_id` | Segment id |
| `pair_anchor_status` | Pair 锚定完整度 |
| `junc_anchor_status` | 非豁免 Junc 锚定完整度 |
| `main_corridor_status` | `complete / incomplete / direction_failed / disconnected` |
| `side_road_status` | `complete / missing / not_applicable` |
| `construction_class` | `2a_complete / 2b_main_complete_side_missing / 2c_not_replaceable / pair_only / pair_incomplete` |
| `step2_replaceable` | 是否进入 Step2 白名单 |
| `segment_replacement_status` | `replaced / retained_swsd / replaced+retained_swsd` |
| `root_cause` | 不能替换的具体原因 |

规则：

- `2a_complete`：主干和附属侧路完整；
- `2b_main_complete_side_missing`：只允许附属侧路缺失，主干必须完整；
- Pair 成功但任一 Junc 未锚定：可继续 ownership 分析，但不得 Segment replace；
- Pair 不完整：不得 Segment replace，ownership 继续收敛。

## 5. Reality Change

`reality_change` 不是零候选同义词，必须记录：

- 检查过的普通 Segment、提右 Segment和 connectivity group；
- 排除原因；
- 现实新增/变化证据；
- 人工复核状态。

## 6. Unresolved Exception

必须记录：

- `candidate_segment_ids`；
- `attempted_rules`；
- `failed_evidence`；
- `why_not_reality_change`；
- `why_not_connectivity_group`；
- `manual_review_required`；
- `next_owner`。

任何只因距离接近、buffer 多命中或现有 class=6 而进入 unresolved 的记录均不合格。

## 7. 指标实体

### RCSD Road 替换率

分子包含最终 `replacement_status=used` 的：

- 普通 Segment RCSD Road；
- 提右 Segment RCSD Road；
- attachable multi-segment connectivity RCSD Road。

### Segment 替换率

- 普通 Segment 按 Step2/Step3 正式替换结果统计；
- multi-segment connectivity 固定不计；
- 新增提右 Segment初期单列统计，避免改变普通 Segment 历史基线；待六 Case稳定后再决定是否增加综合 Segment 指标。

### Final F-RCSD Topology Fail

正式 topology 审计行新增：

- `final_topology_category`：`segment_transition / independent_attachment / 空`；
- `final_topology_object_key`：逐层稳定业务主键；
- `counts_in_final_frcsd_topology_fail`：是否计入正式指标；
- `topology_road_lineage_id`：split 前稳定 Road lineage；
- `topology_endpoint_index`：端点侧别。

`final_frcsd_topology_fail_count` 是 `counts_in_final_frcsd_topology_fail=true` 行的非空 `final_topology_object_key` 去重数。兼容 `topology_connectivity_fail_count` 继续统计全部 fail 行，不参与最终 F-RCSD 正确性结论。

## 8. 状态转换

```text
RCSD Road candidate evidence
  -> single_segment resolved
  -> multi_segment_connectivity resolved
  -> reality_change confirmed
  -> unresolved_exception evidence_exhausted

single_segment(normal)
  -> anchors complete + Step2 replaceable
      -> segment replaced
      -> main replaced + side SWSD retained
  -> anchors incomplete or quality failed
      -> owner retained, segment not replaced

multi_segment_connectivity
  -> attachable -> include_connectivity -> RCSD Road metric only
  -> unattachable -> not_used, retain attribution
```
