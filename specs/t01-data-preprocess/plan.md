# T01 计划

## 1. 当前阶段
- 阶段名：`POC closeout and baseline handoff`
- 阶段目标：
  - 固化当前分支已验证通过的 accepted baseline
  - 完成业务语义与代码实现的文档对齐
  - 结束 POC 试验阶段
  - 为正式模块完整构建准备稳定输入基线、轮次语义与推荐入口

## 2. 本轮完成内容
- 完成 Step1 / Step2 / Step4 / Step5 accepted 语义整理
- 完成以下关键语义固化：
  - Step1 仅输出 `pair_candidates`
  - Step2 `segment_body` 只表达 pair-specific road body
  - Step2 三条强规则与 mirrored bidirectional case
  - 右转专用道误纳入修复
  - `791711` T 型双向退出误追溯修复
  - 层级边界 / 历史高等级边界
  - `mainnodeid = NULL` 单点路口语义
  - residual graph 多轮构段语义
  - Step4 / Step5A / Step5B / Step5C 输入与工作图约束
  - trunk 的双向 road、split-merge、semantic-node-group closure 语义
- 完成 POC 收尾文档与 handoff 文档

## 3. 当前推荐基线
- 推荐输入基线：
  - 最新一轮 refreshed `nodes.geojson`
  - 最新一轮 refreshed `roads.geojson`
- 推荐工作方式：
  - residual graph 多轮构段
- 推荐结果基线：
  - Step5 refreshed `nodes.geojson / roads.geojson`
  - 对应 Step5 merged 审计输出

## 4. 当前不再继续扩展的 POC 内容
- 不再继续新增新的试验轮次
- 不再继续扩大 POC 业务目标
- 不再继续追加与 accepted baseline 无关的试验性口径

## 5. 后续转入正式模块完整构建
- 后续工作将从当前 accepted baseline 继续
- 正式模块完整构建待办至少包括：
  - Step6
  - 单向 Segment
  - Step3 完整语义归并
  - 完整多轮闭环治理
  - 统一编排入口
  - 更完整的测试 / 回归 / 验收体系
