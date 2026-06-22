# T00 Agent Guardrails

本文件只保留 `t00_utility_toolbox` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- `T00` 是 Support Retained 工具集合，不是 Skill，也不是业务生产模块。
- 不直接生成 RCSD 业务要素，不把工具能力扩写成业务主链。
- 不因编号连续性自动新增工具范围；正式工具清单以 `SPEC.md` 与 `INTERFACE_CONTRACT.md` 为准。
- 不新增模块级私有入口；repo 级入口必须先满足仓库入口治理规则。
- 不在模块根目录新增 `SKILL.md`。
