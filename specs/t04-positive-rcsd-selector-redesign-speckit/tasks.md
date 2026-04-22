# Tasks: T04 Step4 正向 RCSD 选择器正式重构（aggregated / polarity / presence）

## Specify

- [x] 收口 GPT 新冻结口径
- [x] 固化 role mapping 规约页
- [x] 同步线程需求与模块契约

## Implement

- [x] 改造 `rcsd_selection.py`
- [x] 引入 `aggregated_rcsd_unit`
- [x] 引入 `positive_rcsd_present`
- [x] 引入 `axis_polarity_inverted`
- [x] 独立输出 `required_rcsd_node`
- [x] 接通 `event_interpretation.py`
- [x] 接通 `outputs.py` / `review_audit.py` / `review_render.py`
- [x] 更新 smoke / selector 断言

## Verify

- [x] 跑固定 pytest
- [x] 跑 Anchor_2 回归
- [x] 对比主证据 baseline
- [x] 串行吸收测试 / QA 结论
