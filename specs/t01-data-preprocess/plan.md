# T01 计划

## 1. 当前阶段
- 阶段名：`Step2 large-scale bottleneck remediation and runtime observability`
- 阶段目标：
  - 在不改变 accepted baseline 业务结果的前提下，降低 A200 级全量数据运行阻力。
  - 补齐官方 end-to-end runner 的运行期可观测性。
  - 为后续大规模验证与问题排查建立稳定、可解释的性能审计基线。

## 2. 当前问题画像
- A200 全量运行时，官方 runner 能持续高 CPU 运行，但当前主要瓶颈集中在 `Step2`。
- 当前只有阶段级进度时，命令行会长时间停留在 `START step2`，无法判断是否正常推进。
- `debug=true` 默认模式下，全量运行容易触发明显内存压力与长时间等待。
- 当前优化已经减少了一部分无意义 I/O，但尚未达到“可安心做大规模验证”的程度。

## 3. 本轮治理主线
- 补齐官方 runner 的运行期可观测性：
  - 命令行阶段进度
  - Step2 内部子阶段进度
  - 结构化 progress / perf checkpoint
- 收敛已经落地的执行层优化：
  - 固定小并发输入读取
  - 阶段级 `gc.collect()` 与 `tracemalloc`
  - `debug=false` 时的临时 stage 目录
- 推进 Step2 瓶颈治理：
  - Step2 内部更细粒度 perf 打点
  - Step2 的第一版 low-memory 策略
  - A200 级别可接受的资源占用上限

## 4. 当前已完成
- 官方 runner 默认 `debug=true`。
- 官方 runner 已支持：
  - 阶段级 `START / DONE / FAIL` 命令行进度
  - `t01_skill_v1_progress.json`
  - `t01_skill_v1_perf.json`
  - `t01_skill_v1_perf.md`
  - `t01_skill_v1_perf_markers.jsonl`
- Step1 / Step2 / refresh / Step4 / Step5 输入读取已切换为固定 `2` worker 受控并行。
- 官方 runner 已补齐阶段级 `gc.collect()` 与 `tracemalloc` 峰值记录。
- 外网 `XXXS` 已验证：
  - 默认 debug 模式结果正确
  - `--no-debug` 低 I/O 模式结果正确
  - freeze compare 保持 `PASS`

## 5. 当前未完成
- Step2 内部子阶段进度仍未补齐。
- A200 全量下的内存压力治理仍未完成。
- 当前仍未形成完整的 low-memory 执行模式。
- 当前仍未进入完整全内存流水线。
- 当前仍未引入核心 pair / trunk / validated 决策层并发。

## 6. 当前边界
- 不改变 accepted baseline 的业务语义与冻结结果。
- 不通过减少必要校验来换速度。
- 不通过修改 freeze baseline 掩盖结果漂移。
- 不将“完整全内存化”误表述为已完成。
- 不将“业务决策层并发”误表述为已完成。

## 7. 下一步
- 在 Step2 内部补齐更细的 progress checkpoint。
- 明确 Step2 的热点子阶段与对象峰值位置。
- 设计并实现第一版 low-memory 策略。
- 在 `XXXS` 与 `A200` 上分别验证：
  - 结果不回退
  - 进度可见性提升
  - 资源占用和耗时得到改善
