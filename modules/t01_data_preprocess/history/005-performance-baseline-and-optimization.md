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
- 官方 `t01-run-skill-v1` 默认 `debug=true`，便于冻结基线复核和大规模验证前的 case 审计
- 需要降低无意义 I/O 时，可显式使用 `--no-debug`
- 官方 `t01-run-skill-v1` 以 temp stage 目录串联 Step2 / Step3 / Step4 / Step5
- 默认仅保留最终结果与轻量审计包
- refresh / Step4 在 `debug=false` 下仍保留最小边界快照，保证层级边界逻辑不丢失
- Step1 / Step2 / refresh / Step4 / Step5 输入图层采用固定 `2` worker 并行读取
- 官方 runner 在每个阶段后执行 `gc.collect()`
- 官方 runner 记录每个阶段的 `tracemalloc` 峰值内存
- 官方 runner 在 stdout 输出阶段级进度，并落盘：
  - `t01_skill_v1_progress.json`
  - `t01_skill_v1_perf.json`
  - `t01_skill_v1_perf.md`
  - `t01_skill_v1_perf_markers.jsonl`

## 3. 优化结论
- 当前优化未改变 accepted baseline 业务结果
- 通过 XXXS freeze compare 已验证结果一致
- 在 `--no-debug` 低 I/O 模式下，官方 runner 的总 wall time 与分阶段耗时明显下降
- 当前仍未完成的更深层优化是：
  - 彻底去掉 Step4 / Step5 内部对临时文件输入的依赖
  - 在图构建与属性回写层进一步做内存级复用
  - 引入超大数据量下的分块 / 低内存执行策略
  - 设计不破坏结果稳定性的并发执行模型

## 4. 当前 before / after 摘要
- 说明：
  - 以下时间是 XXXS 上的参考测量值，不是冻结契约
  - `debug=true` 默认模式会比 `--no-debug` 低 I/O 模式更慢
  - 真正的结果一致性契约由 freeze compare 决定，而不是 wall time 数值
- before：
  - `outputs/_work/t01_perf_audit/t01_perf_audit_20260320_133048_before/perf_before.json`
  - total wall time：`8.434640` sec
- after：
  - `outputs/_work/t01_perf_audit/t01_perf_audit_20260320_154500_after/perf_after.json`
  - total wall time：`0.307849` sec（`--no-debug` 低 I/O 模式）
- compare：
  - `outputs/_work/t01_perf_audit/t01_perf_audit_20260320_154500_after/perf_compare.md`
  - freeze compare：`PASS`

## 5. 当前结论
- Skill v1.0.0 已具备可接受的执行层性能优化与基础内存治理
- 当前默认模式优先保障 debug 审计可见性，不以最小 I/O 为默认目标
- 进一步的深层内存化重构应作为正式模块完整构建任务推进
