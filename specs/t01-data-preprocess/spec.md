# T01 数据预处理 Accepted Baseline 规格

## 1. 文档状态
- 状态：`Accepted baseline / POC closeout`
- 当前阶段：`POC closeout and baseline handoff`
- 本文用途：
  - 固化当前分支已验证通过的 T01 业务语义
  - 作为后续正式模块完整构建的业务基线

## 2. 当前 accepted architecture

### 2.1 单轮 POC 起点
- Step1：
  - 只输出 `pair_candidates`
  - 不代表最终有效 pair
- Step2：
  - 负责 `validated / rejected`
  - 负责 `trunk`
  - 负责 `segment_body`
  - 负责 `step3_residual`

### 2.2 residual graph 外层轮次
- Step4：
  - 使用上一轮 refreshed `Node / Road`
  - 在 residual graph 上继续构段
  - 结束后刷新 `grade_2 / kind_2 / s_grade / segmentid`
- Step5：
  - 使用 Step4 refreshed `Node / Road`
  - 拆分为 `Step5A / Step5B / Step5C`
  - 三阶段之间只剔除新 `segment_body` road，不刷新属性
  - `Step5A + Step5B + Step5C` 完成后统一刷新 `Node / Road`

### 2.3 当前不纳入 accepted baseline 的内容
- Step6
- 单向 Segment
- Step3 完整语义归并
- 完整多轮闭环治理
- 一步到位总编排器

## 3. Step1 / Step2 accepted 语义

### 3.1 Step1
- Step1 只负责发现 `pair_candidates`
- Step1 不代表最终有效 pair
- 最终有效性由后续构段 / 验证阶段判定

### 3.2 Step2
- Step2 输出：
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- `segment_body` 不再表达 all related roads
- `segment_body` 只表达当前 validated pair 的 pair-specific road body
- 弱规则不在 Step2 中做硬删除
- 边界模糊但未命中强规则的结构统一进入 `step3_residual`

### 3.3 Step2 三条强规则
- 强规则 A：
  - non-trunk component 触达其他 terminate node / 其他候选终止路口
  - 且该 terminate 不是当前 pair 的 `A / B`
  - 则该 component 不属于当前 pair `segment_body`
- 强规则 B：
  - non-trunk component 吃到其他 validated pair 的 trunk road
  - 则该 component 不属于当前 pair `segment_body`
- 强规则 C：
  - 过渡路口出现“同向进入 + 同向退出”时
  - 当前 pair 不得沿该方向继续追溯
  - mirrored bidirectional case 同样纳入命中

### 3.4 已闭环修复的问题
- 右转专用道误纳入 `segment_body` 的问题已解决
- `node = 791711` 的 T 型双向退出误追溯问题已解决

## 4. trunk 与最小闭环的 accepted 语义

### 4.1 双向 road 语义
- `direction = 0 / 1` 的双向 road，在当前语义体系中视为两条方向相反的可通行 road
- 因此在 trunk / 最小闭环判定中：
  - `A -> B` 可以走双向 road 的一个方向
  - `B -> A` 可以走同一条双向 road 的反方向
- 若两方向仅镜像复用同一条或同一组双向 road，该结构本身就是合法最小闭环

### 4.2 分合混合通道
- trunk 判定不能只接受“物理上两条完全分离的 road”
- 在合法 Segment 中，允许出现：
  - 先分成两条方向不同的 road，再汇入一条双向 road
  - 先汇入一条双向 road，再重新分成两条方向不同的 road
  - 先分再合、合后再分，以及同类组合
- 只要整体上仍满足：
  - 存在合法的 `A -> B` 与 `B -> A` 通道
  - 未跨越历史高等级边界
  - 未违反当前轮次的 trunk / segment 提取边界
  - 最终仍表达同一条合法路段本体
- 则该结构应视为合法 trunk / 最小闭环的一部分

### 4.3 semantic-node-group closure
- trunk 的闭环语义以“语义路口 / semantic-node-group”为单元
- 不能只用“物理几何是否首尾严格闭合”做唯一判断
- 若正反路径在语义路口层面的有向图已经形成合法闭环，则即使因为同一语义路口组内不同 member node 的物理坐标差异导致几何不开环，也应视为 trunk 成立
- 该口径同样适用于：
  - `mainnodeid` 聚合后的多 node 路口
  - `mainnodeid = NULL` 的单 node 路口

## 5. 层级边界 / 历史高等级边界

### 5.1 基本语义
- 更低等级构段必须在更高等级历史路口中断
- 当前轮 terminate / hard-stop 必须包含历史高等级边界 mainnode
- 该边界同时作用于：
  - pair 搜索阶段
  - segment 收敛阶段

### 5.2 当前 accepted 实现口径
- 对当前轮而言，历史高等级边界 mainnode 具有三重语义：
  - `seed`
  - `terminate`
  - `hard-stop`
- 搜索命中历史边界时的正确行为是：
  - 记为 terminal candidate
  - 然后停止继续穿越边界另一侧
- 不允许出现：
  - 只做 hard-stop 但不允许成对
  - pair 被挡住但 segment 从边界另一侧继续吸收

## 6. `mainnodeid = NULL` 单点路口语义
- 若 `mainnodeid` 为空，则该 node 自身就是一个独立语义路口
- 该 node 自身即该语义路口的 mainnode
- `mainnodeid = NULL` 不等于“不是路口”
- 只要满足当前轮输入规则，就必须正常进入 `seed / terminate`
- 对 Step4 / Step5 这类 residual graph 轮次：
  - 凡是命中当前轮 `seed / terminate` 的节点
  - 一律不得再作为当前轮 `through_node`

## 7. residual graph 多轮语义
- 后续轮次以 refreshed `Node / Road` 为输入基础
- 使用刷新后的 `grade_2 / kind_2` 作为节点筛选依据
- 已有非空 `segmentid` 的 road 在后续轮次工作图中剔除，视为不存在
- 该剔除是工作图层面的逻辑剔除，不是物理删除原始 road
- residual graph 已成为多轮构段的正式工作方式
- 当前 accepted 外层轮次语义为：
  - 首轮：Step1 / Step2
  - 后续：Step4 / Step5A / Step5B / Step5C

## 8. Step4 accepted 规则

### 8.1 输入约束
- 输入使用上一轮 refreshed `nodes.geojson / roads.geojson`
- 当前轮输入节点满足：
  - `grade_2 in {1,2}`
  - `kind_2 in {4,2048}`
  - `closed_con in {1,2}`
- 当前轮 `seed / terminate` 由两部分并集构成：
  - 当前轮按 `grade_2 / kind_2 / closed_con` 命中的节点
  - 历史高等级边界端点 mainnode

### 8.2 工作图约束
- 工作图剔除历史已有非空 `segmentid` 的 road
- 历史边界同时用于：
  - pair candidate 搜索 hard-stop
  - `segment_body` component 收敛 hard-stop

### 8.3 输出与刷新
- Step4 输出：
  - `step4_pair_candidates.*`
  - `step4_validated_pairs.*`
  - `step4_rejected_pairs.*`
  - `step4_trunk_roads.*`
  - `step4_segment_body_roads.*`
  - `step4_residual_roads.*`
  - `historical_boundary_nodes.*`
  - `target_case_audit.json`
- Step4 结束后刷新：
  - `grade_2`
  - `kind_2`
  - `s_grade = "0-1双"`
  - `segmentid`

## 9. Step5 accepted 规则

### 9.1 Step5A 输入约束
- `closed_con in {1,2}`
- 且满足以下任一：
  - `kind_2 in {4,2048}` 且 `grade_2 in {1,2}`
  - `kind_2 = 4` 且 `grade_2 = 3`
- 历史高等级边界端点会并入 Step5A `seed / terminate`

### 9.2 Step5B 输入约束
- 在 Step5A residual graph 上运行
- 当前轮输入节点满足：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`
- Step5B `seed / terminate` 额外并入：
  - `S2 + Step4` 的历史高等级边界端点
- `Step5A` 当轮新端点：
  - 仅用于 Step5B `hard-stop`
  - 不回注入 Step5B `seed / terminate`

### 9.3 Step5C 输入约束
- 在 Step5B residual graph 上运行
- 当前轮输入节点满足：
  - `closed_con in {1,2}`
  - `kind_2 in {1,4,2048}`
  - `grade_2 in {1,2,3}`
- Step5C `seed / terminate` 额外并入：
  - `S2 + Step4` 的历史高等级边界端点
- `Step5A / Step5B` 当轮新端点：
  - 仅用于 Step5C `hard-stop`
  - 不回注入 Step5C `seed / terminate`

### 9.4 Step5 段提取边界
- Step5A 与 Step5B 之间：
  - 只剔除 Step5A 新 `segment_body` road
  - 不刷新属性
- Step5B 与 Step5C 之间：
  - 只剔除 Step5B 新 `segment_body` road
  - 不刷新属性
- Step5A + Step5B + Step5C 结束后：
  - 再统一刷新 `grade_2 / kind_2 / s_grade / segmentid`

### 9.5 Step5 新 road 写入
- Step5A / Step5B / Step5C 本轮新构成的 `segment_body` road 写入：
  - `s_grade = "0-2双"`
  - `segmentid = "A_B"`

## 10. Node / Road 刷新语义

### 10.1 Node
- `grade_2 / kind_2` 是持续滚动的当前语义字段
- 原始 `grade / kind` 不覆盖
- 刷新按语义路口 mainnode 执行
- subnode 保持当前输入值，不做新的业务重写
- 刷新优先级：
  1. 当前轮 validated pair 端点：保持当前 `grade_2 / kind_2`
  2. 所有 road 都在一个 segment：`grade_2 = -1, kind_2 = 1`
  3. 唯一 segment + 其余全是右转专用道：`grade_2 = 3, kind_2 = 1`
  4. 唯一 segment + 其余非segment road 构成多进多出：`grade_2 = 3, kind_2 = 2048`
  5. 其他情况：保持当前值

### 10.2 Road
- `segmentid` 表示 road 已属于某个 validated pair 的 `segment_body`
- `s_grade` 表示该 road 属于哪一轮 accepted baseline 的双向 segment 结果
- 已有非空 `segmentid / s_grade` 的 road，后续轮次保持原值不覆盖

## 11. 当前 accepted baseline
- 当前唯一主方案：
  - Step1 只做 `pair_candidates`
  - Step2 做首轮 validated / trunk / segment_body / residual
  - Step4 / Step5 在 residual graph 上继续扩展
- 当前推荐输入基线：
  - 最新一轮 refreshed `nodes.geojson`
  - 最新一轮 refreshed `roads.geojson`
- 当前推荐输出基线：
  - Step5 refreshed `nodes.geojson / roads.geojson`
  - 对应的 Step5 merged 审计结果

## 12. 留待正式模块完整构建的内容
- Step6
- 单向 Segment
- Step3 完整语义归并
- 完整多轮闭环治理
- 正式模块化统一编排入口
- 更完整的测试 / 回归 / 验收体系
