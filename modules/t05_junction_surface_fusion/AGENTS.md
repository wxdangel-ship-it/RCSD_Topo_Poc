# T05 Agent Guardrails

本文件只保留 `t05_junction_surface_fusion` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- T05 分 Phase 1 surface fusion 与 Phase 2 RCSD junctionization / relation 发布。
- Phase 1 不输出 `intersection_match_all.geojson`，不 split / cut / break `RCSDRoad`，不新增 `RCSDNode`。
- Phase 2 不回改 Phase 1 融合逻辑或 `junction_anchor_surface.gpkg`，不原地修改输入 `RCSDRoad / RCSDNode / nodes`。
- T03/T04 只消费 formal accepted 发布面；rejected、runtime_failed、review-only 和 reject stub 不进入主图层。
- 不新增 repo CLI、root `scripts/`、`tools/`、Makefile 目标、模块 `run.py` 或模块 `__main__.py`。
