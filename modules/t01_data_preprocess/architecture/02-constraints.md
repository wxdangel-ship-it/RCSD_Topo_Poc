# 02 约束

## 状态
- 当前状态：`模块级约束说明`
- 来源依据：
  - 仓库级执行规则
  - 当前 working-layer / staged-runner accepted 语义

## 全局约束
- 当前模块只处理普通道路上的双向路段构建。
- 当前不覆盖：
  - 封闭式道路的路段提取
  - 普通道路上的单向路段提取
- 当前正式输入约束：
  - node：`closed_con in {2,3}`
  - road：`road_kind != 1`
- 后续业务判断统一使用：
  - `grade_2`
  - `kind_2`
- raw `grade / kind` 只保留为初始化、审计和展示字段。
- 统一距离门控：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- 以上 50m gate 适用于当前所有双向构段阶段：
  - `Step2 / Step4 / Step5A / Step5B / Step5C`

## 协作约束
- 模块根目录不放 `SKILL.md`
- 模块长期真相优先沉淀到 `architecture/*` 与 `INTERFACE_CONTRACT.md`
- 新的活动基线不得 silent 覆盖
- 后续性能优化只要与当前三样例活动基线不一致，都必须先由用户复核
