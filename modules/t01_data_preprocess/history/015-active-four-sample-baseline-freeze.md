# 015 - Active Four-Sample Baseline Freeze

## 1. 背景
- 在 `XXXS / XXXS2 / XXXS3` 既有活动基线之上，`XXXS4` 已完成外网样例运行、定向修复和用户目视确认。
- 用户于 2026-03-21 明确接受当前 `XXXS / XXXS2 / XXXS3 / XXXS4` 输出结果，并要求冻结为新的活动基线。
- 本次冻结属于基于用户确认的 baseline 迁移，不等于把所有当前候选规则都提升为 accepted 强规则；候选规则仍需继续通过文档和后续样例收敛。

## 2. 新活动基线
- 当前活动基线目录：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_four_sample_suite/`
- 套件内子基线：
  - `XXXS/`
  - `XXXS2/`
  - `XXXS3/`
  - `XXXS4/`

## 3. 四组样例的业务定位
- `XXXS`
  - 通用冒烟样例
  - 用于验证 official runner 主链路稳定性
- `XXXS2`
  - 距离门控重点样例
  - 用于验证上下行最大垂距 gate 与侧向并入最大距离 gate
- `XXXS3`
  - 环岛重点样例
  - 用于验证环岛预处理、环岛 `mainnode` 保护和 staged runner 协同
- `XXXS4`
  - 侧向平行路 / 分歧合流 corridor 重点样例
  - 用于验证 `Step2` 非 trunk component 的 corridor 归属与 staged residual graph 协同

## 4. 冻结来源
- `XXXS`
  - `outputs/_work/t01_skill_v1/t01_skill_v1_20260321_xxxs_prune_v2/`
- `XXXS2`
  - `outputs/_work/t01_skill_v1/t01_skill_v1_20260321_xxxs2_prune_v2/`
- `XXXS3`
  - `outputs/_work/t01_skill_v1/t01_skill_v1_20260321_xxxs3_prune_v2/`
- `XXXS4`
  - `outputs/_work/t01_skill_v1/t01_skill_v1_20260321_xxxs4_prune_v2/`

## 5. 冻结方式
- 每个样例目录下都保留标准 freeze compare 轻量包：
  - `FREEZE_MANIFEST.json`
  - `FREEZE_SUMMARY.json`
  - `FREEZE_COMPARE_RULES.md`
  - `validated_pairs_baseline.csv`
  - `segment_body_membership_baseline.csv`
  - `trunk_membership_baseline.csv`
  - `refreshed_nodes_hash.json`
  - `refreshed_roads_hash.json`
- 套件根目录额外保留：
  - `BASELINE_SUITE_MANIFEST.json`
  - `BASELINE_SUITE_RULES.md`

## 6. 当前规则
- 后续性能优化、结构重构或实现整理，必须分别与四组活动基线对齐。
- 只要任一样例出现结果差异，默认都视为需要业务复核的变更。
- 未经用户明确确认，不得直接覆盖当前活动基线。

## 7. 历史基线关系
- 旧三样例活动套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/`
- 旧单样例 freeze：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 旧语义修正候选 freeze：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs_semantic_fix_candidate/`
- 上述目录继续保留为历史材料，不再作为当前活动基线。
