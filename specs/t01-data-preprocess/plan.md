# T01 计划

## 当前阶段
- `正式版业务语义修正`

## 本轮目标
1. 统一 node 输入约束为 `closed_con in {2,3}`
2. 统一排除 `road_kind = 1` 的封闭式道路
3. 在 trunk / 最小闭环 validation 中加入 `50m` 上下行最大垂距 gate
4. 在 side component / 旁路吸收中加入 `50m` 侧向距离 gate
5. 运行 `XXXS` 官方回归并产出 freeze compare 审计结果

## 本轮边界
- 不新增新的构段轮次
- 不引入新的环岛特例业务逻辑
- 不更新现有 freeze baseline
- 若与现有 freeze 不一致，只生成 candidate baseline 包与差异报告

## 实施顺序
1. 梳理并统一 `closed_con` / `road_kind` 业务使用点
2. 将两个 `50m` gate 接入 Step2 trunk / segment 收敛路径
3. 补充静态审计文档与契约文档
4. 运行 pytest
5. 运行 `XXXS` 官方入口 + freeze compare
6. 如有差异，生成 freeze candidate 包
