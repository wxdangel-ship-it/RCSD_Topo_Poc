# 10 质量要求

## 1. 可理解
- 模块职责、阶段链和 staged runner 端点滚动规则应能直接从 `architecture/*` 读出。

## 2. 可运行
- official runner 应稳定完成：
  - working bootstrap
  - roundabout preprocessing
  - Step1-Step5 staged residual graph

## 3. 可诊断
- `debug=true` 时必须有可追溯中间产物。
- trunk gate、side gate、roundabout、endpoint pool 都应能在审计结果中定位。

## 4. 可治理
- 当前三样例活动基线必须可被 official compare 入口逐样例复现与对比。
- 文档、实现、契约、历史归档关系清晰，不允许只在 README 或 history 里单独藏关键语义。

## 5. 可优化
- 大规模运行下的性能优化必须先给出热点审计结论，再实施代码修改。
- 性能优化必须优先消除跨阶段复用内核中的重复计算，再考虑更大范围的 I/O / 架构调整。
- 所有性能优化都必须维持当前活动三样例基线结果一致。
