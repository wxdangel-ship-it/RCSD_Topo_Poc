# 03 Context And Scope

## 输入上下文

- 本轮正式输入是本地 case-package。
- 典型数据根当前采用 `/mnt/e/TestData/POC_Data/T02/Anchor_2`。
- full-input / candidate discovery 仍属于工程前置层，不计入 Step1 业务本体。

## 上游关系

- `t01_data_preprocess` 提供基础道路与 node 事实源。
- `t02_junction_anchor` 提供可参考的 Stage4 业务逻辑与 continuous chain 既有实践；T04 只继承理解与审计经验，不保留运行时代码依赖。
- `t03_virtual_junction_anchor` 提供可参考的实现逻辑、模块级 batch / review / summary 组织模式与产物风格；T04 只继承理解、审计与组织经验，不保留运行时代码依赖，也不直接拷贝实现。

## 输出边界

- T04 当前正式输出边界已扩展到 Step1-7。
- `Step1-4` 输出中间结果与 Step4 review 工件，作为 Step5-7 的稳定上游输入。
- `Step5-6` 输出支撑域约束、最终组装结果与组装审计。
- `Step7` 输出 `accepted/rejected` 二态发布层、summary 与 audit，不把审计层当作第三种正式状态。
