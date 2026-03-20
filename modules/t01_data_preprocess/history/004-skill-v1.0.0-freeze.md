# 004 - Skill v1.0.0 Freeze

## 1. 背景
- T01 在当前分支完成了 accepted baseline 收敛
- 已有人工确认通过的 XXXS 效果结果
- 需要将其固化为 Skill v1.0.0 的效果基线

## 2. 冻结范围
- 输入基线：
  - XXXS `roads.geojson`
  - XXXS `nodes.geojson`
- 输出基线：
  - 官方最终 refreshed `nodes.geojson / roads.geojson`
  - validated pair 列表
  - segment_body membership
  - trunk membership
  - 关键 summary 与 hash

## 3. 冻结组织
- 完整 freeze run 保留在 `outputs/_freeze/`
- 仓库内轻量审计包保留在：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 当前本地完整 freeze run 目录：
  - `outputs/_freeze/t01_skill_v1_0_xxxs_20260320_154500/`
- 当前用于 compare 的官方 run：
  - `outputs/_work/t01_skill_v1/t01_skill_v1_20260320_154500_xxxs_verify/`

## 4. 用途
- 作为 T01 Skill v1.0.0 的效果基线
- 作为后续性能优化与代码重构的结果对照标准
- 当前 compare 结果：`PASS`

## 5. 解除或更新条件
- 默认不允许更新 freeze baseline
- 只有在用户明确认可业务变更后，才允许重建并替换该 baseline
