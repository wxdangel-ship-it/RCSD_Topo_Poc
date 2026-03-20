# T01 架构概览

## 1. 当前 accepted architecture
- 官方 Step1-Step5 口径：
  1. Step1：候选 Pair 发现
  2. Step2：首轮 validated / trunk / segment_body 构建
  3. Step3：语义修正与 refreshed Node / Road 更新
  4. Step4：基于 residual graph 的下一轮构段
  5. Step5：`Step5A / Step5B / Step5C` staged residual graph 收尾并统一刷新

## 2. 关键设计原则
- Step1 只做候选发现，不做最终有效性确认
- Step2 的 `segment_body` 只表达 pair-specific road body
- trunk 以语义路口为单元，支持双向 road、split-merge、semantic-node-group closure
- 后续轮次不回到原始全量图，而是在 refreshed + residual graph 上继续推进
- 历史高等级边界同时作用于 pair 搜索与 segment 收敛

## 3. 官方入口与调试层
- 官方入口：
  - `t01-run-skill-v1`
- 分步入口：
  - `t01-step2-segment-poc`
  - `t01-s2-refresh-node-road`
  - `t01-step4-residual-graph`
  - `t01-step5-staged-residual-graph`
- `debug=false`
  - 默认只保留最终结果与轻量审计包
- `debug=true`
  - 保留分阶段中间层

## 4. baseline freeze 审计闭环
- 当前 Skill v1.0.0 效果基线为 XXXS freeze baseline
- 仓库内轻量包：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- compare 入口：
  - `t01-compare-freeze`
- 结果不一致默认视为回退或显式变更
