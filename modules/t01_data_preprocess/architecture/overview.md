# T01 架构概览

## 1. 当前 accepted architecture
- 首轮：
  - Step1 发现 `pair_candidates`
  - Step2 完成 `validated / rejected + trunk + segment_body + step3_residual`
- 首轮刷新：
  - 输出 refreshed `nodes.geojson / roads.geojson`
- residual graph 外层轮次：
  - Step4：基于 refreshed 输入继续构段并刷新
  - Step5A / Step5B / Step5C：基于 Step4 refreshed 输入继续 staged residual graph 构段

## 2. 核心设计原则
- Step1 只做候选发现，不做最终有效性确认
- Step2 的 `segment_body` 只表达 pair-specific road body
- 后续轮次不回到原始全量图，而是在 residual graph 上继续推进
- 已有非空 `segmentid` 的 road 从后续轮次工作图剔除
- 更低等级轮次必须在更高等级历史路口中断
- trunk 与最小闭环以语义路口为单元，不只依赖纯几何闭环

## 3. 当前 accepted 轮次职责

### Step1
- 负责 `pair_candidates`

### Step2
- 负责：
  - validated / rejected
  - trunk
  - segment_body
  - step3_residual

### Step4
- 负责：
  - 消费 refreshed `Node / Road`
  - 在 residual graph 上继续构段
  - 刷新 `grade_2 / kind_2 / s_grade / segmentid`

### Step5A / Step5B / Step5C
- Step5A：
  - 优先轮
- Step5B：
  - residual graph 上所有剩余双向路口收尾轮
- Step5C：
  - residual graph 上将 `kind_2=1` 纳入后的补充轮
- 三阶段完成后统一刷新 `Node / Road`

## 4. 当前 accepted baseline
- 推荐输入基线：
  - 最新一轮 refreshed `nodes.geojson / roads.geojson`
- 推荐输出基线：
  - Step5 refreshed `nodes.geojson / roads.geojson`
  - 对应 Step5 merged 审计结果

## 5. 后续正式模块完整构建
- 当前 POC 已结束，后续将从 accepted baseline 继续
- 未来完整构建至少包括：
  - Step6
  - 单向 Segment
  - Step3 完整语义归并
  - 完整多轮闭环治理
  - 统一编排入口
