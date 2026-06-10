# 11 Risks And Technical Debt

## 1. 当前风险

- T09 模块文档面已补齐，T10 后续应基于 T09 模块契约识别 handoff。
- T09 仍缺少 RCSD Laneinfo 与轨迹通行证据，T10 Case 分析只能把该问题作为下游业务证据缺口暴露。
- T05 工作区存在未提交改动，涉及 Phase2 `swsdnode_out / yes_nr` 输出链路；T10 本轮不处理该改动。
- Case package v1 还不是空间切片包，不能作为内网小样本数据子集直接运行。
- `suggest` 只能生成候选列表，不能证明候选确实存在业务问题；候选真实性仍需后续 Case 分析。

## 2. 后续债务

- 接入真实 T01-T09 runner。
- 实现 Case 空间切片与依赖补齐。
- 将 selector evidence 扩展为模块级稳定 schema，而不是仅靠通用字段匹配。
- 将 T05 / T06 / T09 下游消费统一收敛为文件级输入。
- 持续跟随 T09 契约更新 handoff slot 与 Case 证据包说明。
