# T01 数据预处理规格草案

## 1. 文档状态
- 状态：`Draft / hierarchical boundary fix before poc closeout`
- 当前阶段：允许编码、测试与外网 `XXXS` 验证
- 当前目标：先修复 visual audit 已暴露的问题，再进入 POC 收尾与基线提交准备

## 2. 当前轮次框架
- 首轮已完成：
  - Step1 仅输出 `pair_candidates`
  - Step2 完成 `validated / rejected / trunk / segment_body / step3_residual`
  - 首轮完成后刷新 `grade_2 / kind_2 / s_grade / segmentid`
- Step4：
  - 基于上一轮 refreshed `Node / Road`
  - 在 residual graph 上继续构段
  - 结束后再次刷新 `grade_2 / kind_2 / s_grade / segmentid`
- Step5：
  - 基于 Step4 refreshed `Node / Road`
  - 拆分为 `Step5A / Step5B`
  - Step5A 与 Step5B 之间只剔除新 `segment_body` road，不刷新属性
  - Step5A + Step5B 完成后统一刷新 `Node / Road`
- Step6：
  - 尚未启动

## 3. Step1 / Step2 基线语义

### 3.1 Step1
- Step1 只负责发现 `pair_candidates`
- Step1 不代表最终有效 pair

### 3.2 Step2
- Step2 负责：
  - `pair_candidate -> validated / rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- `segment_body` 只表达当前 validated pair 的 pair-specific road body
- 右转专用道误纳入与 `791711` T 型双向退出误追溯问题已完成修复，不得回退
- `direction = 0 / 1` 的双向 road，在当前语义体系中视为两条方向相反的可通行 road
- 因此在 trunk / 最小闭环判定中，若 `A -> B` 与 `B -> A` 完全镜像地复用同一组双向 road，则该镜像往返本身就是合法最小闭环
- 这不是新的 trunk 类型，而是现有方向语义在最小闭环判定中的直接落实

## 4. 层级边界规则

### 4.1 规则定义
- 更低等级轮次构段，必须在更高等级历史路口处中断
- 当前轮的 `terminate / hard-stop` 口径必须包含：
  - 当前轮自身 `seed / terminate`
  - 更高等级历史轮次 validated pair 的端点 mainnode

### 4.2 当前实现
- Step4：
  - 历史边界取自已完成的 `S2` validated pair 端点 mainnode
- Step5A：
  - 历史边界取自已完成的 `S2 + Step4` validated pair 端点 mainnode
- Step5B：
  - 历史边界取自已完成的 `S2 + Step4 + Step5A` validated pair 端点 mainnode

### 4.3 作用范围
- 该边界规则必须同时作用于：
  1. pair candidate BFS 搜索阶段
  2. `segment_body` 候选通道 / component 收敛阶段
- 不能只挡住 pair，不挡 segment
- 对 Step4 / Step5 这类 residual graph 轮次，凡是命中当前轮 `seed / terminate` 的节点，一律不得再作为当前轮 `through_node`
- 即：
  - 当前轮合法端点必须真正作为端点参与搜索
  - 不能再出现“命中当前轮输入规则，但被 through 吞掉、无法作为 search seed 启动”的情况

## 5. `mainnodeid = NULL` 单点路口规则
- 若 node 的 `mainnodeid = NULL`，则该 node 自身 `id` 即为语义路口 ID
- 若该语义路口仅包含该单个 node，且命中当前轮输入规则，则它必须被视为合法语义路口
- 该类单点语义路口在当前轮必须：
  - 进入 `seed / terminate` 判定
  - 一旦命中当前轮 `seed / terminate`，不得在同一轮再被作为 `through_node`
- 该规则用于避免把本应作为当前轮端点的单点路口误吞为 through 中间点
## 6. Step4 规格

### 5.1 输入
- 输入使用上一轮 refreshed `nodes.geojson / roads.geojson`
- 节点筛选使用：
  - `grade_2`
  - `kind_2`
  - `closed_con`
- 工作图剔除：
  - 历史已有非空 `segmentid` 的 road

### 5.2 输出
- `step4_pair_candidates.*`
- `step4_validated_pairs.*`
- `step4_rejected_pairs.*`
- `step4_trunk_roads.*`
- `step4_segment_body_roads.*`
- `step4_residual_roads.*`
- `historical_boundary_nodes.*`
- `target_case_audit.json`
- refreshed `nodes.geojson / roads.geojson`

## 7. Step5 规格

### 6.1 Step5A 输入集合
- `closed_con in {1,2}`
- 且满足以下任一：
  - `kind_2 in {4,2048}` 且 `grade_2 in {1,2}`
  - `kind_2 = 4` 且 `grade_2 = 3`

### 6.2 Step5B 输入集合
- 在 Step5A residual graph 上
- 对所有满足以下条件的剩余双向路口继续做收尾构段：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`

### 6.3 Step5A / Step5B 关系
- Step5A 是优先轮
- Step5B 是 residual graph 上所有剩余双向路口的收尾轮
- Step5A 与 Step5B 之间：
  - 只剔除 Step5A 新 `segment_body` road
  - 不刷新 `grade_2 / kind_2 / s_grade / segmentid`

### 6.4 Step5 输出
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
- merged：
  - `step5_validated_pairs_merged.*`
  - `step5_segment_body_roads_merged.*`
  - `step5_residual_roads_merged.*`
  - `historical_boundary_nodes.*`
- refreshed：
  - `nodes.geojson / roads.geojson`
  - `nodes_step5_refreshed.geojson / roads_step5_refreshed.geojson`
  - `step5_summary.json`
  - `step5_mainnode_refresh_table.csv`

## 8. 当前轮次待解决问题
- Step4 target cases 需要保留 case 级审计证据，不能只给总括性解释
- Step5 在引入历史边界后已去掉错误跨级穿越，但仍需继续视觉审查，不得提前进入 closeout

## 9. 当前不纳入范围
- POC closeout / baseline handoff
- 启动 Step6
- 重写 Step1 / Step2 核心算法
- 回退已通过的 tighten 修复
