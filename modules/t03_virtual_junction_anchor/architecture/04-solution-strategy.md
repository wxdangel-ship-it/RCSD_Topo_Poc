# 04 Solution Strategy

- 使用独立 `Step4-5` pipeline 承接冻结 Step3 之后的 RCSD 关联与 foreign 过滤，不回灌 Step3
- 结构拆分为 `step45_loader / step45_rcsd_association / step45_foreign_filter / step45_render / step45_writer / step45_batch_runner`
- `Step4-5` 产出 `required / support / excluded` RCSD 集合、hook zone、foreign context、状态与审计
- 渲染风格沿用 Step3 三态表达，状态命名继续收敛为 `established / review / not_established`
