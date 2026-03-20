# T01 架构概览

## 1. 当前分层
- Step1：`pair_candidates`
- Step2：`validated / rejected + trunk + segment_body + step3_residual`
- Step4：基于上一轮 refreshed `Node / Road` 的 residual graph 新一轮构建
- Step5：基于 Step4 refreshed 输入的 `Step5A / Step5B / Step5C` 三阶段 residual graph 构建
- Step6：未来轮次，尚未启动

## 2. 当前职责边界

### Step1
- 负责候选发现
- 不负责最终有效 pair 确认

### Step2
- 负责 pair candidate validation
- 负责 trunk / pair_backbone 识别
- 负责把 pair-specific road body 收敛为 `segment_body`
- 负责把边界模糊结构挂入 `step3_residual`

### Step4
- 负责消费上一轮 refreshed 输入
- 负责在 residual graph 上继续构建
- 负责刷新 `grade_2 / kind_2 / s_grade / segmentid`

### Step5
- 负责在 Step4 refreshed 输入上拆成 `Step5A / Step5B / Step5C`
- `Step5A` 先跑优先轮
- `Step5B` 在 residual graph 上跑收尾轮
- `Step5C` 在 residual graph 上将 `kind_2=1` 纳入补充构段
- 三阶段完成后统一刷新 `Node / Road`

### Step6
- 未来负责消费 Step5 输出继续构建
- 不在本轮实现范围内

## 3. 当前主流程
- 原始 Node / Road
- 第一轮 Step1 + Step2
- 第一轮 refresh
- Step4 residual graph 构建
- Step4 refreshed `nodes.geojson / roads.geojson`
- Step5A：
  - 去掉历史已有 segment road
  - 跑优先轮
- Step5B：
  - 再去掉 Step5A 新 segment road
  - 跑收尾轮
- Step5C：
  - 再去掉 Step5B 新 segment road
  - 跑 `kind_2 in {1,4,2048}` 的补充轮
- Step5 merged / refreshed：
  - 合并 validated pair / segment
  - 统一刷新 `grade_2 / kind_2 / s_grade / segmentid`
- 未来 Step6 再消费 Step5 refreshed 输出继续推进
