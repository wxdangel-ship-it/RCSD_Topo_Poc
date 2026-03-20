# 011 - Active Three-Sample Baseline Freeze

## 1. 背景
- 在完成以下业务语义修正并通过外网三组样例目视确认后，T01 不再继续沿用早期的单样例 `XXXS` freeze 作为活动基线：
  - working-layer bootstrap
  - roundabout preprocessing
  - `closed_con in {2,3}`
  - `road_kind != 1`
  - 统一 50m dual / side distance gate
  - staged runner 全量 endpoint pool 滚动

## 2. 新活动基线
- 当前活动基线目录：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/`
- 套件内子基线：
  - `XXXS/`
  - `XXXS2/`
  - `XXXS3/`

## 3. 三组样例的业务定位
- `XXXS`
  - 通用冒烟样例
  - 用于验证整条 official runner 主链路稳定性
- `XXXS2`
  - 距离门控重点样例
  - 用于验证上下行最大垂距 gate 与侧向并入最大距离 gate
- `XXXS3`
  - 环岛重点样例
  - 用于验证环岛预处理、环岛 `mainnode` 保护和后续 staged runner 协同

## 4. 冻结方式
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

## 5. 当前规则
- 后续性能优化、结构重构或实现整理，必须分别与三组活动基线对齐。
- 只要任一样例出现结果差异，默认都视为需要业务复核的变更。
- 未经用户明确确认，不得直接覆盖当前活动基线。

## 6. 历史基线关系
- 旧单样例 freeze：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 旧语义修正候选 freeze：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs_semantic_fix_candidate/`
- 二者继续保留为历史材料，不再作为当前活动基线。
