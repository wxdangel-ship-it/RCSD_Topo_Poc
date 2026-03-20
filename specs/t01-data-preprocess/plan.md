# T01 计划

## 1. 当前阶段
- 阶段名：`Step5A/Step5B/Step5C staged residual graph segment construction`
- 阶段目标：
  - 在现有 Step5 staged residual graph 编排中新增 `Step5C`
  - 让 `kind_2=1` 节点在 Step5C residual graph 上进入构段
  - 保持 Step5A / Step5B / Step5C 之间不刷新属性
  - 在外网 `XXXS` 上验证三阶段 merged 与 refreshed 结果
  - 暂不进入 Step6、分支收尾与 baseline handoff

## 2. 本轮要做
- 在 Step5 编排中新增 `Step5C`
- Step5C 输入集合改为：
  - `closed_con in {1,2}`
  - `grade_2 in {1,2,3}`
  - `kind_2 in {1,4,2048}`
- 补齐 trunk 全局语义：
  - trunk 闭环以语义路口为单元
  - `semantic-node-group closure` 也可成立
  - 不再把“纯几何不开环”作为唯一拒绝条件
- Step5C 工作图继续剔除：
  - 历史已有 `segmentid` road
  - `Step5A` 新 `segment_body` road
  - `Step5B` 新 `segment_body` road
- 保持 Step5A / Step5B / Step5C 之间不刷新属性，三阶段完成后统一刷新
- 保持历史边界规则：
  - `S2 + Step4` 仍回注入 Step5C `seed / terminate`
  - `Step5A / Step5B` 当轮新端点仅用于 Step5C `hard-stop`
- 在外网 `XXXS` 上重跑 Step5 并输出新的审查结果

## 3. 本轮不做
- 不做 POC closeout / baseline handoff
- 不启动 Step6
- 不做多轮总编排一键执行收尾
- 不重写 Step1 / Step2 主算法

## 4. 本轮交付
- 文档更新：
  - `spec.md`
  - `plan.md`
  - `tasks.md`
  - `INTERFACE_CONTRACT.md`
  - `README.md`
- 代码更新：
  - Step5 三阶段编排（A/B/C）
  - Step5C 输入规则与 merged/refreshed 输出
- 外网 `XXXS` 新结果：
  - Step5 审查目录
  - Step5C / merged 审查结果

## 5. 验证准则
- Step5A / Step5B / Step5C 之间不刷新属性
- Step5C 输入集合准确纳入 `kind_2=1`
- Step5C 工作图不包含历史已成段 road，也不包含 Step5A / Step5B 新 segment road
- Step5 merged / refreshed 结果正确累积三阶段产物
