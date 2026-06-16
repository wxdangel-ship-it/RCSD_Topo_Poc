# 10 Quality Requirements

## Phase 1 正确性

- CRS 与坐标变换必须统一到 `EPSG:3857`。
- 不得用几何相交单独决定不同 `mainnodeid` 的业务合并。
- T03/T04 非 accepted 输入不得进入主发布层。
- 未锚定到 SWSD 语义路口、无法解析 `mainnodeid` 的输入面不得进入主发布层。
- 主图层只保留 7 字段 schema。
- `surface_sources` 必须只表达最终几何实际使用的来源。
- `is_multi_source_merged = 1` 时必须存在多来源 union；primary 替代不算多源合并。
- 主图层 `mainnodeid` 必须非空，`surface_id` 必须为 `JAS:{mainnodeid}`。
- `kind_2` 与 `junction_type` 映射冲突必须 audit，不得静默修正。

## GIS / 拓扑检查项

- CRS 与坐标变换正确性：输入读取时统一 CRS，输出 CRS 固定 `EPSG:3857`。
- 拓扑一致性：只允许最小合法化，不允许 silent fix 改变业务边界。
- 几何语义可解释性：融合只按 `mainnodeid` 与来源 formal 状态推进，几何只做辅助判断。
- 审计可追溯性：summary 记录输入、输出、计数、冲突、缺失字段与 consistency。
- 性能可验证性：当前 Phase 1 以线性分组和局部 union 为主，后续真实 full-input 可通过 summary 计数与测试样例扩展性能门槛。

## 输出一致性

`summary.json.consistency` 必须至少覆盖：

- `junction_anchor_surface.gpkg` feature count 与 `published_surface_count` 一致。
- 每个 feature 有非空 `surface_id`、`mainnodeid` 与 `junction_type`。
- `surface_sources` 在允许值域内。
- `is_multi_source_merged` 为 `0 / 1`。
- 多源标志与 `surface_sources` 中的 `|` 一致。
- `mainnodeid` 与 `surface_id` 规则一致。
- `kind_2` 与 `junction_type` 映射一致。
- 输出 CRS 为 `EPSG:3857`。
- 不生成 `intersection_match_all.geojson`。

## 回归要求

测试至少覆盖：

- 主图层 schema 与 CRS。
- T02_INPUT、T03 accepted、T04 accepted 单源发布。
- T03/T04 rejected 或 non-accepted 过滤。
- 未锚定到 SWSD 语义路口的来源面被 skipped，不进入主图层。
- T02+T03、T02+T04 多源合并。
- T03+T04 同 `mainnodeid` 冲突 audit。
- 不同 `mainnodeid` 几何相交不自动合并。
- `kind_2` 到 `junction_type` 的映射。
- `patch_id` 来源继承、nodes 反查与冲突审计。
- 不生成关系表、RCSD split 输出或 RCSDNode insert 输出。
- runner 不修改输入 nodes 或上游 surface。

## Phase 2 正确性

- `intersection_match_all.geojson` 字段固定为 `target_id / base_id / status / level / is_highway`。
- `intersection_match_all.geojson` 输出 CRS 必须为 CRS84 / WGS84 lon-lat。
- 失败关系必须 `status = 1` 且 `base_id = 0`。
- 成功关系必须 `status = 0` 且 `base_id != 0`。
- 不得把普通 RCSDRoad id 写入 `base_id`。
- RCSDRoad / RCSDNode 输入只读，所有拓扑变化通过 copy-on-write 输出表达。
- 被 split 的原始 RCSDRoad 不进入 active `rcsdroad_out.gpkg`。
- 新增 RCSDRoad / RCSDNode id 必须全局唯一且稳定递增。
- T03-A 多 RCSDNode、T04 complex 多 RCSDNode，以及 T04 `road_surface_fork` partial handoff 中 `base_id_candidate` 与 `semantic_required_rcsd_node_ids` 分离的场景，必须先归组再建关系，不打断 road。
- T03 road-only 与 T04 fallback road-only 才能进入 RCSDRoad split。
- T07 历史路口锚定 relation evidence 只作为已有 RCSD 语义路口 direct relation，不触发 RCSDRoad split 或 RCSDNode insert。
- T07 历史锚定 relation-only target 没有 Phase 1 surface 时，仍必须进入 `intersection_match_all.geojson`。
- Phase 2 入口必须统一 canonicalize SWSD 语义路口主键，覆盖 evidence `target_id`、surface `mainnodeid`、nodes `id/mainnodeid`、known target 索引和最终 relation/audit 输出；整数 ID 的字符串 / 浮点字符串表达差异必须归一，例如 `622700016.0` 输出为 `622700016`。
- `kind_2 = 64` 环岛场景必须验证所有 SWSD 子 node 均被路口面覆盖，RCSD 候选语义路口全组 node 均被环岛面覆盖，并且候选语义路口之间通过 `RCSDRoad.roadtype = 8` 连通。
- `kind_2 = 64` 环岛场景只能归组已有 RCSDNode，不得 split RCSDRoad 或新增 RCSDNode。
- Road-only 投影点靠近 RCSDRoad 端点时必须复用已有端点 RCSDNode 或审计失败，不得生成极短 road 段。
- `target_id` 必须唯一，一个 SWSD 语义路口只输出一条 relation。
- 成功关系必须通过 cardinality QC：不得存在 `1:N` 的 `target_id -> base_id` 挂接或重复 success target；允许存在 `N:1` 的 `base_id <- target_id`，但必须输出审计。
- Cardinality QC 错误必须输出 `relation_cardinality_errors.csv/json`，并给出 `introduced_by_module / source_modules / source_case_ids / scenes / reasons` 归因信息；`1:N` 与重复 target 属于阻断错误，相关 relation 必须从 `intersection_match_all.geojson` 主表剔除。`N:1` 属于非阻断审计，relation 保留给 T06 消费。
- `level = grade - 1`，缺失、为空或非法时为 `-1`。
- `is_highway = closed_con - 1`，缺失、为空或非法时为 `-1`。
- Phase 2 不得改写 final SWSD nodes，不得输出 SWSD node copy-on-write 标记层；无 RCSD 场景通过失败 relation 和 audit 表达。
- 多个 `base_id` 无法合并时必须 blocking error，不得输出多条 relation，也不得写成普通失败关系。
- T03 handoff 补齐只能读取 T03 已输出的 relation evidence 与 case 级 `step6_status/step6_audit` 字段，不得反推或新增 T03 业务语义。
- T03 handoff 补齐是旧 T03 产物兼容能力；当前 T03 evidence 字段完整时，内网实验脚本默认 `--t03-backfill-mode never` 并直接消费原始 T03 evidence。补齐必须输出独立 backfilled evidence、audit 与 summary，不覆盖原始 T03 输出。

## Phase 2 GIS / 拓扑检查项

- CRS 与坐标变换正确性：处理过程使用 `EPSG:3857`，最终关系 GeoJSON 转为 CRS84。
- 拓扑一致性：split 点过近或靠近端点必须跳过或失败并 audit，不允许 silent fix。
- 几何语义可解释性：投影来源必须来自 relation evidence 的 fact reference 或 SWSD semantic point。
- 审计可追溯性：junctionization audit 记录 target、surface、source evidence、原 road/node、新 road/node、动作、失败原因。
- 性能可验证性：summary 记录 feature count、split count、generated/grouped node count、预分类 plan、只读/可变 target 计数、阶段级耗时与 consistency。
- 控制台进度输出必须稀疏，按 `progress_interval` 汇报 target 进度，不输出 per-target 明细。
- 输出阶段必须记录逐文件耗时与文件大小，`progress=True` 时打印逐文件 `writing/done`，便于定位 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 等大文件写出瓶颈。
- 只读关系构建允许通过 `readonly_workers` 并行；涉及 RCSDRoad split、RCSDNode grouping、新增 id 分配的分支当前保持串行。

## Phase 2 一致性

`summary.json.consistency` 必须至少覆盖：

- 所有 `status = 1` 的 `base_id` 均为 `0`。
- 所有 `status = 0` 的 `base_id` 均非 `0`。
- `target_id` 无重复。
- 新增 RCSDRoad / RCSDNode id 唯一。
- 被 split 原始 RCSDRoad 不在 active 输出。
- 新 RCSDRoad 的 `snodeid / enodeid` 均存在于 `rcsdnode_out.gpkg`。
- 新增和归组 RCSDNode 均存在于 `rcsdnode_out.gpkg`。
- 输出 CRS 正确。
- 输入文件未被原地修改。
- 如果存在 `multiple_base_id_unmergeable`，`summary.passed` 必须为 `false`。
- 如果存在阻断型 `relation_cardinality_errors`，`summary.passed` 必须为 `false`；仅存在 `many_target_to_one_base` 非阻断审计时，`summary.passed` 可为 `true`。
- T03 handoff 补齐后的 evidence 能驱动 Phase 2 中 T03-A RCSDNode grouping 与 T03 road-only RCSDRoad split。
- `kind_2 = 64` 环岛能基于覆盖面和 `roadtype = 8` 连通性归组多个 RCSD 语义路口，并拒绝非 `roadtype = 8` 的伪连通。
