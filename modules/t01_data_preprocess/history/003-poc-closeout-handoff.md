# 003 - POC 收尾与基线交接说明

## 1. 为什么当前可以结束 POC
- 当前分支已经把 POC 阶段暴露的核心业务语义问题收敛并固化：
  - Step1 / Step2 职责边界清晰
  - Step2 `segment_body` 语义已收紧
  - 右转专用道误纳入问题已修复
  - `791711` T 型双向退出误追溯已修复
  - 历史高等级边界语义已落地
  - `mainnodeid = NULL` 单点路口语义已落地
  - residual graph 多轮构段方式已形成稳定工作口径
  - trunk 已支持双向 road、split-merge、semantic-node-group closure
- 当前代码、文档与已验证结果已经能够形成一致的 accepted baseline

## 2. 当前 accepted baseline 是什么

### 2.1 轮次语义
- 首轮：
  - Step1：`pair_candidates`
  - Step2：`validated / rejected + trunk + segment_body + step3_residual`
- 后续轮次：
  - Step4：residual graph 外层轮次
  - Step5A / Step5B / Step5C：继续在 residual graph 上 staged 扩展

### 2.2 推荐输入基线
- 最新一轮 refreshed `nodes.geojson`
- 最新一轮 refreshed `roads.geojson`

### 2.3 推荐输出基线
- Step5 refreshed `nodes.geojson / roads.geojson`
- 对应 Step5 merged 审计结果

## 3. 当前推荐运行链路
- 首轮：
  - `python -m rcsd_topo_poc t01-step2-segment-poc`
- 首轮刷新：
  - `python -m rcsd_topo_poc t01-s2-refresh-node-road`
- 外层轮次：
  - `python -m rcsd_topo_poc t01-step4-residual-graph`
  - `python -m rcsd_topo_poc t01-step5-staged-residual-graph`

## 4. 为什么当前不再继续扩大 POC
- 当前 POC 的目标是收敛 accepted baseline，而不是无限追加新试验
- 继续扩展新的轮次或新业务目标，会再次把“业务语义确认”与“正式模块构建”混在一起
- 因此本轮将 POC 结束，并把后续内容转入正式模块完整构建待办

## 5. 后续正式模块完整构建从哪里开始
- 从当前 accepted baseline 开始
- 直接消费最新一轮 Step5 refreshed `nodes.geojson / roads.geojson`
- 直接复用当前已收敛的 Step1 / Step2 / Step4 / Step5 业务语义

## 6. 正式模块完整构建待办
- Step6
- 单向 Segment
- Step3 完整语义归并
- 完整多轮闭环治理
- 一步到位总编排入口
- 更完整的测试 / 回归 / 验收体系

## 7. handoff 结论
- 当前分支已完成 POC 收尾
- 当前仓库已整理为可提交到 baseline 的状态
- 正式模块完整构建可以在此基线上启动
