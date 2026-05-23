# 11 Risks And Technical Debt

## 当前风险

- T07 从 T02 Step1 / Step2 继承业务语义，但不能继承 T02 的 Segment 候选域；实现时若复用 T02 代码过多，容易重新引入 Segment 依赖。
- `mainnodeid = 0` 在不同模块存在不同解释边界；T07 当前按 T02 口径只声明空值 singleton，如需把 `0` 视为空值必须另行确认。
- `kind_2 = 128` 当前只进入 Step1 / Step2 语义级锚定，不进入 T02 Stage4 complex polygon。

## 技术债控制

- 首轮实现应保持小文件分层，避免复制 T02 大文件。
- 测试应拆分为 Step1、Step2 与 no-Segment dependency，不集中到单个超大测试文件。
- 除已登记的内网脚本外，若后续新增入口，必须先走入口治理并同步 registry。
