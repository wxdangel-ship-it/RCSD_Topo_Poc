# 04 Solution Strategy

- 使用新模块承载独立 `Step3` 业务内核与批处理编排
- 结构拆分为 `case_loader / step1_context / step2_template / step3_engine / render / writer / batch_runner`
- `Step3` 只产出 allowed space、三类 negative mask、状态与审计
- 渲染风格继承 T02 认知锚点，但状态命名收敛为 `established / review / not_established`
