# T01 - INTERFACE_CONTRACT

## 1. 文档状态
- 状态：`Accepted baseline contract`
- 当前阶段：`POC closeout and baseline handoff`
- 用途：固化当前 accepted baseline 的输入约束、输出契约与轮次衔接关系

## 2. 基础输入契约

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

### 2.3 语义路口契约
- 若 `mainnodeid` 有值，则该值为语义路口 ID
- 若 `mainnodeid` 为空，则 node 自身 `id` 为语义路口 ID
- `mainnodeid = NULL` 的 node 不是“非路口”
- 该 node 自身就是该语义路口的 mainnode

### 2.4 direction / trunk 语义契约
- `direction = 0 / 1`：
  - 视为两条方向相反的可通行 road
  - 在 pair 搜索中允许双向通行
  - 在 trunk / 最小闭环判定中允许镜像复用
- trunk 的闭环语义以语义路口为单元，而不是只看纯几何首尾闭合
- 若正反路径在 semantic-node-group 层面的有向图已经形成闭环，则即使物理几何不开环，也可成立 trunk
- 当前 trunk 允许：
  - 双向直连最小闭环
  - split-merge 分合混合通道
  - semantic-node-group closure

### 2.5 formway 契约
- `bit7 = 右转专用道`
  - Step2 through 压缩与 Node 刷新规则使用
- `bit8 = 左转专用道`
  - trunk 审计与排除使用

## 3. Step1 / Step2 契约

### 3.1 Step1
- Step1 输出：`pair_candidates`
- Step1 只负责候选发现
- Step1 不代表最终有效 pair

### 3.2 Step2
- Step2 输出：
  - `validated_pairs`
  - `rejected_pair_candidates`
  - `trunk_roads`
  - `segment_body_roads`
  - `step3_residual_roads`
  - `branch_cut_roads`
  - `pair_validation_table`
  - `segment_summary.json`
- `segment_body_roads` 不等于 all related roads
- `segment_body_roads` 只表达当前 validated pair 的 pair-specific road body
- `step3_residual_roads` 是待后续语义修正的附属结构输入

### 3.3 Step2 强规则契约
- 强规则 A：
  - non-trunk component 触达其他 terminate（非 A/B）即剔除
- 强规则 B：
  - non-trunk component 吃到其他 validated pair trunk 即剔除
- 强规则 C：
  - 过渡路口“同向进入 + 同向退出”停止追溯
  - mirrored bidirectional case 同样命中

## 4. refreshed Node / Road 契约

### 4.1 Node 输出字段
- `grade_2`
- `kind_2`

说明：
- `grade_2 / kind_2` 是持续滚动的当前语义字段
- 原始 `grade / kind` 不覆盖
- 仅 mainnode 记录执行业务改写
- subnode 保持当前输入值

### 4.2 Road 输出字段
- `s_grade`
- `segmentid`

说明：
- `segmentid` 表示该 road 已属于某个 validated pair 的 `segment_body`
- 已有非空 `segmentid / s_grade` 的 road 在后续轮次保持原值
- 后续轮次工作图剔除已有非空 `segmentid` 的 road

## 5. Step4 输入 / 输出契约

### 5.1 Step4 输入
- 使用上一轮 refreshed `nodes.geojson / roads.geojson`
- 节点筛选：
  - `grade_2 in {1,2}`
  - `kind_2 in {4,2048}`
  - `closed_con in {1,2}`
- 工作图：
  - 剔除已有非空 `segmentid` 的 road

### 5.2 Step4 层级边界契约
- 历史高等级边界 mainnode 对 Step4 同时具备：
  - `seed`
  - `terminate`
  - `hard-stop`
- 这些端点会显式注入 `force_seed_node_ids / force_terminate_node_ids`
- pair 搜索与 segment 收敛都必须使用同一套历史边界

### 5.3 Step4 输出
- `step4_pair_candidates.*`
- `step4_validated_pairs.*`
- `step4_rejected_pairs.*`
- `step4_trunk_roads.*`
- `step4_segment_body_roads.*`
- `step4_residual_roads.*`
- `historical_boundary_nodes.*`
- `target_case_audit.json`
- refreshed `nodes.geojson / roads.geojson`

## 6. Step5A / Step5B / Step5C 输入 / 输出契约

### 6.1 Step5A 输入
- 使用 Step4 refreshed `nodes.geojson / roads.geojson`
- 工作图剔除历史已有非空 `segmentid` 的 road
- 节点筛选：
  - `closed_con in {1,2}`
  - 且
    - `kind_2 in {4,2048}` 且 `grade_2 in {1,2}`
    - 或 `kind_2 = 4` 且 `grade_2 = 3`
- 历史高等级边界 `S2 + Step4` 端点并入 `seed / terminate`

### 6.2 Step5B 输入
- 使用 Step5A residual graph
- 工作图继续剔除 Step5A 新 `segment_body` road
- 不刷新属性
- 节点筛选：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`
- 历史高等级边界 `S2 + Step4` 端点并入 `seed / terminate`
- `Step5A` 新端点仅用于 Step5B `hard-stop`

### 6.3 Step5C 输入
- 使用 Step5B residual graph
- 工作图继续剔除 Step5B 新 `segment_body` road
- 不刷新属性
- 节点筛选：
  - `closed_con in {1,2}`
  - `kind_2 in {1,4,2048}`
  - `grade_2 in {1,2,3}`
- 历史高等级边界 `S2 + Step4` 端点并入 `seed / terminate`
- `Step5A / Step5B` 新端点仅用于 Step5C `hard-stop`

### 6.4 Step5 分阶段关系
- Step5A、Step5B、Step5C 之间只剔除新 `segment_body` road
- Step5A、Step5B、Step5C 之间不刷新属性
- 三阶段结束后才统一刷新：
  - `grade_2`
  - `kind_2`
  - `s_grade`
  - `segmentid`

### 6.5 Step5 输出
- Step5A：
  - `step5a_pair_candidates.*`
  - `step5a_validated_pairs.*`
  - `step5a_rejected_pairs.*`
  - `step5a_trunk_roads.*`
  - `step5a_segment_body_roads.*`
  - `step5a_residual_roads.*`
- Step5B：
  - `step5b_pair_candidates.*`
  - `step5b_validated_pairs.*`
  - `step5b_rejected_pairs.*`
  - `step5b_trunk_roads.*`
  - `step5b_segment_body_roads.*`
  - `step5b_residual_roads.*`
- Step5C：
  - `step5c_pair_candidates.*`
  - `step5c_validated_pairs.*`
  - `step5c_rejected_pairs.*`
  - `step5c_trunk_roads.*`
  - `step5c_segment_body_roads.*`
  - `step5c_residual_roads.*`
- merged：
  - `step5_validated_pairs_merged.*`
  - `step5_segment_body_roads_merged.*`
  - `step5_residual_roads_merged.*`
- refreshed：
  - `nodes.geojson`
  - `roads.geojson`
  - `nodes_step5_refreshed.geojson`
  - `roads_step5_refreshed.geojson`
  - `step5_summary.json`
  - `step5_mainnode_refresh_table.csv`

### 6.6 Step5 新 road 写入
- Step5A / Step5B / Step5C 本轮新 road 写入：
  - `s_grade = "0-2双"`
  - `segmentid = "A_B"`

## 7. 当前推荐基线契约
- 当前推荐输入基线：
  - 最新一轮 refreshed `nodes.geojson`
  - 最新一轮 refreshed `roads.geojson`
- 当前推荐输出基线：
  - Step5 refreshed `nodes.geojson / roads.geojson`
  - 对应 merged 审计输出

## 8. 当前不承诺内容
- Step6 输入 / 输出契约
- 单向 Segment 输出契约
- Step3 完整语义修正契约
- 完整多轮闭环治理契约
