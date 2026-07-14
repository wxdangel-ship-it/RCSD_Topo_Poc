# P02 Agent Guardrails

- P02 只做武汉局部实验编排、人工关系转换与证据收口，不接管 T08/T01/T05/T06 算法职责。
- 原始人工关系不可覆盖；Tool5 后转换关系必须保留逐行 lineage。
- 缺失的道路面、导流带、RCSDIntersection 和未经确认的端点引用只按 unavailable/input-integrity 审计表达；完整原始 Road/Node 不裁剪、不伪造、不 silent fix。用户逐 Road、逐字段确认的临时 `SNodeId/ENodeId` 修正只能在 P02 copy-on-write 工作副本中执行，并必须校验旧值、保留要素数/ID/几何、输出独立审计；不得读取 `NodeLid/CrossLid` 或据几何推断其它端点。
- 不把局部实验替换率直接提升为全量业务结论。
- 当前只允许用户于 2026-07-14 明确授权的正式入口 `scripts/p02_run_wuhan_internal_case.py`；不得借此新增 repo CLI、Makefile 目标、模块 `run.py`、模块 `__main__.py` 或其它 P02 长期入口。
