# 11 Risks And Technical Debt

## 1. 当前风险

- T09 模块文档面已补齐，T10 后续应基于 T09 模块契约识别 handoff。
- T09 仍缺少 RCSD Laneinfo 与轨迹通行证据，T10 Case 分析只能把该问题作为下游业务证据缺口暴露。
- T05 工作区存在未提交改动，涉及 Phase2 `swsdnode_out / yes_nr` 输出链路；T10 本轮不处理该改动。
- Case package v1 已支持按半径生成外部输入空间切片，并补齐道路端点节点依赖；但局部 replay 仍可能受 T03 / T04 自动候选发现、T05 关系证据完整性和 T06 业务门槛影响。
- `suggest` 只能生成候选列表，不能证明候选确实存在业务问题；候选真实性仍需后续 Case 分析。
- T10 Case runner 通过既有脚本或 callable 串联，不改变 T01-T09 算法；若上游模块脚本当前缺少更细粒度 CaseID 选择能力，T10 只能记录该限制，不能在编排层 silent fix。

## 2. 后续债务

- 继续收敛 T03 / T04 的 CaseID 显式选择能力，降低局部 replay 对自动候选发现的依赖。
- 将 selector evidence 扩展为模块级稳定 schema，而不是仅靠通用字段匹配。
- 将 T05 / T06 / T09 下游消费统一收敛为文件级输入。
- 持续跟随 T09 契约更新 handoff slot 与 Case 证据包说明。
