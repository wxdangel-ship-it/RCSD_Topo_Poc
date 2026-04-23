# 01 Introduction And Goals

## 模块目标

- 为分歧 / 合流 / 连续复杂路口建立 T04 的正式模块外壳。
- 将线程级已确认的 Step1-7 冻结需求沉淀为 repo 内 source-of-truth。
- 维持 Step1-4 的稳定上游结果包与 Step4 目视审计输出。
- 进入 Step5-7 正式研发实现阶段，并默认遵循 SpecKit 的 `Product / Architecture / Development / Testing / QA` 五视角覆盖。

## 当前正式范围

- Step1：candidate admission
- Step2：high-recall local context
- Step3：topology skeleton
- Step4：fact event interpretation
- Step5：geometric support domain
- Step6：polygon assembly
- Step7：final acceptance and publishing

## 当前非目标

- 不新增 repo 官方 CLI
- 不直接 import / 调用 / 硬拷贝 T03 模块代码
- 不保留最终 `review` 作为第三种正式发布状态
