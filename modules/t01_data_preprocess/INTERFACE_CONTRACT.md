# T01 - INTERFACE_CONTRACT

## 1. 文档状态
- 状态：`POC Contract Draft`
- 当前阶段：`Step5A/Step5B staged residual graph segment construction`
- 用途：固化当前原型阶段的输入、输出与审计契约

## 2. 输入契约

### 2.1 Road 输入
- 支持格式：`Shp` / `GeoJSON`
- 几何类型：`LineString`
- 强依赖字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`
- 多轮输入依赖字段：
  - `s_grade`
  - `segmentid`

### 2.2 Node 输入
- 支持格式：`Shp` / `GeoJSON`
- 几何类型：`Point`
- 强依赖字段：
  - `id`
  - `kind`
  - `grade`
  - `closed_con`
  - `mainnodeid`
- 多轮输入依赖字段：
  - `grade_2`
  - `kind_2`

### 2.3 Step5A 输入契约
- 使用 Step4 refreshed `Node / Road`
- 工作图剔除历史已有非空 `segmentid` 的 road
- seed / terminate 条件：
  - `closed_con in {1,2}`
  - 且
    - `kind_2 in {4,2048}` 且 `grade_2 in {1,2}`
    - 或 `kind_2 = 4` 且 `grade_2 = 3`

### 2.4 Step5B 输入契约
- 使用 Step5A residual graph
- 工作图继续剔除 Step5A 新 `segment_body` road
- 不刷新属性
- seed / terminate 条件：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`

### 2.5 formway 当前启用口径
- `bit7 = 右转专用道`
  - through incident degree 可用于压缩
  - Node 刷新规则 3 可用于判定“其余全是右转专用道”
- `bit8 = 左转专用道`
  - trunk 审计与排除

## 3. Step1 / Step2 基线输出契约
- Step1 输出：`pair_candidates`
- Step2 输出：`validated / rejected + trunk + segment_body + step3_residual`

## 4. Step5A / Step5B 输出契约

### 4.1 Step5A
- `step5a_pair_candidates.*`
- `step5a_validated_pairs.*`
- `step5a_rejected_pairs.*`
- `step5a_trunk_roads.*`
- `step5a_segment_body_roads.*`
- `step5a_residual_roads.*`

### 4.2 Step5B
- `step5b_pair_candidates.*`
- `step5b_validated_pairs.*`
- `step5b_rejected_pairs.*`
- `step5b_trunk_roads.*`
- `step5b_segment_body_roads.*`
- `step5b_residual_roads.*`

### 4.3 Step5 merged
- `step5_validated_pairs_merged.*`
- `step5_segment_body_roads_merged.*`
- `step5_residual_roads_merged.*`

## 5. Step5 refreshed 输出契约

### 5.1 Node 输出字段
- `grade_2`
- `kind_2`

说明：
- 基于 Step5A + Step5B 的 validated pair 并集和累计 `segmentid` 结果回写
- 原始 `grade / kind` 不覆盖
- 只对 mainnode 记录做业务改写
- subnode 保持输入值

### 5.2 Road 输出字段
- `s_grade`
- `segmentid`

说明：
- 历史已有非空 `segmentid / s_grade` 保持原值
- 本轮新 `segment_body` road 写入：
  - `s_grade = "0-2双"`
  - `segmentid = "A_B"`

### 5.3 Step5 refreshed 输出文件
- `nodes.geojson`
- `roads.geojson`
- `nodes_step5_refreshed.geojson`
- `roads_step5_refreshed.geojson`
- `step5_summary.json`
- `step5_mainnode_refresh_table.csv`

### 5.4 step5_summary 最少字段
- `step5a_input_node_count`
- `step5a_seed_count`
- `step5a_terminate_count`
- `step5a_validated_pair_count`
- `step5a_new_segment_road_count`
- `step5b_input_node_count`
- `step5b_seed_count`
- `step5b_terminate_count`
- `step5b_validated_pair_count`
- `step5b_new_segment_road_count`
- `step5_removed_historical_segment_road_count`
- `step5_removed_step5a_segment_road_count`
- `step5_total_new_segment_road_count`
- `node_rule_keep_pair_count`
- `node_rule_single_segment_count`
- `node_rule_right_turn_only_count`
- `node_rule_new_t_count`
- `multi_segment_mainnode_kept_count`

### 5.5 step5_mainnode_refresh_table 最少字段
- `mainnode_id`
- `participates_in_step5a_pair`
- `participates_in_step5b_pair`
- `current_grade_2`
- `current_kind_2`
- `current_closed_con`
- `new_grade_2`
- `new_kind_2`
- `unique_segmentid_count`
- `nonsegment_road_count`
- `nonsegment_all_right_turn_only`
- `nonsegment_has_in`
- `nonsegment_has_out`
- `applied_rule`

## 6. 当前不承诺内容
- 完整 Step3 语义修正
- Step6 构建契约
- 多轮闭环
- 单向 Segment 输出契约
