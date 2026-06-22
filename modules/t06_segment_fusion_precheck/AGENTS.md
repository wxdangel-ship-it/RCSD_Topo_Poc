# T06 Agent Guardrails

本文件只保留 `t06_segment_fusion_precheck` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- 当前正式范围为 Step1 fusion unit、Step2 replacement plan / problem registry、Step3 Segment replacement。
- 不原地修改 `segment.gpkg`、`nodes.gpkg`、`intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg` 或 Step2 输出。
- Step3 优先消费 Step2 `replacement_plan`；旧 replaceable / special / group audit 仅作为兼容 fallback。
- 不把 `pair_nodes` 顺序或 `segmentid A_B` 顺序当作 SWSD 单向方向。
- 不根据局部数据反推上游字段语义；字段语义以 T01 / T05 / T06 契约为准。
- 不新增 repo CLI、`tools/`、Makefile 目标、模块 `run.py` 或模块 `__main__.py`。
