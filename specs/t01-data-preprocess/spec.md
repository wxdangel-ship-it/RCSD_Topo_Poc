# T01 Spec-Kit 治理规格

## 文档定位
- 本文档是当前 T01 治理/整改轮次的 spec-kit 规格说明。
- 它不再承载 steady-state 的 accepted baseline 正文。

## 正式业务规格落点
- 当前 accepted baseline 主体见：
  - [06-accepted-baseline.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md)
- 模块级契约见：
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)

## 当前治理目标
1. 以 `XXXS*` 临时最终 Segment 基线作为非回退闸门。
2. 按实现审计批次整改 `Step2 / Step4 / Step5 / Step6` 的关键偏差。
3. 清理文档角色边界，确保：
   - `architecture/*` 承载模块级源事实
   - `INTERFACE_CONTRACT.md` 承载模块契约
   - `README.md` 承载使用说明
   - `specs/` 承载当前治理轮次文档

## 当前整改批次
- 批次 A：修正 `Step4 / Step5A / Step5B` 对当前 `grade_2 / kind_2` 的压扁
- 批次 B：引入 `Step5A / Step5B / Step5C` 逐轮 refresh
- 批次 C：去掉 `Step2` 对 raw `grade / kind` 的业务 fallback
- 批次 D：补齐 `formway = 128` 在 Step6 的一致过滤

## 当前样例治理边界
- `PASS_LOCKED`
  - `XXXS / XXXS2 / XXXS3 / XXXS4 / XXXS6 / XXXS8`
- `FAIL_TARGET`
  - `XXXS5 / XXXS7`
- 临时样例基线记录：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`
