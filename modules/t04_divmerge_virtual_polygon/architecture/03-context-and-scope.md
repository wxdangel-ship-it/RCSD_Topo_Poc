# 03 Context And Scope

## 输入上下文

- 本轮正式输入是本地 case-package。
- 典型数据根当前采用 `/mnt/e/TestData/POC_Data/T02/Anchor_2`。
- full-input / candidate discovery 仍属于工程前置层，不计入 Step1 业务本体。

## 上游关系

- `t01_data_preprocess` 提供基础道路与 node 事实源。
- `t02_junction_anchor` 提供 Stage4 可复用核心算法与 continuous chain 既有实践。
- `t03_virtual_junction_anchor` 提供模块级 batch / review / summary 组织模式。

## 输出边界

- T04 当前输出的是 Step1-4 中间结果与 Step4 review 工件。
- 这些结果为后续 Step5-7 提供稳定上游输入，不等同最终发布层。
