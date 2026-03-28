# 018 - Test Eight-Sample Baseline Freeze

## 1. 背景
- 用户要求将 `XXXS1` 至 `XXXS8` 冻结为一套后续回归使用的测试基线。
- 本次冻结目标是补齐当前 `XXXS1-8` 全覆盖测试套件，便于后续性能优化、结构重构和规则调整时做统一回归。
- 本次冻结不自动替代当前 active accepted baseline。

## 2. 新测试基线套件
- 新套件目录：
  - `modules/t01_data_preprocess/baselines/t01_skill_test_eight_sample_suite/`
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
- 冻结源运行目录：
  - `outputs/_work/t01_manual_review_suite_20260328_bb24202_regression/`
- 每个样例均直接使用该套件对应 case 的：
  - `debug/step2/S2`
  - `debug/step4`
  - `debug/step5`
  - 根目录 refreshed `nodes.gpkg / roads.gpkg`

## 4. 冻结方式
- 每个样例目录下保留标准 freeze compare 轻量包：
  - `FREEZE_MANIFEST.json`
  - `FREEZE_SUMMARY.json`
  - `FREEZE_COMPARE_RULES.md`
  - `validated_pairs_baseline.csv`
  - `segment_body_membership_baseline.csv`
  - `trunk_membership_baseline.csv`
  - `refreshed_nodes_hash.json`
  - `refreshed_roads_hash.json`
  - `freeze_compare_report.json`
  - `freeze_compare_report.md`
- 套件根目录额外保留：
  - `BASELINE_SUITE_MANIFEST.json`
  - `BASELINE_SUITE_RULES.md`

## 5. 验证结果
- 使用仓库现有 compare 机制，对 `XXXS1-8` 当前运行结果与对应 freeze 子目录逐一自比较。
- 八个样例的 compare 结果均为 `PASS`。

## 6. 与当前 active baseline 的关系
- 当前 active accepted baseline 仍保持原有套件，不因本次测试冻结自动变更。
- 新套件的用途是：
  - 扩大测试覆盖面
  - 为后续改动提供 `XXXS1-8` 的统一非回退检查口径
