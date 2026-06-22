# 05 质量要求

## 1. Phase 1 正确性

- 只消费 formal accepted surface candidate。
- 主图层 `mainnodeid` 必须非空。
- 不同 `mainnodeid` 即使几何相交，也不得仅凭几何合并。
- 输出 CRS 固定为 `EPSG:3857`。
- Phase 1 不输出 `intersection_match_all.geojson`，不修改 RCSDRoad/RCSDNode。

## 2. Phase 2 正确性

- 成功 relation 必须 `status=0 / base_id>0`，失败 relation 必须 `status=1 / base_id=0`。
- 一个 SWSD `target_id` 在主表中最多一条成功 relation。
- 多个 RCSD 候选可合并时先 grouping，再输出唯一 relation；无法合并时输出 blocking error。
- T03/T04 road-only 场景才进入 RCSDRoad split；`kind_2=64` 环岛只归组已有 RCSDNode，不 split RCSDRoad。
- T07 relation-only target 即使没有 Phase 1 surface，也可以进入最终 relation。

## 3. GIS 与拓扑要求

- Phase 1 空间处理使用 `EPSG:3857`，Phase 2 relation GeoJSON 输出 CRS84。
- RCSDRoad split 点靠近端点时必须复用端点或审计失败，不生成极短段。
- 新增 RCSDRoad 的端点必须存在于 `rcsdnode_out.gpkg`。
- 被 split 的原始 RCSDRoad 不进入 active `rcsdroad_out.gpkg`。
- 输入 RCSDRoad/RCSDNode 不得原地修改。

## 4. 回归要求

- Phase 1 测试覆盖 schema、CRS、accepted 过滤、unanchored skipped、多源融合、冲突 audit 和不生成关系表。
- Phase 2 测试覆盖 direct relation、grouping、road-only split、环岛、T07 relation-only、cardinality QC、T10 feedback 消费边界和 T03 handoff backfill。

## 5. 性能要求

Phase 2 full-input 运行需要记录 decision plan 规模、只读 / 可变 target 数、阶段级耗时、输出文件耗时和文件大小。只读关系可并行；RCSDRoad split、RCSDNode grouping 和新增 id 分配当前保持串行，避免 copy-on-write 状态竞争。
