# RCSD_Topo_Poc - Project Brief (Global)

## 1. 项目目标

`RCSD_Topo_Poc` 当前阶段的目标是在保留工程底座治理的同时，持续维护已登记模块。当前重点包括：

- 仓库骨架
- 文档治理与 source-of-truth 分层
- RCSD-neutral 的文本回传协议
- 新模块启动模板
- 基础测试与 smoke 模式
- 已登记模块的文档契约与实现收口
- 工具集合模块、正式业务模块与模板目录的角色边界对齐
- 已登记模块的官方入口、文档契约与项目级登记保持一致

## 2. 当前范围

- 初始化 `docs/`、`modules/`、`src/`、`tests/`、`tools/`、`configs/` 等顶层骨架
- 建立项目级架构文档与仓库结构元数据
- 建立 `modules/_template/` 作为后续模块统一起点
- 保持当前输入数据组织方式与 `Highway_Topo_Poc` 一致
- 维护当前已纳入治理的 `t00_utility_toolbox`
- 维护当前已登记正式模块 `t01_data_preprocess`
- 维护当前已登记正式模块 `t02_junction_anchor`
- 维护当前已登记正式模块 `t03_virtual_junction_anchor`
- 维护当前已登记正式模块 `t04_divmerge_virtual_polygon`
- 维护当前已登记正式模块 `t05_junction_surface_fusion`
- 启动并维护当前已登记正式模块 `t06_segment_fusion_precheck`
- 启动并维护当前已登记正式模块 `t07_semantic_junction_anchor`
- 启动并维护当前已登记正式模块 `t08_preprocess`
- 维护当前已登记 P01 成果模块 `p01_arm_build`

## 3. 当前非目标

- 不无边界扩展更多未登记业务模块
- 不迁移 Highway 的算法实现、专项脚本与历史审计工件
- 不冻结 RCSD 的模块列表、指标口径与执行链路

## 4. 当前结构性结论

- 当前已登记正式业务模块：`t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t07_semantic_junction_anchor`、`t08_preprocess`
- 当前已登记 P01 成果模块：`p01_arm_build`
- 当前已纳入治理的工具集合模块：`t00_utility_toolbox`
- `t00_utility_toolbox` 的定位是工具集合模块 / 非业务生产模块
- `t01_data_preprocess` 当前已具备 official end-to-end、Step6 聚合与 freeze compare 的最小实现闭环
- `t01_data_preprocess` 双向 Segment 构建对 `kind_2 = 128` 复杂分歧 / 合流 mainnode 组采用物理 node 级建图：Step1 使用 `node.id` 而非 `mainnodeid`，并以 raw `kind / grade` 作为该轮有效规则字段；S2 中 raw `kind=8/16` 仅对复杂组内物理 node 作为分歧 / 合流端点匹配补充，不全局放宽普通节点；同时保留 `kind_2_128_*` 审计字段；该审计不扩展 `through_node_ids` 语义；Step1 / Step2 内部穿越使用 `Road.kind` 前两位道路等级做续行优先，同等级出口再用进入 / 退出夹角消歧；Step2 对复杂热点优先采用 `kind2_128_local_corridor` 局部 port 判定，避免在复杂路口内部全局追溯，兜底 trunk search budget 超限时输出 `trunk_search_budget_exceeded` 并保留预算审计信息
- `t02_junction_anchor` 当前仍为 Active 正式业务模块；模块正文如在独立重构中，应在独立轮次中维护
- `t03_virtual_junction_anchor` 当前仍为 Active 正式业务模块；正式范围按 `Step1~Step7` 业务主链表达，仅处理 `center_junction / single_sided_t_mouth`，默认正式全量 `58` case 的业务正确性基线已满足人工目视审计
- `t03_virtual_junction_anchor` 当前少量 accepted case 仍存在几何形状优化空间，但这属于后续长期迭代方向，不再构成当前正式准出阻塞项
- `t03_virtual_junction_anchor` 当前保留 `t03-rcsd-association` 官方 CLI；其业务含义对应 `Step4 + Step5` 关联阶段。T03 模块级内网批量执行与监控已经形成 repo 级脚本交付面：主脚本为 `scripts/t03_run_internal_full_input_8workers.sh` 与 `scripts/t03_watch_internal_full_input.sh`，历史 finalization shell wrapper 已退役
- `t03_virtual_junction_anchor` 当前 internal full-input 批次根目录正式成果包括 `virtual_intersection_polygons.gpkg` 与 `nodes.gpkg`
- `t03_virtual_junction_anchor` 当前 `nodes.gpkg` 仅更新代表 node 的 `is_anchor`：`accepted => yes`，`rejected / runtime_failed => fail3`；其中 `fail3` 只属于 T03 downstream output 语义，不回写输入原始 `nodes.gpkg`，也不反向修改 T02 上游契约
- `t03_watch_internal_full_input.sh` 当前采用 T02 风格的 formal-first 监控口径，默认关注 `total / completed / running / pending / success / failed`
- `t04_divmerge_virtual_polygon` 当前作为 Active 正式业务模块进入治理；正式范围已扩展到 `Step1-7`，其中 `Step1-4` 维持既有 `case-package` 输入下的 Step4 review PNG、flat mirror、index 与 summary，`Step5-7` 进入正式研发实现阶段，且默认遵循 SpecKit 的 `Product / Architecture / Development / Testing / QA` 五视角覆盖；internal full-input 通过 repo 级 shell/watch 包装 + T04 私有 runner 交付，不新增 repo 官方 CLI
- `t05_junction_surface_fusion` 当前作为 Active 正式业务模块进入治理；Phase 1 负责多源路口面融合发布，Phase 2 负责 RCSD junctionization、SWSD-RCSD relation 生产与 copy-on-write `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 输出
- `t06_segment_fusion_precheck` 当前作为 Active 正式业务模块；正式口径覆盖 Step1 SWSD 可融合 Segment 识别、Step2 buffer-based RCSDSegment 构建、兼容可替换集合和错误分析，并已扩展到 Step3：消费 replaceable Segment 输出带 `source` 的 F-RCSD Road / Node，删除被替换 SWSDRoad 及其端点 SWSDNode，引入 retained RCSDRoad / RCSDNode，并消费 Step2 passed 特殊路口组审计中的内部 RCSDRoad / RCSDNode，重建涉及的语义路口 C；Step3 提供模块内 callable runner 与独立运行脚本
- `t07_semantic_junction_anchor` 当前作为 Active 正式业务模块启动；正式范围覆盖 T02 Step1 / Step2 的语义路口级重构与独立 Step3 relation 补锚，输出代表 node 的 `has_evd / is_anchor / anchor_reason`、Step2 / Step3 `t07_rcsdintersection_anchor_surface.gpkg`、Step2 / Step3 `t07_swsd_rcsd_relation_evidence.csv/json` 与 Step3 `intersection_match_t07.geojson`，Step1 / Step2 消费 `nodes / DriveZone / RCSDIntersection`，Step3 消费 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`，不处理 Segment；T 型路口 `kind_2 = 2048` 不在 T07 建立 SWSD-RCSD 关系，交由 T03 虚拟锚定；当前提供模块内 callable runner、`scripts/t07_run_semantic_junction_anchor_innernet.sh` 与 `scripts/t07_run_step3_intersection_match_innernet.sh` 内网脚本，不新增 repo 官方 CLI
- `t08_preprocess` 当前作为 Active 正式预处理模块启动；当前覆盖 Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合、Tool4 T 型路口错误修复、Tool5 复杂路口预处理、Tool6 Nodes 类型质检、Tool7 交通限制显性化、Tool8 Laneinfo 箭头显性化与 Tool9 RCSD 数据清理，Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出写回输入目录并追加 `_tool1`，Tool2 补充 `patch_id / kind` 并输出事件 Road，Tool3 补充 `kind_2 / grade_2` 并处理环岛 mainnode，Tool4 输出完整 Nodes/audit Nodes 并修复错误 T 型路口，Tool5 构建复杂分歧 / 合流路口并可处理错误 1 对多路口，Tool6 输出 `node_error_tool6.csv / node_error_tool6.gpkg` 作为人工质检输入且不改写 Nodes/Roads，Tool7 输出 `sw_restriction_tool7.gpkg`，Tool8 输出 `sw_arrow_tool8.gpkg`，Tool9 输出 `rcsdnode_clean_tool9.gpkg / rcsdroad_clean_tool9.gpkg`，输出 GPKG 均为 `EPSG:3857`
- T06 正式启用 final `nodes.gpkg.kind_2` 的 junc-node 豁免语义：仅 `junc_nodes` 中 `kind_2 in {1,4096,8192}` 的节点可跳过 Step1 `has_evd / is_anchor` eligibility 判定，并在 Step2 中不作为 T05 relation 必检映射节点；`pair_nodes` 不适用该豁免
- T06 Step2 以 SWSD Segment 50m buffer 生成 RCSDSegment 审查输出；RCSDRoad 使用 `intersects + 阈值` 筛选，构图前以 `formway` bit7/128 识别提前右转 road，若提前右转 road 两端均与非提前右转候选 road 形成二度链接，或属于 required semantic nodes 之间的必要 corridor，则保留，否则排除；`junc_kind2_exempt_nodes` 只作为 optional allowed 审计节点；候选连通分量必须先收缩为覆盖 required semantic nodes 的 corridor 子图，pruning 阶段必须保护 required-to-required 必要通道，双向 SWSD 还必须保护 pair 两端正反向 directed corridor；额外 T05 mapped semantic nodes 必须按 seed-based pruning 判定为 `inner_nodes / out_nodes`，处于 required corridor 内部的 mapped semantic node 可作为 `inner_nodes` 保留审计，非 inner 且仍进入 retained graph 时必须拒绝；`swsd_directionality=single` 时必须由 SWSDRoad `snodeid / enodeid / direction` 推导 pair source/target，并按该方向构建 RCSD 有向 corridor，禁止用 `pair_nodes` 顺序、`segmentid A_B` 顺序或反向可达兜底；`swsd_directionality=dual` 时 retained graph 必须 pair 两端双向可达；final `nodes.gpkg.kind_2=64/128` 的环岛 / 复杂路口启用特殊组门控：按 `pair_nodes + junc_nodes` 统计关联 Segment，组内未全部可替换时，组内所有原本可替换 Segment 均移出 replaceable，并输出 `t06_special_junction_group_audit.*` 审计 RCSD relation、组内 RCSDNode / 内部 RCSDRoad 与门控结果；Step2 不再执行旧 pair-to-pair BFS 路径搜索、主轴 / 长度趋势或唯一性筛选
- T06 Step2 RCSD 建图使用 `rcsdnode_out.gpkg` 的 `id / mainnodeid / subnodeid` 归一化到 canonical RCSD semantic node id；全局 RCSD 语义路口组按有效 `mainnodeid` 聚合，组内所有 node 关联 road 均视为该语义路口的进入 / 退出道路；relation required nodes 与 RCSDRoad `snodeid / enodeid` 按同一 canonical key 判定连通，未映射到当前 Segment 的全局 RCSD 语义路口若进入候选图，必须参与 seed pruning，必要通道内保留为 `inner_nodes`，旁支归入 `out_nodes` 裁剪
- `p01_arm_build` 当前作为 Active P01 成果模块进入治理；正式范围覆盖 P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 规则级还原，输出 Trace / ThroughDecisionAudit / IssueReport / LogicalArmGroup / RawArmAlignment / ArmBuildFeedback / corrected_final_arms / arm_source_profiles / source_arm_pass_rules / final_generation_decisions / frcsd_road_next_road.geojson / final audit / review PNG / review GPKG / summary / review index，不提供 repo 官方 CLI 或 `scripts/` 常驻命令
- `_template` 仅是模板目录，不属于模块生命周期盘点对象
- 模块根目录不放 `SKILL.md`
- 标准 Skill 统一放 repo root `.agents/skills/`

## 5. 初始数据组织兼容约束

当前阶段，patch 输入目录先沿用以下兼容布局：

```text
<PatchID>/
  PointCloud/
  Vector/
  Tiles/
  Traj/
```

这只是初始化阶段的数据组织兼容约束，不代表 RCSD 业务标准已经冻结。
