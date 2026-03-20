# T01 数据预处理规格草案

## 1. 文档状态
- 状态：`Draft / Step5A-Step5B staged residual graph segment construction`
- 当前阶段：允许编码、测试与外网 `XXXS` 验证
- 本文档描述当前 POC 收敛口径，不代表最终生产封板

## 2. 当前轮次框架
- 第一轮：已完成 `grade=1, kind=4` 主路口的 segment 构建，并完成第一轮属性刷新
- Step4：已完成基于上一轮 refreshed `Node / Road` 的 residual graph 构建，并再次刷新 `grade_2 / kind_2 / s_grade / segmentid`
- Step5：当前轮次，拆成两段：
  - `Step5A`：优先轮
  - `Step5B`：收尾轮
- Step6：未来轮次，本轮不启动

## 3. 输入口径

### 3.1 原始字段
- `Road` 基础字段：`id`、`snodeid`、`enodeid`、`direction`、`formway`
- `Node` 基础字段：`id`、`kind`、`grade`、`closed_con`、`mainnodeid`

### 3.2 Step5 输入基线
- Step5 使用 Step4 输出的 refreshed `nodes.geojson / roads.geojson` 作为唯一输入基线
- 必须读取并使用：
  - `grade_2`
  - `kind_2`
  - `closed_con`
  - `segmentid`
  - `s_grade`
- Step5 不使用原始 `grade / kind` 作为筛选条件

## 4. 工作图口径

### 4.1 Step5A 工作图
- 读取 Step4 refreshed Road
- 剔除历史已有非空 `segmentid` 的 road
- 这些 road 在 Step5A 中视为不存在

### 4.2 Step5B 工作图
- 基于 Step5A 工作图继续构建
- 再剔除 Step5A 新构成的 `segment_body` road
- 然后在 residual graph 上运行 Step5B

### 4.3 禁止事项
- Step5A 与 Step5B 之间不得刷新 `Node / Road` 属性
- Step5A 刷新结果不得反向影响 Step5B 的输入筛选

## 5. Step1 / Step2 基线语义

### 5.1 Step1
- Step1 只输出 `pair_candidates`
- Step1 不代表最终有效 pair

### 5.2 Step2
- Step2 负责：
  - `pair_candidate -> validated / rejected`
  - `trunk(pair_backbone)`
  - `segment_body`
  - `step3_residual`

## 6. Step5 语义
- Step5 不是把所有剩余节点一次性平权混跑
- Step5A 与 Step5B 都复用现有 pair / segment 构建内核
- Step5A / Step5B 跑完后：
  - 合并二者的 validated pair 与 segment 结果
  - 统一刷新 `grade_2 / kind_2 / s_grade / segmentid`

## 7. Step5A 输入节点集合
- 条件：
  - `closed_con in {1,2}`
  - 且满足以下两类之一：
    - `kind_2 in {4,2048}` 且 `grade_2 in {1,2}`
    - `kind_2 = 4` 且 `grade_2 = 3`

## 8. Step5B 输入节点集合
- 在 Step5A residual graph 上
- 对所有仍满足以下条件的剩余双向路口继续收尾构段：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`
- Step5B 不是只处理 `grade_2 = 3, kind_2 = 2048`

## 9. mainnode / subnode 口径
- 语义路口按 `mainnodeid` 聚合：
  - 若 `mainnodeid` 有值，则该值为语义路口 ID
  - 若 `mainnodeid` 为空，则 `id` 自身为语义路口 ID
- 判定时以语义路口组的关联 road 集合为准
- 回写时：
  - 只对 mainnode 对应记录做业务改写
  - subnode 保持输入文件当前值

## 10. Step5 完成后的 Node 刷新规则

### 10.1 继承当前值
- 对所有 node：
  - 继承输入文件中的 `grade_2 / kind_2`
  - 不回退到原始 `grade / kind`

### 10.2 规则 1：Step5 pair 端点
- 若 mainnode 出现在 `Step5A + Step5B` 的 validated pair 端点中：
  - `grade_2` 保持当前值不变
  - `kind_2` 保持当前值不变

### 10.3 规则 2：所有 road 都在一个 segment 中
- 条件：
  - 关联的所有 road 都有非空 `segmentid`
  - 且唯一 `segmentid` 个数为 `1`
- 操作：
  - `grade_2 = -1`
  - `kind_2 = 1`

### 10.4 规则 3：唯一 segment + 其余全是右转专用道
- 条件：
  - 关联 road 的非空 `segmentid` 唯一值个数为 `1`
  - 且存在其他 `segmentid` 为空的 road
  - 这些非 segment road 的 `formway` 全命中右转专用道 `bit7 = 128`
- 操作：
  - `grade_2 = 3`
  - `kind_2 = 1`

### 10.5 规则 4：唯一 segment + 其他非 segment road 构成多进多出
- 条件：
  - 关联 road 的非空 `segmentid` 唯一值个数为 `1`
  - 且存在其他 `segmentid` 为空的 road
  - 这些非 segment road 在当前语义路口上统计后同时存在进入和退出
- 操作：
  - `grade_2 = 3`
  - `kind_2 = 2048`
- 含义：
  - 这是输出给未来 Step6 的候选
  - 不反向参与本轮 Step5A / Step5B

### 10.6 优先级
1. Step5 pair 端点：保持当前值
2. 所有 road 都在一个 segment 中：`-1 / 1`
3. 唯一 segment + 其他全是右转专用道：`3 / 1`
4. 唯一 segment + 其他非 segment road 构成多进多出：`3 / 2048`
5. 其余情况：保持当前 `grade_2 / kind_2`

## 11. Step5 完成后的 Road 刷新规则

### 11.1 保留历史值
- 输入中已有非空 `segmentid / s_grade` 的 road：
  - 保持原值不变
  - 不覆盖

### 11.2 Step5 本轮新 segment_body road
- 若 road 属于 Step5A 或 Step5B 新构成的 `segment_body`
- 回写：
  - `s_grade = "0-2双"`
  - `segmentid = "A_B"`

### 11.3 仍未归属的 road
- 若 road 未参与任何轮次 segment：
  - 字段原为空则继续为空
  - 不写默认值

## 12. 输出口径

### 12.1 Step5A
- `step5a_pair_candidates.*`
- `step5a_validated_pairs.*`
- `step5a_rejected_pairs.*`
- `step5a_trunk_roads.*`
- `step5a_segment_body_roads.*`
- `step5a_residual_roads.*`

### 12.2 Step5B
- `step5b_pair_candidates.*`
- `step5b_validated_pairs.*`
- `step5b_rejected_pairs.*`
- `step5b_trunk_roads.*`
- `step5b_segment_body_roads.*`
- `step5b_residual_roads.*`

### 12.3 Step5 merged
- `step5_validated_pairs_merged.*`
- `step5_segment_body_roads_merged.*`
- `step5_residual_roads_merged.*`

### 12.4 Step5 refreshed
- `nodes_step5_refreshed.geojson`
- `roads_step5_refreshed.geojson`
- 同时保留同名链式输出 `nodes.geojson / roads.geojson` 供后续 Step6 直接消费
- `step5_summary.json`
- `step5_mainnode_refresh_table.csv`

## 13. 当前不纳入范围
- 启动 Step6
- 重写 Step1 / Step2 核心算法
- 完整 Step3 语义修正
- 多轮闭环
- 单向 Segment 阶段
