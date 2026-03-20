# T01 任务清单

## 1. accepted baseline 已完成项

### 1.1 业务语义
- [x] Step1 只输出 `pair_candidates`
- [x] Step2 固化为 `validated / rejected / trunk / segment_body / step3_residual`
- [x] Step2 `segment_body` 收敛为 pair-specific road body
- [x] Step2 强规则 A / B / C 固化
- [x] mirrored bidirectional case 纳入强规则
- [x] 修复右转专用道误纳入
- [x] 修复 `791711` T 型双向退出误追溯
- [x] trunk 支持双向 road 镜像最小闭环
- [x] trunk 支持 split-merge 混合通道
- [x] trunk 支持 semantic-node-group closure
- [x] `mainnodeid = NULL` 单点路口语义固化
- [x] 层级边界 / 历史高等级边界固化
- [x] Step4 residual graph 固化
- [x] Step5A / Step5B / Step5C staged residual graph 固化

### 1.2 正式入口与冻结
- [x] 官方 end-to-end 入口 `t01-run-skill-v1`
- [x] freeze compare 入口 `t01-compare-freeze`
- [x] XXXS freeze baseline 轻量审计包
- [x] 内网测试三件套契约写入模块文档

## 2. 当前运行期可观测性与性能治理
- [x] 官方 runner 默认 `debug=true`
- [x] 提供显式 `--no-debug` 低 I/O 模式
- [x] 用 temp stage 目录减少 `debug=false` 下的不必要持久化 I/O
- [x] Step1 / Step2 / refresh / Step4 / Step5 输入图层固定 `2` worker 并行读取
- [x] 增加阶段级 GC 回收与 `tracemalloc` 峰值统计
- [x] 增加官方 runner 阶段级命令行进度：
  - `RUN START`
  - `[n/N] START`
  - `[n/N] DONE`
  - `[n/N] FAIL`
- [x] 增加结构化运行期产物：
  - `t01_skill_v1_progress.json`
  - `t01_skill_v1_perf.json`
  - `t01_skill_v1_perf.md`
  - `t01_skill_v1_perf_markers.jsonl`
- [x] 对 XXXS freeze baseline 做 compare PASS 校验

## 3. 当前未完成的 Step2 全量瓶颈治理
- [ ] 给 Step2 增加内部子阶段 progress checkpoint
- [ ] 给 Step2 增加更细粒度 perf checkpoint
- [ ] 识别 A200 全量下 Step2 的主要内存峰值来源
- [ ] 设计并落地第一版 low-memory 执行策略
- [ ] 评估 `debug=true` 全量模式下的可接受资源上限
- [ ] 在不改变业务结果的前提下继续降低 Step2 全量耗时

## 4. 后续正式模块完整构建待办
- [ ] Step6
- [ ] 单向 Segment
- [ ] Step3 完整语义归并
- [ ] 完整多轮闭环治理
- [ ] 完整全内存流水线
- [ ] 核心业务决策层并发执行模型
- [ ] 正式模块化统一编排入口
- [ ] 更完整的测试 / 回归 / 验收体系
