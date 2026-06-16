# 04 Solution Strategy

本文件是 T05 的详细版需求 / 落地策略说明。凝练版业务需求见 `../SPEC.md`，稳定输入输出、业务规则和入口契约见 `../INTERFACE_CONTRACT.md`。

## 1. Phase 1 总体策略

T05 Phase 1 使用“标准化 -> 分组 -> 融合 -> 发布”的轻量链路：

1. 读取 T02_INPUT / T03 / T04 surface 与可选 `nodes.gpkg`。
2. 将所有输入几何统一到 `EPSG:3857`。
3. 过滤非 formal accepted 输入。
4. 标准化来源字段、`mainnodeid`、`patch_id`、`kind_2` 与 `junction_type`。
5. 跳过无法解析 `mainnodeid` 的未锚定来源面，并写入 skipped 审计。
6. 按 `mainnodeid` 分组。
7. 对同组面执行单源发布、多源 union 或 primary 选择。
8. 写出 7 字段主图层、fusion audit、skipped 审计与 summary consistency。

## 2. Formal-first 输入策略

- T03 的 batch aggregate `virtual_intersection_polygons.gpkg` 是 formal accepted 聚合层；若存在 `step7_state / final_state / acceptance_class / success` 等 formal 字段，则必须为 accepted。
- T04 只接收 `final_state = accepted`。
- T04 rejected layer、reject stub、reject index、T03 rejected / runtime_failed / review-only 结果不得进入主图层。
- visual / review 字段只可作为兼容属性，不得替代 formal 状态。

## 3. 字段归一策略

- `mainnodeid` 优先取来源面字段，其次通过 `case_id / anchor_id / representative_node_id` 和 `nodes.gpkg` 反查。
- `kind_2` 优先取来源面字段，其次从 `nodes.gpkg` 反查。
- `patch_id` 优先取来源面字段，其次从 `nodes.gpkg` 反查。
- `mainnodeid` 无法反查时不进入主图层。
- `patch_id / kind_2` 无法反查时允许为空，但必须进入 audit 与 summary 计数。

## 4. 融合策略

单源：

- 直接发布。
- `geometry_action = keep_source`
- `fusion_action = single_source`

多源：

- 仅同 `mainnodeid` 可进入同组融合；无 `mainnodeid` 的面已在标准化阶段跳过。
- 几何相交、接触或距离不超过 `2.0m` 时执行 union。
- union 后如形成距离合理的 MultiPolygon，允许发布并审计。
- 不同 `mainnodeid` 不因几何相交自动合并。

Primary：

- 不能安全 union 时选择 primary。
- T03/T04 generated accepted surface 优先于 T02_INPUT。
- T03/T04 同组时按 `kind_2` 域选择 primary，并记录 `t03_t04_same_mainnodeid`。
- `patch_id / kind_2` 冲突写入 audit，不静默覆盖来源事实。

## 5. 几何策略

- 只允许 `make_valid / buffer(0)` 等最小合法化。
- 不做任意外扩、平滑、裁剪或跨 `mainnodeid` dissolve。
- 所有几何清理写入 `geometry_cleaned` 或 audit notes。

## 6. 工程分层

- `models.py`：schema、常量、dataclass。
- `io.py`：读写 GPKG/CSV/JSON 与 run root。
- `normalizer.py`：三类来源标准化与 nodes lookup。
- `fusion.py`：分组、union、primary、冲突审计。
- `outputs.py`：主图层、audit、summary 与 consistency。
- `runner.py`：模块内 callable runner。
- `t03_relation_evidence_backfill.py`：读取 T03 当前 run root 的批次 evidence 与 case 级 step6 状态，生成 T05 Phase 2 handoff 补齐 evidence。

当前不提供 CLI、`tools/`、`Makefile`、`run.py` 或 `__main__.py`。内网执行只提供 `scripts/t05_backfill_t03_relation_evidence_innernet.py` 作为 T03 handoff 补齐入口，不作为 Phase 1 / Phase 2 主 runner。

## 7. Phase 2 总体策略

Phase 2 使用“读取 Phase 1 surface -> 消费 relation evidence -> 场景分流 -> copy-on-write RCSD 处理 -> 关系发布”的链路：

1. 读取 `junction_anchor_surface.gpkg`、fusion audit、final `nodes.gpkg`、原始 `RCSDRoad.gpkg / RCSDNode.gpkg` 与 T07/T03/T04 relation evidence；旧 T02 evidence 仅作为兼容输入。
2. 以 Phase 1 surface 的 `mainnodeid` 作为 Phase 2 target 主键。
3. 预先构建 target 级 decision plan，并统计 direct / grouping / road_split / no_related、只读 target、可变 target 等体量。
4. 先并行处理无需修改 RCSDRoad / RCSDNode 的只读关系构建分支。
5. 再串行处理 T03-A 多 RCSDNode、T04 complex 多 RCSDNode、T03/T04 road-only、`kind_2 = 64` 环岛聚合等会修改 copy-on-write RCSD 状态的分支。
6. 已有 RCSD 语义路口直接输出关系。
7. T03-A 多 RCSDNode 与 T04 complex 多 RCSDNode 执行 RCSDNode grouping，不打断 road。
8. T03 road-only 与 T04 fallback road-only 进入 RCSDRoad split，生成 RCSDNode，再建立关系。
9. `kind_2 = 64` 环岛不依赖 road-only split，而是基于 SWSD node 覆盖面、`roadtype = 8` 环岛 road buffer 和 RCSDNode 连通性筛选，归组已有 RCSDNode 后建立关系。
10. 完全无 RCSD 或 split/grouping 失败时输出失败关系，统一 `status = 1 / base_id = 0`。
11. 多个 RCSD 候选可合并时归组为一个 RCSD 语义路口；无法合并时输出 blocking error，不写主表 relation。
12. 输出 `intersection_match_all.geojson`、copy-on-write RCSDRoad/RCSDNode、增量层、audit、blocking errors、summary 与聚合 performance 打点。

Phase 2 不重新融合路口面，不修改 Phase 1 `junction_anchor_surface.gpkg`，不修改 T07/T03/T04 主链，也不原地修改输入 RCSD 文件。

当前 T03 批次级 `t03_swsd_rcsd_relation_evidence.*` 字段完整时，Phase 2 直接消费原始 T03 evidence。若遇到旧 T03 run 缺少 T05 场景分流所需的 `required_rcsdnode_ids / support_rcsdroad_ids`，可执行 T05 handoff 补齐工具，从 T03 已输出的 `cases/<case_id>/step6_status.json` 或 `step6_audit.json.inputs` 读取正式字段，写出独立的 `t03_swsd_rcsd_relation_evidence_backfilled.*`。Phase 2 再消费补齐后的 evidence。

## 8. Phase 2 场景策略

- T07/T03/T04 已产出的成功 relation evidence：若提供 `status_suggested = 0` 与可用 `base_id_candidate`，Phase 2 优先直接消费该关系，不再用同 row 的 `required_rcsdnode_ids` 重新归组；历史锚定 relation-only target 即使没有 Phase 1 surface，也进入 `intersection_match_all.geojson`。
- T02 existing RCSDIntersection evidence：旧批次兼容路径，若提供可用 `base_id_candidate`，直接建立关系。
- T03-A：`required_rcsdnode_ids` 为 1 时直接关系；多个时归组，组内所有 node `mainnodeid` 填主 node id。
- T03 existing role mismatch：只有 `base_id_candidate / required_rcsdnode_ids` 明确指向 RCSD 语义路口时才直接关系；`association_class=B` 不自动等于该场景。
- T03 road-only：`relation_state = rcsd_present_not_junction` 且存在 support RCSDRoad，同时不存在可用 RCSDNode 语义核心时，按 SWSD 语义点投影 split。
- T03 road-only 端点场景：若投影点落在 RCSDRoad 起终点阈值内，不生成极短 split 段，复用最近端点 RCSDNode 并按需归组。
- T04 required RCSDNode：直接关系。
- T04 complex：多个可用 RCSDNode 归组。
- T04 `main_evidence_with_rcsdroad_fallback`：优先使用 `fact_reference_point` 投影 split。
- T04 `no_main_evidence_with_rcsdroad_fallback_and_swsd`：使用 SWSD semantic point 投影 split。
- T04 fallback 若 relation evidence 缺少场景字段，可从 accepted layer、summary、audit 或 case-level audit 补读；补读失败不得 silent fallback。
- SWSD 环岛 `kind_2 = 64`：所有 SWSD 子 node 必须被 Phase 1 路口面覆盖；覆盖面与 `RCSDRoad.roadtype = 8` 的 road `10m` buffer 合并后形成环岛候选面；候选 RCSD 语义路口必须全组 node 都在该面内，且候选语义路口之间通过 `roadtype = 8` 的 RCSDRoad 连通，才进入 RCSDNode grouping。
- Phase 2 入口对 SWSD 语义路口主键统一做整数 canonical normalization，覆盖 evidence `target_id`、surface `mainnodeid`、nodes `id/mainnodeid`、known target 索引和最终 relation/audit 输出；`622700016` 与 `622700016.0` 在 T05 内部视为同一 target，并统一输出 `622700016`。
- Phase 2 不改写 final SWSD nodes，也不输出 SWSD node copy-on-write 标记层；`no_related_rcsd` 仅通过失败 relation、junctionization audit 与 module relation audit 表达。
- Cardinality QC 中，`one_target_to_many_base` 与重复 success target 仍是阻断错误，必须从主 relation 剔除并令 `summary.passed=false`；`many_target_to_one_base` 只作为非阻断审计保留，relation 继续发布给 T06，由 T06 的 Segment 端点 distinct、buffer、方向性和替换计划继续判定。
- T04 `road_surface_fork` partial handoff 若同时给出局部 `base_id_candidate / required_rcsd_node_ids` 与原语义主点 `semantic_required_rcsd_node_ids`，Phase 2 必须先把这些 RCSDNode 按 `group_existing_rcsd_nodes` 归组，再发布唯一 relation；该修正应在 T05 完成，不交给 T06 双向 Segment 兜底。
- T10 `T10_SIDE_GROUP` 与 `T10_PAIR_ANCHOR_CLUSTER` 仅作为补充证据：只能依附同 target 已有 T07/T03/T04/T02 成功 relation，或依附 T03/T04 road-only split 决策补充 RCSDNode grouping；不得单独创建 SWSD-RCSD relation，也不得覆盖 road-only split 主决策。
- T07 `existing_rcsdintersection_matched` 的 `base_id_candidate` 必须先证明能落到 `rcsdnode_out.id/mainnodeid` 或可由 Phase 1 surface 内 RCSDNode 重绑定 / 归组后，才允许发布成功 relation；无法证明时输出失败 relation，不用最近点或 T06 结果反推。
- `relation_graph_consumability_audit.*` 用于审计成功 relation 的 base 是否可被 `rcsdroad_out / rcsdnode_out` 图消费。该审计是质量追溯信号，不作为本阶段强制阻断项。

## 9. Phase 2 拓扑策略

- 新 `RCSDRoad.id / RCSDNode.id` 从输入与已生成 id 的全局最大值加 1 稳定递增。
- 被 split 的原始 RCSDRoad 不进入 active `rcsdroad_out.gpkg`，仅在 audit 中保留。
- 投影点过近端点时不 split，复用端点 RCSDNode；多个端点节点命中时按现有 grouping 规则归为一个 RCSD 语义路口。
- split 后新 road 继承原 road 非 `id / snodeid / enodeid / geometry` 字段，`direction` 默认继承。
- `rcsdroad_out.gpkg` 是 copy-on-write 主网输出，允许承载输入中原有的 `LineString / MultiLineString` 混合几何；split 生成的新增 road 仍保持 `LineString`。
- 同一 SWSD 路口只生成 1 个 RCSDNode 时 `mainnodeid = null`。
- 同一 SWSD 路口生成或归组多个 RCSDNode 时，组内所有 RCSDNode 包括主节点自己 `mainnodeid = 主 RCSDNode.id`。
- `intersection_match_all.geojson` 中 `target_id` 必须唯一，一个 SWSD 语义路口只允许输出一条 relation。
- `level = grade - 1`，`is_highway = closed_con - 1`；缺失或非法时为 `-1`。
- 多 `base_id` 无法合并时写 `blocking_errors.csv/json` 并令 `summary.passed = false`。
- `kind_2 = 64` 环岛聚合只更新已有 RCSDNode 的 `mainnodeid`，不 split RCSDRoad、不新增 RCSDNode；主 RCSDNode 按距离 SWSD 环岛语义点最近、再按 id 最小选择。
- 全量运行时以 `progress_interval` 控制控制台输出频率，summary 只记录阶段级耗时和聚合体量，不记录 per-target 打点。
- `readonly_workers` 只并行直接关系、无 RCSD 普通失败、缺少 evidence 普通失败等只读分支；RCSDRoad split 与 RCSDNode grouping 当前保持串行，避免新增 id 与拓扑状态更新并发冲突。
