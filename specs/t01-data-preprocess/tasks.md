# T01 数据预处理任务清单

## 1. 当前任务状态

- 状态：`Step2 Segment POC In Progress`
- 当前说明：
  - 允许实现 Step2 原型
  - 允许修正 Step1 语义
  - 不得越界到多轮闭环、T 型完整复核、单向 Segment 终局实现

## 2. 本轮已确认任务

### 2.1 文档任务

- 更新 `spec.md`
- 更新 `plan.md`
- 更新 `tasks.md`
- 更新模块级 `INTERFACE_CONTRACT.md`
- 更新模块级 `README.md`
- 必要时同步 `architecture/overview.md`

### 2.2 Step1 任务

- 将 Step1 口径统一改为 `pair_candidates`
- 保留 seed / terminate / through / 双向确认能力
- 输出 candidate 审查图层与表格

### 2.3 Step2 任务

- 读取 / 串接 Step1 `pair_candidates`
- 生成 candidate channel
- 回溯裁枝通往其他 terminate node 的分支
- 识别 trunk
- 构建 segment
- 产出 validated / rejected 结果与审计图层

### 2.4 验证任务

- 补最小 pytest 覆盖
- 在外网 `XXXS` 上完成实际验证
- 整理 Step1 candidate 与 Step2 validated 差异摘要

## 3. 本轮最小测试覆盖

- candidate 与 validated 显式分离
- only_clockwise_loop 拒绝
- branch_leads_to_other_terminate 裁枝
- disconnected_after_prune 拒绝
- trunk 与 segment 不等价
- left_turn_only_polluted_trunk 或 `formway_unreliable_warning`

## 4. 当前不纳入范围

- 多轮双向 Segment 工作图剥离闭环
- T 型路口轮间复核完整实现
- 单向 Segment 阶段
- trunk 冲突最终优先级策略
- 最终生产出参封板

## 5. 待确认事项

1. 当前 `only_clockwise_loop` 是否全部视为最终 reject
2. `shared_trunk_conflict` 后续是保守 reject 还是延迟分配
3. `formway bit8` 是否足以从原型规则升级为生产强规则
4. 候选通道的局部扩张边界是否还要再收紧
