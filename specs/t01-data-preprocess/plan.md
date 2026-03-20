# T01 计划

## 1. 当前阶段
- 阶段名：`Step5A/Step5B staged residual graph segment construction`
- 阶段目标：
  - 基于 Step4 refreshed `Node / Road` 启动 `Step5A / Step5B`
  - Step5A 先处理优先级更高的一批双向路口
  - Step5B 在 Step5A residual graph 上完成剩余双向路口收尾
  - 两阶段完成后统一刷新 `grade_2 / kind_2 / s_grade / segmentid`

## 2. 本轮要做
- 新增明确的 `Step5` 编排入口
- Step5A 使用：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048} and grade_2 in {1,2}`
  - 或 `kind_2 = 4 and grade_2 = 3`
- Step5B 使用：
  - Step5A residual graph
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`
- Step5A 与 Step5B 之间只剔除新 `segment_body` road，不刷新属性
- 统一输出 Step5A / Step5B / merged / refreshed 结果
- 在外网 `XXXS` 上完成实跑

## 3. 本轮不做
- 不启动 `Step6`
- 不重写 Step1 / Step2 核心算法
- 不实现完整 Step3
- 不推进多轮闭环
- 不推进单向 Segment 阶段

## 4. 本轮交付
- 文档更新：
  - `spec.md`
  - `tasks.md`
  - `INTERFACE_CONTRACT.md`
  - `README.md`
  - `architecture/overview.md`
- 代码更新：
  - `Step5A / Step5B` staged residual graph 编排器
  - Step5 merged 输出
  - Step5 完成后的 Node / Road 统一刷新
- 审查输出：
  - `step5a_*`
  - `step5b_*`
  - `step5_*_merged`
  - `step5_summary.json`
  - `step5_mainnode_refresh_table.csv`

## 5. 验证准则
- Step5A / Step5B 输入节点集合符合定义
- Step5A 与 Step5B 之间未刷新属性
- Step5B 工作图确实去掉历史已有 segment road 与 Step5A 新 segment road
- 本轮新 road 被写为：
  - `s_grade = "0-2双"`
  - `segmentid = "A_B"`
- 新刷出的 `grade_2 = 3, kind_2 = 2048` 只作为未来 Step6 候选输入
