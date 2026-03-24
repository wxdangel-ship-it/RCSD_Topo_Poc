# T01 任务清单

## 已确认基线
- [x] Step1 只输出 `pair_candidates`
- [x] Step2 输出 `validated / rejected / trunk / segment_body / step3_residual`
- [x] Step6 已纳入 official end-to-end
- [x] working layers 初始化已前置
- [x] 环岛预处理已纳入开始阶段
- [x] 全局 50m 双线 / 侧向并入 gate 已固化
- [x] 右转专用道误纳入问题已关闭
- [x] T 型路口竖向阻断规则已上提为统一约束

## 临时最终 Segment 基线
- [x] 建立 `XXXS-XXXS8` 临时最终 Segment 基线
- [x] 更新 `XXXS6` 为 `PASS_LOCKED`
- [x] 当前分组：
  - `PASS_LOCKED`: `XXXS / XXXS2 / XXXS3 / XXXS4 / XXXS6 / XXXS8`
  - `FAIL_TARGET`: `XXXS5 / XXXS7`
- [x] 将当前状态写入：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`

## 当前实现整改批次
- [ ] 批次 A：修正 `Step4 / Step5A / Step5B` 对当前 `grade_2 / kind_2` 的压扁
- [ ] 批次 B：引入 `Step5A / Step5B / Step5C` 逐轮 refresh
- [ ] 批次 C：去掉 `Step2` 对 raw `grade / kind` 的业务 fallback
- [ ] 批次 D：补齐 `formway = 128` 在 Step6 的一致过滤

## 样例问题
- [ ] 修复 `XXXS5`
  - 问题口径：`Segment 39546457_47130796` 含超过 `50m` 的旁路分支
- [ ] 修复 `XXXS7`
  - 问题口径：`Segment 1013672_612642212` 含双向旁路
  - 约束：从 `Step1-Step5` 整体评估，不得只打局部补丁
- [x] 保持 `XXXS7 / Segment 1026500_1026503` 正确构成
- [x] 保持首次已修 duplicate-road case 不回退

## 非回退要求
- [ ] 每个整改批次完成后，对以下样例逐一验证最终 Segment 不回退：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
  - `XXXS4`
  - `XXXS6`
  - `XXXS8`
- [ ] 对 `FAIL_TARGET` 记录修复前后差异快照

## 架构整改
- [x] 第一轮拆出 `step2_release_utils.py`
- [x] 第一轮拆出 `step2_output_utils.py`
- [x] 第二轮拆出 `step2_trunk_utils.py`
- [x] 第三轮拆出 `step2_validation_utils.py`
- [x] `step2_segment_poc.py` 已降到 `< 100 KB`
- [ ] 继续收敛 `step2_segment_poc.py` 的 `segment_body / tighten / orchestration` 职责

## 文档清理
- [x] 将正式 baseline 主承载收敛到 `spec.md`
- [x] 更新 `plan.md`
- [x] 更新 `tasks.md`
- [x] 更新 `modules/t01_data_preprocess/README.md`
- [x] 更新 `modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
- [ ] 完成文档落点复核并输出清理说明
