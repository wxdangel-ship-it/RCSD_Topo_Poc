# T01 数据预处理阶段计划

## 1. 当前阶段

- 当前阶段：`Step2 Segment POC`
- 当前状态：允许编码、测试与外网 `XXXS` 实跑
- 当前目标：
  - 把 Step1 语义改为 `pair_candidates`
  - 实现 Step2 candidate validation + segment construction 原型
  - 产出 QGIS 可审查结果

## 2. 本轮要完成的事项

### 2.1 语义调整

- Step1 不再被描述为“最终有效 Pair 产出”
- Step1 只负责：
  - seed / terminate 规则筛选
  - BFS 搜索
  - through 继续追溯
  - 双向确认
- Step1 输出统一口径为：
  - `pair_candidates`

### 2.2 Step2 原型实现

- 消费 Step1 `pair_candidates`
- 实现 candidate channel 生成
- 实现分支回溯裁枝
- 实现 trunk 识别
- 实现 validated / rejected 判定
- 围绕 trunk 收敛 segment
- 输出 trunk / segment / branch_cut / validation table / summary

### 2.3 外网验证

- 定位并使用外网 `XXXS`
- 完整跑通：
  - Step1 candidate
  - Step2 validation + segment construction
- 形成独立运行目录与差异摘要

## 3. 本轮执行原则

- 本轮是原型研发，不是生产规则封板
- 优先复用现有 `src/`、`tests/`、`outputs/_work/`、`python -m rcsd_topo_poc` 风格
- candidate / validated 必须显式区分
- trunk / segment 必须显式区分
- 不做 silent fix，所有关键拒绝原因必须可审计

## 4. 本轮不做的事项

- 多轮双向 Segment 全流程闭环
- T 型路口轮间复核完整实现
- 单向 Segment 阶段
- trunk 冲突最终归属策略封板
- Step2 最终生产输出定稿

## 5. 当前风险与待确认点

- `only_clockwise_loop` 的业务处理口径，后续可能还需要更细确认
- `shared_trunk_conflict` 当前仍是保守拒绝，后续可能需要更稳的 pair 排序 / 归属策略
- `formway bit8` 当前只适合原型阶段显式审计 / 可配置排除
- 候选通道扩张边界当前仍是 POC 级实现，后续可能需要进一步收紧
