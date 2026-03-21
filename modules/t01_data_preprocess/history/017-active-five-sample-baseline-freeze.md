# 017 - Active Five-Sample Baseline Freeze

## 1. 背景
- 在当前活动四样例基线 `XXXS / XXXS2 / XXXS3 / XXXS4` 已稳定的前提下，`XXXS5` 已完成 `Step5C adaptive barrier fallback` 修正、用户目视确认，并要求纳入活动基线。
- 本次冻结的核心新增业务覆盖是：
  - `Step5C final fallback`
  - rolling endpoint pool 与 actual terminate barrier 解耦
  - 长 corridor `997356__39546395` 的兜底构段

## 2. 新活动基线
- 当前活动基线目录：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/`
- 套件内子基线：
  - `XXXS/`
  - `XXXS2/`
  - `XXXS3/`
  - `XXXS4/`
  - `XXXS5/`

## 3. 五组样例的业务定位
- `XXXS`
  - 通用冒烟样例
  - 验证 official runner 主链路稳定性
- `XXXS2`
  - 距离门控重点样例
  - 验证 dual/side 50m gate
- `XXXS3`
  - 环岛重点样例
  - 验证环岛预处理与环岛 mainnode 保护
- `XXXS4`
  - 侧向平行路 / 分歧合流 corridor 重点样例
  - 验证 `Step2` 非 trunk component 归属与 staged residual graph 协同
- `XXXS5`
  - `Step5C final fallback` 重点样例
  - 验证历史 endpoint 不再机械等同 hard-stop 后，长 corridor 的兜底构段能力

## 4. 冻结来源
- `XXXS`
  - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs_step5c_adaptive_compare_v2/`
- `XXXS2`
  - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs2_step5c_adaptive_compare_v2/`
- `XXXS3`
  - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs3_step5c_adaptive_compare_v2/`
- `XXXS4`
  - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs4_step5c_adaptive_compare_v2/`
- `XXXS5`
  - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs5_step5c_adaptive_v2/`

## 5. 冻结方式
- 每个样例目录下保留标准 freeze compare 轻量包：
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

## 6. 验证结果
- 以 `t01-compare-freeze` 对五个 current run 与对应 freeze 子目录逐一 compare，结果全部 `PASS`：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
  - `XXXS4`
  - `XXXS5`
- `XXXS5` 的定点业务证据：
  - `STEP5C:997356__39546395` 已进入 candidate 与 validated
  - 目标审计见：
    - `outputs/_work/t01_skill_eval/t01_skill_v1_20260321_xxxs5_step5c_adaptive_v2/debug/step5/STEP5C/target_pair_audit_997356__39546395.json`

## 7. 历史基线关系
- 旧活动四样例套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_four_sample_suite/`
- 旧活动三样例套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/`
- 上述目录继续保留为历史材料，不再作为当前活动基线。
