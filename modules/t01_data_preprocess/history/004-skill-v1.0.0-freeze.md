# 004 - Skill v1.0.0 Freeze

## 1. 背景
- 该文档记录的是 T01 早期以 `XXXS` 单样例建立 `Skill v1.0.0` freeze baseline 的历史过程。
- 这份单样例 freeze 曾作为最初的效果基线，用于约束后续 POC 收束和正式化阶段。

## 2. 原冻结范围
- 输入基线：
  - `XXXS/roads.geojson`
  - `XXXS/nodes.geojson`
- 输出基线：
  - 最终 refreshed `nodes.geojson / roads.geojson`
  - validated pair 列表
  - segment_body membership
  - trunk membership
  - summary / hash

## 3. 原冻结组织
- 完整 freeze run：
  - `outputs/_freeze/t01_skill_v1_0_xxxs_20260320_154500/`
- 仓库内轻量审计包：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`

## 4. 当前状态
- 该单样例 freeze 现已转为归档历史。
- 当前活动基线已经切换为三样例套件，见：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/`
- 切换原因：
  - 已完成用户批准的业务语义修正
  - 已对 `XXXS / XXXS2 / XXXS3` 完成目视确认
  - 需要用三组样例共同约束后续性能优化与结果一致性

## 5. 当前用途
- 保留为历史追溯材料。
- 用于解释早期单样例 freeze 与当前活动基线之间的差异来源。
- 不再作为后续性能优化和实现调整的当前对齐对象。
