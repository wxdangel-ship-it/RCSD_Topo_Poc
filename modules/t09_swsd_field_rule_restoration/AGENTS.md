# T09 Agent Guardrails

本文件只保留 `t09_swsd_field_rule_restoration` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- T09 负责还原 SWSD 现场通行规则证据，并投影显式禁止通行证据到 F-RCSD restriction。
- 不生成 F-RCSD `RoadNextRoad`。
- 不修改 T06、T08、SWSD 或 F-RCSD 输入。
- 不根据缺少 allowed evidence 自动推导 prohibited。
- 不把 topology not applicable 或 direction incompatible 表达为交通规则禁止。
- 不新增 repo CLI、root `scripts/`、Makefile 目标、模块 `run.py` 或模块 `__main__.py`。
