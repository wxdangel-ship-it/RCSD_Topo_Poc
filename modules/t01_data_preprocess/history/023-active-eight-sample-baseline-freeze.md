# 023 - Active Eight-Sample Baseline Freeze

## 1. 背景
- 用户已完成 `XXXS1` 至 `XXXS8` 的再次目视检查，并确认当前可接受基线应扩展为八样例套件。
- 本次冻结以用户认可的产物目录为准：
  - `outputs/_work/t01_manual_review_suite_20260327_xxxs5_wedge_fix/`
- 同时确认后续业务验收主口径为：
  - 最终 `segment.gpkg` 语义一致

## 2. 新 active baseline
- 当前 active accepted baseline 目录：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_eight_sample_suite/`
- 套件内子基线：
  - `XXXS1/`
  - `XXXS2/`
  - `XXXS3/`
  - `XXXS4/`
  - `XXXS5/`
  - `XXXS6/`
  - `XXXS7/`
  - `XXXS8/`

## 3. 冻结来源
- accepted reference run root：
  - `outputs/_work/t01_manual_review_suite_20260327_xxxs5_wedge_fix/`
- 每个样例的 baseline 轻量包直接从对应 case 的下列产物抽取：
  - `debug/step2/S2`
  - `debug/step4`
  - `debug/step5`
  - 根目录 `nodes.gpkg / roads.gpkg / segment.gpkg`

## 4. 验收口径
- 业务主口径：
  - 最终 `segment.gpkg` 语义一致
- 辅助审计证据：
  - `validated_pairs_baseline.csv`
  - `segment_body_membership_baseline.csv`
  - `trunk_membership_baseline.csv`
  - `refreshed_nodes_hash.json`
  - `refreshed_roads_hash.json`
- 对于仅出现在导出字段大小写、路径或 schema 迁移层面的差异，默认不直接视为业务回退；是否回退仍以 `segment.gpkg` 语义一致性为准。

## 5. 冻结内容
- 套件根目录：
  - `BASELINE_SUITE_MANIFEST.json`
  - `BASELINE_SUITE_RULES.md`
- 每个 case 子目录：
  - `FREEZE_MANIFEST.json`
  - `FREEZE_SUMMARY.json`
  - `FREEZE_COMPARE_RULES.md`
  - `validated_pairs_baseline.csv`
  - `segment_body_membership_baseline.csv`
  - `trunk_membership_baseline.csv`
  - `refreshed_nodes_hash.json`
  - `refreshed_roads_hash.json`
  - `segment_output_hash.json`
  - `freeze_compare_report.json`
  - `freeze_compare_report.md`

## 6. 与旧 active baseline 的关系
- 旧 active baseline：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/`
- 旧目录继续保留为历史材料，不再作为当前 active accepted baseline。
- 当前 active accepted baseline 以八样例套件为准。

## 7. 后续约束
- 后续 Step2 性能优化、结构调整或规则修订，必须先与本八样例 active baseline 对齐。
- 未经用户明确确认，不得覆盖本套 active accepted baseline。
