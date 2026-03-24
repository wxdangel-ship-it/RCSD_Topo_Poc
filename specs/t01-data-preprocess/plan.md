# T01 计划

## 当前阶段
- `temporary final-segment baseline governance`
- `implementation-audit driven repair`
- `formal baseline documentation cleanup`

## 当前目标
1. 维护 `XXXS*` 临时最终 Segment 基线，只用于回归闸门，不覆盖 accepted baseline。
2. 按审计结果拆批整改实现，而不是继续混修样例问题。
3. 将正式文档收敛到当前修订版 accepted baseline。

## 临时基线状态

### PASS_LOCKED
- `XXXS`
- `XXXS2`
- `XXXS3`
- `XXXS4`
- `XXXS6`
- `XXXS8`

### FAIL_TARGET
- `XXXS5`
- `XXXS7`

### 说明
- `XXXS` 当前带有一处已记录的临时接受差异，后续如需重新打开，必须单独立项，不与当前批次混修。
- 临时基线记录落在：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`

## 实施顺序
1. 先以临时基线做最终 Segment 非回退闸门。
2. 按审计结果分批整改实现：
   - 批次 A：`Step4 / Step5A / Step5B` 不得压扁当前 `grade_2 / kind_2`
   - 批次 B：`Step5A / Step5B / Step5C` 改为逐轮 refresh 后再进入下一轮
   - 批次 C：去掉 `Step2` 对 raw `grade / kind` 的业务 fallback
   - 批次 D：补齐 `formway = 128` 在 Step6 的一致过滤
3. 每一批完成后，都必须：
   - 对 `PASS_LOCKED` 做最终 Segment 非回退检查
   - 记录 `FAIL_TARGET` 前后差异
4. 业务输出稳定后，再继续结构整改与文档收口。

## 文档清理落点
- accepted baseline 主体：`modules/t01_data_preprocess/architecture/06-accepted-baseline.md`
- 架构索引：`modules/t01_data_preprocess/architecture/overview.md`
- 模块契约：`modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
- 模块说明：`modules/t01_data_preprocess/README.md`
- spec-kit 计划与过程文档：
  - `spec.md`
  - `plan.md`
  - `tasks.md`

## 边界
- 不自动更新 freeze baseline。
- 不把临时最终 Segment 基线误写成 accepted baseline。
- 不通过 silent fix 掩盖问题。
- 架构整改优先抽取共性模块与压缩超大文件职责，不顺手扩大为新的业务算法开发。
