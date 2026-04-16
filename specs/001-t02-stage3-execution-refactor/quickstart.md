# Quickstart: T02 Stage3 Execution-Layer Refactor

## 1. 当前阶段目标

当前阶段只做执行层重构计划与结构迁移，不直接继续 `V4` case 修补。

## 2. 执行顺序

1. 冻结 `round_15` 为“结构未完成”基线
2. 定义 Step3~7 显式结果对象
3. 拆 Step7 为唯一终裁层
4. 拆 Step4 / Step5 / Step6 执行层
5. 收缩 `virtual_intersection_poc.py` 为 orchestrator
6. 重构审计链
7. 做结构验收
8. 验收通过后，再恢复 `61-case` 全量与目视审查

## 3. 当前不允许做的事情

- 不继续按 `724123 / 769081 / 851884` 直接追加 late pass
- 不先追 `V4` 数量下降
- 不用 packaging contract 达成代替执行层重构达成
- 不在结构门槛未通过时恢复 `Anchor 61` 正式全量

## 4. 恢复全量前的最小检查

- Step3~7 结果对象已存在
- Step7 之后不再改几何
- `root_cause_layer / visual_review_class` 不再由字符串反推
- 保护锚点不回退

## 5. 恢复全量后的验证顺序

1. 先验证 `正常准出正确性`
2. 再验证 `目视分类正确性`
3. 最后才重新进入 `V4`、再到 `520394575`
