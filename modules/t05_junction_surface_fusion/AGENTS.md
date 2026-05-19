# T05 模块执行约束

本目录只约束 `t05_junction_surface_fusion`。

## 当前阶段

- T05 分为两个独立阶段。
- 当前模块实现 Phase 1：多源路口面融合发布。
- 当前模块新增 Phase 2：消费 Phase 1 成果，执行 RCSD junctionization 与 SWSD-RCSD 关系生产。
- Phase 1 输出 `junction_anchor_surface.gpkg`、fusion audit 与 `summary.json`。
- Phase 2 输出 `intersection_match_all.geojson`、copy-on-write RCSDRoad/RCSDNode 与审计。

## 禁止事项

- Phase 1 不输出 `intersection_match_all.geojson`，不建立 SWSD-RCSD 最终关系表。
- Phase 1 不做 `RCSDRoad` split / cut / break，不新增 `RCSDNode`。
- Phase 2 不得回改 Phase 1 融合逻辑或 `junction_anchor_surface.gpkg`。
- Phase 2 不得原地修改输入 `RCSDRoad / RCSDNode / nodes`。
- 不修改 T02/T03/T04 输入或算法主链。
- 不新增 repo CLI、`scripts/`、`tools/`、`Makefile` 或模块 `run.py` / `__main__.py`。

## 实现边界

- 只允许模块内 callable runner：`run_t05_junction_surface_fusion(...)` 与 `run_t05_phase2_rcsd_junctionization_and_relation(...)`。
- 输入面必须统一到 `EPSG:3857` 后融合。
- T03/T04 仅消费 formal accepted 发布面；rejected、runtime_failed、review-only 与 reject stub 不得进入主图层。
- 几何清理只允许最小合法化，并必须写入 audit。
- Phase 2 关系输出 CRS 必须为 CRS84 / WGS84 lon-lat。
- Phase 2 失败关系必须 `status = 1` 且 `base_id = 0`。
