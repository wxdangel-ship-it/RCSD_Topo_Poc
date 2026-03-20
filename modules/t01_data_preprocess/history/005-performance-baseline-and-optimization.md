# 005 - Performance Baseline And Optimization

## 1. 性能基线背景
- official runner 已提供：
  - 阶段级进度输出
  - `t01_skill_v1_progress.json`
  - `t01_skill_v1_perf.json`
  - `t01_skill_v1_perf.md`
  - `t01_skill_v1_perf_markers.jsonl`
- 当前主要热点仍集中在：
  - Step2 搜索与验证
  - 中间结果写盘
  - staged residual graph 的阶段间串联

## 2. 已落地优化
- 引入 official end-to-end runner
- 统一 `debug` 行为
- 增加阶段级 perf marker 与 progress marker
- 基础输入层支持并行读图
- runner 在阶段之间执行 `gc.collect()` 并记录 `tracemalloc`

## 3. working bootstrap 前移的架构影响
- working Nodes / Roads 已前移到模块开始阶段
- `grade_2 / kind_2 / s_grade / segmentid` 从模块开始即存在
- 这一步的主要收益是：
  - 明确后续 Step1-Step5 全部操作 working layers
  - 为未来 preprocess 留出正式容器
  - 避免后续阶段再重复承担“首次引入运行期字段”的职责

## 4. 本轮 roundabout preprocessing 的影响
- 环岛预处理接在 working bootstrap 之后
- 它主要是结构和语义能力扩展，不是纯性能优化
- 当前实现的原则是：
  - 基于共享 node 的拓扑连通聚合
  - 审计输出仅在 `debug=true` 下保留详细层
  - `debug=false` 时保留 summary，避免无意义中间 I/O
- 本轮没有把环岛能力伪装成性能优化收益

## 5. 当前结论
- 当前性能治理已具备官方 runner、进度打点、阶段级内存/时间审计
- working bootstrap 与 roundabout preprocessing 已有稳定挂点
- 更深层的 low-memory / large-scale runtime 治理仍是后续待办
