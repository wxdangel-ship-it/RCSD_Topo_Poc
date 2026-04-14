# T02 / Stage3 Anchor61 架构优化分析

## 1. 是否残留“先修 case”任务

- 不允许
- 当前任务拆分仅围绕：
  - 契约同步
  - Step3/5/6/7 骨架重构
  - 输出/审计单轨化
  - Anchor61 正式验收接线

## 2. 是否误混入 full-input 正式交付

- 不允许
- full-input 本轮仅作 regression
- 任何 full-input 输出仅用于回归证明，不形成正式 Stage3 交付结论

## 3. 是否扩大到 Stage4

- 不允许
- Stage4 不在本轮范围内

## 4. 是否允许不受控改测试

- 不允许
- 测试修改仅限：
  - Anchor61 正式验收层接线
  - 与主契约明确冲突的断言修正

## 5. 是否继续向 monolith 堆逻辑

- 不允许
- 本轮要求将 canonical live truth 从 `virtual_intersection_poc.py` 迁出

## 6. Round 1 完整方案范围

- 完成 spec-kit 工件
- 完成最小契约同步
- 建立 Anchor61 manifest 与正式验收层骨架
- 完成 Step3 canonical result layer
- 完成 Step7 pure verdict 主路径
- 将 `virtual_intersection_poc.py` 中与 Step3/Step7 强相关的 live truth 迁出主导权
