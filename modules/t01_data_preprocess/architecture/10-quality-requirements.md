# 10 质量要求

## 可理解
- accepted baseline、模块契约、实现整改计划必须能分别从：
  - `architecture/*`
  - `INTERFACE_CONTRACT.md`
  - `specs/t01-data-preprocess/*`
  直接读出，不允许角色混写。

## 可运行
- official runner 应稳定完成：
  - `working bootstrap`
  - `roundabout preprocessing`
  - `Step1-Step5C`
  - `Step6`

## 可诊断
- `debug=true` 时必须保留足够的中间产物。
- trunk gate、side gate、T-junction gate、endpoint pool、same-stage arbitration 都应可审计。

## 可回归
- 临时最终 Segment 基线应作为当前整改批次的非回退闸门。
- `PASS_LOCKED` 样例不得回退。
- `FAIL_TARGET` 变更必须记录前后差异。

## 可治理
- 文档、实现、契约、历史归档之间关系必须清晰。
- 关键业务口径不得只存在于 `README`、`history` 或单次对话结论中。
