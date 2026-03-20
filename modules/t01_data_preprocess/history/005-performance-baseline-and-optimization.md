# 005 - Performance Baseline And Optimization

## 1. 性能基线背景
- 优化前链路以分阶段输出目录为主
- 默认会保留大量中间产物，I/O 开销明显
- 主要热点集中在：
  - GeoJSON 写盘
  - `json.dump`
  - Step2 / Step4 / Step5 输出层

## 2. 主要优化
- 为 Step1 / Step2 / refresh / Step4 / Step5 增加统一 `debug` 开关
- `debug=false` 时减少默认中间产物输出
- 官方 `t01-run-skill-v1` 以 temp stage 目录串联 Step2 / Step3 / Step4 / Step5
- 默认仅保留最终结果与轻量审计包
- refresh / Step4 在 `debug=false` 下仍保留最小边界快照，保证层级边界逻辑不丢失

## 3. 优化结论
- 当前优化未改变 accepted baseline 业务结果
- 通过 XXXS freeze compare 已验证结果一致
- 默认官方 runner 的总 wall time 与分阶段耗时明显下降
- 当前仍未完成的更深层优化是：
  - 彻底去掉 Step4 / Step5 内部对临时文件输入的依赖
  - 在图构建与属性回写层进一步做内存级复用

## 4. 当前 before / after 摘要
- before：
  - `outputs/_work/t01_perf_audit/t01_perf_audit_20260320_133048_before/perf_before.json`
  - total wall time：`8.434640` sec
- after：
  - `outputs/_work/t01_perf_audit/t01_perf_audit_20260320_154500_after/perf_after.json`
  - total wall time：`0.307849` sec
- compare：
  - `outputs/_work/t01_perf_audit/t01_perf_audit_20260320_154500_after/perf_compare.md`
  - freeze compare：`PASS`

## 5. 当前结论
- Skill v1.0.0 已具备可接受的官方默认性能
- 进一步的深层内存化重构应作为正式模块完整构建任务推进
