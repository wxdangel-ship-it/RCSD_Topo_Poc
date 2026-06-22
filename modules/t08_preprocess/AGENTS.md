# T08 Agent Guardrails

本文件只保留 `t08_preprocess` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- T08 是正式预处理、质检、修复和显性化模块，不是临时工具箱。
- 不根据局部样本反推 Road / Node 字段语义。
- Tool4 不做契约外拓扑重塑；只按契约修复路口类型。
- T08 成果输出文件名必须在扩展名前以 `_toolX` 结尾。
- 不修改 T00 Tool4 / Tool5 契约，除非任务明确授权。
- 不在模块根目录新增 `SKILL.md`。
