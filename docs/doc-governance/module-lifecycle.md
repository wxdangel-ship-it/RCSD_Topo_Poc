# 模块生命周期

## 1. 文档目的

本文档用于定义本仓库业务模块的生命周期状态，明确哪些模块属于当前正式治理对象、哪些已经退役、哪些只保留为历史参考。

`modules/_template/` 不是业务模块，不纳入本生命周期表。

## 2. 状态定义

### Active

- 当前正式治理与迭代对象

### Retired

- 不再作为当前活跃模块治理对象
- 保留历史实现与文档

### Historical Reference

- 不再作为当前正式模块
- 保留为经验、历史证据和择优提炼来源

### Support Retained

- 仓库保留的支撑 / 测试模块
- 当前不属于活跃模块集合

## 3. 当前模块状态表

### Active

| 模块 ID | 路径 | 当前正式范围 | 当前状态 |
|---|---|---|---|
| `t01_data_preprocess` | `modules/t01_data_preprocess` | working bootstrap + roundabout preprocessing + Step1-Step6 双向 Segment 构建 official end-to-end；active freeze compare 为 `t01_skill_active_eight_sample_suite` | `official end-to-end / freeze-compare baseline active` |
| `t02_junction_anchor` | `modules/t02_junction_anchor` | `DriveZone / has_evd gate` + `anchor recognition / anchor existence` + `virtual intersection anchoring` baseline；文本证据包与 `t02-fix-node-error-2` 为独立支撑入口 | `stage1/stage2/stage3 baseline active / independent refactor may continue outside this governance round` |
| `t03_virtual_junction_anchor` | `modules/t03_virtual_junction_anchor` | `Step1~Step7` 正式业务主链；仅处理 `center_junction / single_sided_t_mouth`，消费 Anchor61 `case-package` 或 internal full-input 局部上下文，输出 RCSD 关联/负向约束中间结果、最终虚拟路口面、平铺 PNG、索引、summary、batch aggregate polygons、downstream `nodes.gpkg` 与 terminal case records | `step1-step7 formal chain active / 58-case correctness baseline accepted / association-finalization implementation names canonical / no new public finalization cli` |
| `t04_divmerge_virtual_polygon` | `modules/t04_divmerge_virtual_polygon` | `Step1-7` doc-first formalization；消费包含 `divstripzone.gpkg` 的 case-package 或 internal full-input，输出 admission/local-context/topology/event-unit interpretation、Step5 支撑域约束、Step6 最终组装结果，以及 Step7 `accepted/rejected` 发布层与审计汇总 | `step1-step4 stable / step5-step7 formal implementation active / internal full-input script wrapper active / no public cli` |
| `t05_junction_surface_fusion` | `modules/t05_junction_surface_fusion` | Phase 1 多源路口面融合发布；Phase 2 消费 Phase 1 成果、final nodes、原始 RCSDRoad/RCSDNode 与 relation evidence，输出 `intersection_match_all.geojson`、copy-on-write `rcsdroad_out.gpkg / rcsdnode_out.gpkg`、junctionization audit 与 summary | `phase1-phase2 active / callable module runners / innernet helper scripts registered / no public cli` |
| `t06_segment_fusion_precheck` | `modules/t06_segment_fusion_precheck` | T06 Step1 识别可参与融合的 SWSD Segment 单元；Step2 基于 T05 Phase 2 relation 与 copy-on-write RCSD 网络输出 buffer-based RCSDSegment 审查成果与 replaceable 集合；Step3 消费 replaceable Segment，copy-on-write 输出 F-RCSD Road / Node 并重建涉及的语义路口关系 | `step1-step2 implemented / step3 callable runner + independent script implemented / no public cli` |
| `t07_semantic_junction_anchor` | `modules/t07_semantic_junction_anchor` | T07 Step1 / Step2 / Step3：T02 Step1 / Step2 的语义路口级重构与独立 Step3 relation 补锚；Step1 / Step2 消费 `nodes / DriveZone / RCSDIntersection`，Step3 消费 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`，输出代表 node 的 `has_evd / is_anchor / anchor_reason`、Step2 / Step3 `t07_rcsdintersection_anchor_surface.gpkg`、Step2 / Step3 `t07_swsd_rcsd_relation_evidence.csv/json` 与 Step3 `intersection_match_tool7.geojson`，不处理 Segment | `step1-step2-step3 active / callable module runners / innernet scripts registered / no public cli` |
| `t08_preprocess` | `modules/t08_preprocess` | T08 正式预处理模块；当前覆盖 Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合、Tool4 路口类型修复、Tool5 复杂路口预处理、Tool6 Nodes 类型质检、Tool7 交通限制显性化、Tool8 Laneinfo 箭头显性化与 Tool9 RCSD 数据清理，T08 成果输出文件名统一以 `_toolX` 结尾；Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出写回输入目录并追加 `_tool1`；Tool2 补充 `patch_id / kind` 并删除 `kind` 具有 `17` 主辅路出入口属性的 Road 到事件输出；Tool3 补充 `kind_2 / grade_2`；Tool4 输出完整 Nodes/可选 Roads/audit Nodes，修复错误 T 型、一入一出分合流并可消费 Tool6 人工确认成果；Tool5 构建复杂分歧 / 合流路口并可处理错误 1 对多路口；Tool6 输出 `node_error_tool6.csv / node_error_tool6.gpkg` 作为人工质检输入，不改写输入 Nodes/Roads；Tool7 输出 `sw_restriction_tool7.gpkg`；Tool8 输出 `sw_arrow_tool8.gpkg`；Tool9 输出 `rcsdnode_clean_tool9.gpkg / rcsdroad_clean_tool9.gpkg`，均输出 `EPSG:3857` GPKG | `tool1-tool2-tool3-tool4-tool5-tool6-tool7-tool8-tool9 active / innernet scripts registered / tool4 consumes optional tool6 QC / tool6 QC only` |
| `p01_arm_build` | `modules/p01_arm_build` | P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原；A1 构建三源 Arm、特殊转向、ArmMovement、corrected trunk，A2 构建 LogicalArmGroup / RawArmAlignment / ArmBuildFeedback，P01-Final 输出 `frcsd_road_next_road.geojson`、source map、source policy、audit 与 issue | `p01-v1-a1-a2-final / callable module runners only / no public cli` |

### Retired

| 模块 ID | 路径 | 当前正式范围 | 当前状态 |
|---|---|---|---|
当前无。

### Historical Reference

当前无。

### Support Retained

| 模块 ID | 路径 | 当前正式范围 | 当前状态 |
|---|---|---|---|
| `t00_utility_toolbox` | `modules/t00_utility_toolbox` | Tool1-Tool7、Tool9、Tool10、Tool11 固定脚本与共享底层能力；项目内工具集合，不直接承担业务生产逻辑 | `governed tooling module / non-business production` |

说明：

- 未在本表登记的模块目录，不自动视为当前正式治理对象。
- `t01_data_preprocess` 当前已具备 official end-to-end、Step6 聚合与 active freeze compare 的最小实现闭环。
- `t02_junction_anchor` 当前已具备 stage1、stage2 与 stage3 的最小实现闭环；其模块正文若在独立重构中，应在独立轮次维护。
- `t03_virtual_junction_anchor` 当前作为 T03 新模块进入 Active，正式范围按 `Step1~Step7` 业务主链表达，历史 `Association / Finalization` 命名只保留在实现映射、兼容输出与 closeout 追溯中。
- `t04_divmerge_virtual_polygon` 当前作为 T04 新模块进入 Active，正式范围已扩展到 `Step1-7`；其中 `Step1-4` 维持稳定上游中间结果与 Step4 审计工件，`Step5-7` 进入正式研发实现阶段，并默认按 SpecKit 的 `Product / Architecture / Development / Testing / QA` 五视角推进；internal full-input 通过 repo 级 shell/watch 包装 + T04 私有 runner 交付，不新增 repo 官方 CLI。
- `t05_junction_surface_fusion` 当前作为 T05 正式模块进入 Active，Phase 1 发布统一路口面，Phase 2 发布 SWSD-RCSD relation 与 copy-on-write RCSD 网络成果；Phase 2 成功 relation 的 `base_id` 必须是 RCSD 语义路口主 node id。
- `t06_segment_fusion_precheck` 当前作为 T06 正式模块启动，范围已从 Segment 替换前置检查扩展到 Step3 融合输出：Step3 只消费 Step2 replaceable 成果，删除被替换 SWSDRoad 及其端点 SWSDNode，引入 retained RCSDRoad / RCSDNode，输出带 `source` 的 F-RCSD Road / Node，并重建涉及的语义路口 C；当前不新增 repo 官方 CLI，Step1+Step2 内网执行通过 `scripts/t06_run_innernet_precheck.py` 包装，Step3 通过独立脚本 `scripts/t06_run_step3_segment_replacement.py` 消费 Step2 成果。
- `t07_semantic_junction_anchor` 当前作为 T07 正式模块启动，范围覆盖语义路口级 `has_evd / is_anchor / anchor_reason`、T07 版 T02 surface/evidence handoff 与独立 Step3 relation 补锚，不处理 Segment；当前不新增 repo 官方 CLI，Step1 / Step2 内网执行通过 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 包装模块内 runner，Step3 通过 `scripts/t07_run_step3_intersection_match_innernet.sh` 独立执行。
- `t08_preprocess` 当前作为 T08 正式预处理模块启动；工具形态属于项目正式组成部分，当前内网执行通过 `scripts/t08_tool1_vector_convert.py`、`scripts/t08_tool2_road_preprocess.py`、`scripts/t08_tool3_nodes_type_aggregation.py`、`scripts/t08_tool4_junction_type_repair.py`、`scripts/t08_tool5_complex_junction_preprocess.py`、`scripts/t08_tool6_nodes_type_qc.py`、`scripts/t08_tool7_traffic_restriction.py`、`scripts/t08_tool8_lane_arrow.py` 与 `scripts/t08_tool9_rcsd_cleaning.py`；T08 成果输出文件名统一以 `_toolX` 结尾，Tool4 按契约修复路口类型并可消费 Tool6 人工确认成果，Tool6 只输出人工质检候选，不自动修复，Tool7 输出显性交通限制，Tool8 输出显性 Laneinfo arrow，Tool9 输出清理后的 RCSDNode / RCSDRoad。
- `p01_arm_build` 当前作为 P01 成果模块进入 Active；目录结构与 T0X 模块一致，覆盖 P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原，不提供 repo 官方 CLI 或常驻脚本入口。
- stage3 `virtual intersection anchoring` 纳入当前 baseline，不等于最终唯一锚定决策闭环或正式产线闭环。
- 单 `mainnodeid` 文本证据包当前作为 stage3 复核与外部复现支撑入口保留。
- `t02-fix-node-error-2` 当前作为 stage2 之后的独立离线修复工具保留，不纳入主阶段链。
- `t00_utility_toolbox` 已纳入治理，但不属于业务生产模块，不应误记为 Active 业务模块。

## 4. 模板目录说明

- `modules/_template/` 是模块启动模板
- 它不是 `Active`、`Retired`、`Historical Reference` 或 `Support Retained` 中的任何一种
- 不能把模板目录误当成已经存在的业务模块
