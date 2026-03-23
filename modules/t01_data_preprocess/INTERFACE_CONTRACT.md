# T01 - INTERFACE_CONTRACT

## 1. 文档状态
- 状态：`accepted baseline contract / current active baseline`
- 用途：固化当前 working layer、roundabout preprocessing、Step1-Step6、freeze compare 与 Step2 same-stage arbitration 的接口契约。

## 2. 官方输入契约
- 官方推荐输入统一为：
  - `nodes.geojson`
  - `roads.geojson`
- Shapefile 仅保留读取兼容层，不再作为官方契约或官方推荐入口。

## 3. Working Layers

### 3.1 Working Nodes
- 必备字段：
  - `id`
  - `mainnodeid`
  - `working_mainnodeid`
  - `closed_con`
  - `grade`
  - `kind`
  - `grade_2`
  - `kind_2`
- 初始化：
  - `grade_2 = grade`
  - `kind_2 = kind`
  - `working_mainnodeid = mainnodeid`
- `working_mainnodeid` 是内部 working 语义字段，运行期继续维护并优先供 Step1-Step6 使用。
- 对外公开 `nodes.geojson / inner_nodes.geojson` 不显式输出 `working_mainnodeid`。
- 默认情况下，`mainnodeid` 保持原始输入值；例外是 roundabout preprocessing，可同步改写 `mainnodeid / working_mainnodeid`。

### 3.2 Working Roads
- 必备字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`
  - `road_kind`
  - `segmentid`
  - `sgrade`
- 初始化：
  - `segmentid = null`
  - `sgrade = null`
- 读取兼容层允许识别：
  - `s_grade`
  - `segment_id`
  - `Segment_id`
- 新输出不得再写回上述 legacy 字段。

## 4. 正式业务字段
- Step1-Step6 业务判断统一使用：
  - node：`grade_2 / kind_2 / closed_con / working_mainnodeid`
  - road：`segmentid / sgrade / road_kind`
- raw `grade / kind` 仅保留输入、展示与审计用途。
- 对外公开 node 图层正式持久化字段：
  - `mainnodeid`
  - `grade_2`
  - `kind_2`
  - `closed_con`

## 5. 预处理阶段契约

### 5.1 bootstrap
- official runner 进入模块后先建立 working `nodes / roads`。

### 5.2 roundabout preprocessing
- 位置：bootstrap 之后、Step1 之前。
- roundabout `mainnode`：
  - `grade_2 = 1`
  - `kind_2 = 64`
- roundabout member node：
  - `grade_2 = 0`
  - `kind_2 = 0`
- roundabout 全组 node：
  - `mainnodeid = roundabout mainnode`
  - `working_mainnodeid = roundabout mainnode`
- roundabout 是当前唯一允许显式修正公开 `mainnodeid` 的场景。

## 6. Step1-Step5C accepted 契约
- Step1：只输出 `pair_candidates`
- Step2：输出 `validated / rejected / trunk / segment_body / step3_residual`
- Step4、Step5A、Step5B：strict staged residual graph
- Step5C：adaptive barrier fallback
- 全流程统一前置过滤：
  - node：`closed_con in {2,3}`
  - road：`road_kind != 1`
- 全流程右转专用道约束：
  - `formway bit7` 的右转专用道不得进入 Step1-Step5 的 Segment 构建图
  - 若节点去除右转专用道后不再构成真实路口，则该节点不得出现在：
    - `pair_candidates` 的 through / terminate 判定
    - Step4 / Step5 residual graph 的 boundary / endpoint pool
    - final Segment 的语义路口集合
  - 该类节点即使 `kind_2 = 1`，也不得仅因右转专用道挂接而被保留为构段路口
- 全流程统一 gate：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- Step2 `segment_body` 中的单侧旁路系统仅允许：
  - side component 自身全部由单向 road 构成
  - attachment flow 满足 `single_departure_return`
  - corridor 与主路平行方向一致
- 若 side component 包含任意双向 road，则不得作为合法单侧旁路保留，统一进入 `step3_residual`
- Step2 / Step4 / Step5 `single-pair validation` 额外前置：
  - 若 trunk candidate 命中 `bidirectional_minimal_loop`
  - 且内部路径呈“弱 connector node 串接 + 内部 T-support / support anchor 闭合”
  - 则该 pair 必须直接以 `t_junction_vertical_tracking_blocked` 拒绝
  - 只要该 T 型路口不是 segment 起点 / 终点，该规则在 Step2 / Step4 / Step5A / Step5B / Step5C 都必须生效
  - 该类 pair 不得进入 same-stage pair arbitration，也不得在后续阶段重新构出

## 7. Step2 same-stage pair arbitration 契约

### 7.1 触发位置
- Step2 先执行单 pair 合法性验证。
- same-stage pair arbitration 发生在：
  - `single-pair validation`
  - 之后
  - final `validated_pairs / segment_body / step3_residual`
  - 之前

### 7.2 输入契约
- 仲裁池只接收 `single_pair_legal = true` 的 pair candidate options。
- 仲裁对象为：
  - `pair_id`
  - 加上该 pair 对应的 `trunk / segment_body candidate` 组合
- conflict component 识别当前至少覆盖：
  - `trunk_road_ids` overlap
  - `segment_body candidate / segment_body` overlap
  - corridor overlap

### 7.3 输出契约
- Step2 final `validated_pairs` 仅由仲裁 winners 构成。
- 单 pair 合法但仲裁落选的 pair，不再参与 final `segment_body` 固化。
- 仲裁结果必须显式写出：
  - `single_pair_legal`
  - `arbitration_status`
  - `arbitration_component_id`
  - `arbitration_option_id`
  - `lose_reason`

### 7.4 仲裁审计输出
- `pair_conflict_table.csv`
  - `pair_id`
  - `conflict_pair_id`
  - `conflict_type`
  - `shared_road_count`
  - `shared_trunk_road_count`
- `pair_conflict_components.json`
  - `component_id`
  - `pair_ids`
  - `component_size`
  - `contested_road_ids`
  - `strong_anchor_node_ids`
  - `exact_solver_used`
  - `fallback_greedy_used`
  - `selected_option_ids`
- `pair_arbitration_table.csv`
  - `pair_id`
  - `component_id`
  - `single_pair_legal`
  - `arbitration_status`
  - `endpoint_boundary_penalty`
  - `strong_anchor_win_count`
  - `corridor_naturalness_score`
  - `contested_trunk_coverage_count`
  - `contested_trunk_coverage_ratio`
  - `internal_endpoint_penalty`
  - `body_connectivity_support`
  - `semantic_conflict_penalty`
  - `lose_reason`
- `corridor_conflict_roads.geojson`
- `validated_pairs_final.csv`
- `target_conflict_audit_xxxs7.json`

## 8. Step5C 契约

### 8.1 输入与中间集合
- `rolling endpoint pool`
- `protected hard-stop set`
- `demotable endpoint set`
- `actual terminate barriers`

### 8.2 当前 accepted 口径
- `rolling endpoint pool`
  - 历史 endpoint mainnode
  - 加上当前 residual graph 上满足：
    - `closed_con in {2,3}`
    - `kind_2 in {4,64,2048}`
    - `grade_2 in {1,2,3}`
    的语义节点
- `protected hard-stop set`
  - 当前只保留 roundabout `mainnode`：`kind_2 = 64` 且 `closed_con in {2,3}`
- `demotable endpoint set`
  - `rolling endpoint pool - protected hard-stop set`
- `actual terminate barriers`
  - `protected hard-stop set`
  - 加上当前 residual graph 上未被 demote 的真实 barrier endpoint

## 9. Step6 输出契约

### 9.1 输入
- latest refreshed `nodes.geojson / roads.geojson`
- Step6 不重新做构段搜索
- official runner 中，Step6 优先复用 Step5 内存态 `working_mainnodeid`
- standalone 读取公开 `nodes.geojson` 时，若未显式带出 `working_mainnodeid`，则回退 `mainnodeid`，再为空时回退 node `id`

### 9.2 输出
- `segment.geojson`
- `inner_nodes.geojson`
- `segment_error.geojson`
- `segment_error_s_grade_conflict.geojson`
- `segment_error_grade_kind_conflict.geojson`
- `segment_summary.json`
- `segment_build_table.csv`
- `inner_nodes_summary.json`

### 9.3 语义
- `segment.geojson`
  - `id = segmentid`
  - `sgrade`
  - `pair_nodes`
  - `junc_nodes`
  - `roads`
- `pair_nodes`
  - `A_B -> A,B`
  - `A_B_N -> A,B`
- `inner_nodes.geojson`
  - 完整复制被某个 Segment 完全内含的 node 原字段
  - 仅追加 `segmentid`
  - 不显式输出 `working_mainnodeid`

## 10. official end-to-end 输出
- `nodes.geojson`
- `roads.geojson`
- `segment.geojson`
- `inner_nodes.geojson`
- `segment_error.geojson`
- `segment_error_s_grade_conflict.geojson`
- `segment_error_grade_kind_conflict.geojson`
- `validated_pairs_skill_v1.csv`
- `segment_body_membership_skill_v1.csv`
- `trunk_membership_skill_v1.csv`
- `validated_pairs_final.csv`
- `pair_conflict_table.csv`
- `pair_conflict_components.json`
- `pair_arbitration_table.csv`
- `corridor_conflict_roads.geojson`
- `skill_v1_manifest.json`
- `skill_v1_summary.json`

## 11. freeze compare 契约
- compare 重点仍是业务结果一致性：
  - `validated_pairs`
  - `segment_body_membership`
  - `trunk_membership`
  - refreshed `nodes / roads` 语义 hash
- roads compare 必须兼容：
  - baseline `s_grade`
  - current `sgrade`
- 若只存在 schema 迁移差异，应标记为 `SCHEMA_MIGRATION_DIFFERENCE`，不能误报业务 FAIL。
