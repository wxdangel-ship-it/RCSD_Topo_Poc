# T06 模块执行约束

本目录只约束 `t06_segment_fusion_precheck`。

## 当前阶段

- 当前模块正式范围仅覆盖 T06 前两步：
  - Step1：识别可参与融合的 SWSD Segment 单元。
  - Step2：基于 T05 Phase 2 relation 与 copy-on-write RCSD 网络抽取 RCSD Segment candidate，并执行趋势类硬筛。
- 本轮不执行 Segment 替换，不重塑路口，不修改 T01 / T05 输出。

## 禁止事项

- 不新增 repo CLI、`tools/`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- 当前唯一 T06 repo 级脚本入口是 `scripts/t06_run_innernet_precheck.py`，只作为内网 Step1 + Step2 运行包装，底层仍调用模块内 runner。
- 不原地修改 `segment.gpkg`、`nodes.gpkg`、`intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg` 或 `swsd_roads_path`。
- 不根据局部数据反推上游字段语义；字段语义以 T01 / T05 / T06 契约为准。
- 不把 `pair_nodes` 顺序或 `segmentid A_B` 顺序当作 SWSD 单向方向。

## 实现边界

- 只允许模块内 callable runner：
  - `run_t06_step1_identify_fusion_units(...)`
  - `run_t06_step2_extract_rcsd_segments(...)`
  - `run_t06_segment_fusion_precheck(...)`
- 内网执行脚本 `scripts/t06_run_innernet_precheck.py` 只能转发到 `run_t06_segment_fusion_precheck(...)`，不得内置替代业务逻辑。
- Step1 按 `pair_nodes + junc_nodes` 的语义路口 ID 集合判断 EVD 与 anchor/fallback 资格；其中 `pair_nodes.kind_2 in {1,4096,8192}` 的节点不参与 `has_evd / is_anchor` 判定并视为通过，`junc_nodes` 不适用该豁免。
- Step2 只接受 `intersection_match_all.geojson` 中 `status = 0` 且 `base_id > 0` 的 relation。
- `junc_nodes` 在 RCSD 抽取中是内部通过 + 侧向阻断，不是 hard-stop。
- SWSD 单向方向必须从 `swsd_roads_path` 中 Segment road body 推导。
- SWSD 单向 + RCSD 双向必须 rejected。

## 必做验证

- 单元测试必须覆盖 Step1 eligibility、relation mapping、SWSD 单向方向推导、RCSD candidate 抽取、junc side blocking、趋势硬筛与 runner 输出。
- GIS / 拓扑任务必须显式覆盖 CRS、拓扑一致性、几何语义、审计追溯与性能可验证性。
- 提交前至少执行 T06 测试与 `git diff --check`。
