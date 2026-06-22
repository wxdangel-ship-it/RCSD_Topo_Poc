# T07 Agent Guardrails

本文件只保留 `t07_semantic_junction_anchor` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- T07 只处理语义路口级锚定和 relation 补锚，不处理 Segment。
- 不读取、生成或统计 `segment.gpkg`，不解析 `pair_nodes / junc_nodes`。
- `kind_2` 是当前正式类型判断字段；不要从局部样本反推 `kind_2`、`mainnodeid` 或 `RCSDIntersection` 语义。
- Step3 只消费 T05 成功 relation 和输入 `RCSDNode` 做补锚，不独立建立 T 型路口 surface 关系。
- 不新增 repo CLI、`tools/`、Makefile 目标、模块 `run.py` 或模块 `__main__.py`。
