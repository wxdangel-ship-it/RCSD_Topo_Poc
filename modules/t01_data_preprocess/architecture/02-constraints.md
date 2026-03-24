# 02 约束

## 全局业务约束
- 当前模块仅处理非封闭式双向道路场景。
- 当前不覆盖：
  - 封闭式道路场景
  - 单向 Segment

## 输入约束
- node：
  - `closed_con in {2,3}`
- road：
  - `road_kind != 1`
  - `formway != 128`

## 字段启用约束
- 后续业务判断统一使用：
  - `grade_2`
  - `kind_2`
- raw `grade / kind` 仅保留为输入信息与审计信息。

## 统一构段约束
- `Step2 / Step4 / Step5A / Step5B / Step5C` 共享：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- T 型路口竖向阻断规则：
  - 仅对应 `kind_2 = 2048`
  - 不对应 `kind_2 = 4`
- 更低等级构段不得跨越更高等级历史边界语义路口。

## 治理约束
- 模块级 steady-state 源事实沉淀在：
  - `architecture/*`
  - `INTERFACE_CONTRACT.md`
- `specs/` 不再承载正式业务 baseline 正文。
