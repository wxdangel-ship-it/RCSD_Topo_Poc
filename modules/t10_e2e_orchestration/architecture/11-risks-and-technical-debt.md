# 11 Risks And Technical Debt

## 1. 当前风险

- T09 模块文档面缺失，T10 只能基于当前实现和项目级登记识别 T09 handoff。
- T09 当前实现与“消费 T06 F-RCSD 承载关系”的长期口径仍需进一步对齐。
- T05 工作区存在未提交改动，涉及 Phase2 `swsdnode_out / yes_nr` 输出链路；T10 本轮不处理该改动。
- Case package v1 还不是空间切片包，不能作为内网小样本数据子集直接运行。
- `suggest` 只能生成候选列表，不能证明候选确实存在业务问题；候选真实性仍需后续 Case 分析。

## 2. 后续债务

- 接入真实 T01-T09 runner。
- 实现 Case 空间切片与依赖补齐。
- 将 selector evidence 扩展为模块级稳定 schema，而不是仅靠通用字段匹配。
- 将 T05 / T06 / T09 下游消费统一收敛为文件级输入。
- 补齐 T09 模块文档面。
