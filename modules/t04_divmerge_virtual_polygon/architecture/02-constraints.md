# 02 Constraints

## 治理约束

- 先文档、后代码。
- 新模块必须纳入项目级治理索引。
- 默认禁止新增执行入口；本轮仅保留模块内 runner。

## 业务约束

- Step1 不提前做事实解释或几何。
- Step2 只定义 SWSD 负向上下文。
- Step4 只做事实解释与 review，不做最终 polygon。

## 工程约束

- 可以参考 T02 Stage4 的 Step2/3/4 业务逻辑与已验证判定思路，但 T04 运行时不得直接 import / 调用 T02 模块代码；所需逻辑必须在 T04 私有实现中落地。
- 优先复用 T03 的 case-package / batch / review 输出组织。
- 不把 T02 大 orchestrator 平移到 T04 主结构。
