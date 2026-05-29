# 当前模块盘点

## 范围

- 盘点日期：2026-04-18
- 目的：说明当前仓库正式业务模块现状、模块文档面状态与模板资产状态

## 当前正式生命周期结论

- `Active`：
  - `t01_data_preprocess`
  - `t02_junction_anchor`
  - `t03_virtual_junction_anchor`
  - `t04_divmerge_virtual_polygon`
  - `t05_junction_surface_fusion`
  - `t06_segment_fusion_precheck`
  - `t07_semantic_junction_anchor`
  - `t08_preprocess`
  - `p01_arm_build`
- `Historical Reference`：无
- `Retired`：无
- `Support Retained`：
  - `t00_utility_toolbox`

## 当前 Active 模块

| 模块 ID | 路径 | 当前正式范围 | 当前文档面状态 | 当前实现状态 | 备注 |
|---|---|---|---|---|---|
| `t01_data_preprocess` | `modules/t01_data_preprocess` | working bootstrap + roundabout preprocessing + Step1-Step6 双向 Segment 构建 official end-to-end；active freeze compare 为 `t01_skill_active_eight_sample_suite` | 已补齐标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | `t01-run-skill-v1` 与 `t01-compare-freeze` 已正式可用；Step6 已纳入 official end-to-end | 当前正式范围聚焦非封闭式双向道路；单向 Segment 与更大批处理扩展未纳入当前正式范围 |
| `t02_junction_anchor` | `modules/t02_junction_anchor` | stage1 `DriveZone / has_evd gate` + stage2 `anchor recognition / anchor existence` + stage3 `virtual intersection anchoring` baseline；文本证据包与 `t02-fix-node-error-2` 为独立支撑入口 | 已补齐标准 architecture 文档组、`06-accepted-baseline.md`、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | stage1 / stage2 / stage3 已实现；`t02-virtual-intersection-poc` 已支持 `case-package` 唯一正式验收基线与 `full-input` 完整数据 `fixture / dev-only / regression` 模式 | T01 是其上游事实源之一；模块正文可在独立重构轮次中维护，本盘点只保留项目级登记与入口索引 |
| `t03_virtual_junction_anchor` | `modules/t03_virtual_junction_anchor` | `Step1~Step7` 正式业务主链；Anchor61 `case-package` / internal full-input 局部上下文输入、合法空间冻结、RCSD 关联、foreign / excluded 负向约束、受约束几何、最终发布、平铺 PNG、索引、summary、batch aggregate polygons、downstream `nodes.gpkg` 与 terminal case records | 已补齐标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md`，并新增业务步骤到实现阶段映射文档 | `t03-step3-legal-space` 作为冻结前置入口保留，`t03-rcsd-association` 为当前 RCSD 关联 CLI；`Association / Finalization` 作为实现/输出命名保留，不再作为正式需求主结构 | T03 当前已完成正式继承与重构收口；当前剩余 `707913 / 954218 / 520394575` 已人工确认属于输入数据错误 |
| `t04_divmerge_virtual_polygon` | `modules/t04_divmerge_virtual_polygon` | `Step1-4` doc-first formalization；case-package 输入、admission/local-context/topology/event-unit interpretation、Step4 overview/event-unit review、flat mirror、index、summary | 已补齐标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | T04 Step1-4 runner 已模块化实现，优先复用 T02 Stage4 内核与 T03 review closeout 组织，不新增 repo 官方 CLI | 当前仅正式覆盖 Step1-4；Step5-7 仍留待后续轮次承接 |
| `t05_junction_surface_fusion` | `modules/t05_junction_surface_fusion` | Phase 1 多源路口面融合发布；Phase 2 RCSD junctionization、SWSD-RCSD relation 生产与 copy-on-write `rcsdroad_out.gpkg / rcsdnode_out.gpkg` 输出 | 已具备 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | Phase 1 / Phase 2 模块内 callable runner 已实现；T05 内网 helper / experiment 脚本已登记为 repo 级脚本入口 | 当前补齐项目级登记，T06 Step2 正式消费 Phase 2 relation 与 copy-on-write RCSD 网络成果 |
| `t06_segment_fusion_precheck` | `modules/t06_segment_fusion_precheck` | Step1 SWSD 可融合 Segment 识别；Step2 buffer-based RCSDSegment 审查输出与可替换集合；Step3 基于 replaceable Segment 输出 F-RCSD Road / Node 并重建涉及的语义路口关系 | Step1 / Step2 文档与实现已建立；Step3 callable runner 与独立脚本已落地 | 提供模块内 callable runner、`scripts/t06_run_innernet_precheck.py` Step1+Step2 包装与 `scripts/t06_run_step3_segment_replacement.py` Step3 独立脚本；不新增 repo CLI、`tools/`、`Makefile` 或模块 `run.py` / `__main__.py` | Step3 采用 copy-on-write，不修改 T01/T05/Step2 输入；现有 Step1+Step2 内网脚本默认行为不变 |
| `t07_semantic_junction_anchor` | `modules/t07_semantic_junction_anchor` | T02 Step1 / Step2 的语义路口级重构与独立 Step3 relation 补锚；Step1 / Step2 消费 `nodes / DriveZone / RCSDIntersection`，Step3 消费 Step2 后 `nodes`、T05 `intersection_match_all.geojson` 与输入 `RCSDNode`，输出代表 node 的 `has_evd / is_anchor / anchor_reason`、Step2 `t07_rcsdintersection_anchor_surface.gpkg`、Step2 / Step3 `t07_swsd_rcsd_relation_evidence.json` 与 Step3 `intersection_match_tool7.geojson`，不处理 Segment | 已建立 `INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` 与 architecture 文档 | 提供模块内 callable runner、`scripts/t07_run_semantic_junction_anchor_innernet.sh` Step1+Step2 包装与 `scripts/t07_run_step3_intersection_match_innernet.sh` Step3 独立脚本；不新增 repo CLI、`tools/`、`Makefile` 或模块 `run.py` / `__main__.py` | Step1 仅处理代表 node `kind_2 in {4,8,16,64,128,2048}`；Step3 仅处理 `kind_2 in {4,8,16,2048}`、`has_evd=yes`、`is_anchor=no` 且 T05 relation 成功、RCSD `base_id` 存在的候选 |
| `t08_preprocess` | `modules/t08_preprocess` | Tool1 基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出写回输入目录并追加 `_tool1`；Tool2 Road GPKG 预处理，补充 `patch_id / kind`，删除 `kind` 具有 `17` 主辅路出入口属性的 Road 到事件输出，并输出阶段性能；Tool3 Nodes 类型聚合，补充 `kind_2 / grade_2` 并处理环岛 mainnode；Tool4 路口类型修复，输出完整 Nodes、可选 Roads 与 audit Nodes，并可消费 Tool6 人工确认成果；Tool5 复杂路口预处理，构建复杂分歧 / 合流路口并可处理错误 1 对多路口；Tool6 Nodes 类型质检，输出 `node_error_tool6.csv / node_error_tool6.gpkg` 作为人工质检输入；Tool7 交通限制显性化，输出 `sw_restriction_tool7.gpkg`；输出 `EPSG:3857` GPKG，成果输出文件名以 `_toolX` 结尾 | 已建立 `INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` 与 architecture 文档 | 提供模块内 callable runner 与 `scripts/t08_tool1_vector_convert.py`、`scripts/t08_tool2_road_preprocess.py`、`scripts/t08_tool3_nodes_type_aggregation.py`、`scripts/t08_tool4_junction_type_repair.py`、`scripts/t08_tool5_complex_junction_preprocess.py`、`scripts/t08_tool6_nodes_type_qc.py`、`scripts/t08_tool7_traffic_restriction.py` 内网运行脚本 | 工具形态属于项目正式组成部分；Tool4 按契约修复路口类型并可消费 Tool6 人工确认结果；Tool6 不改写输入 Nodes/Roads，CSV 最后一列 `是否修复` 默认 `1`；Tool7 不改写输入 C 表 / SW Node / SW Road |
| `p01_arm_build` | `modules/p01_arm_build` | P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原；输出 Arm / Movement / LogicalArmGroup / final GeoJSON / audit / review PNG / review GPKG / summary / review index | 已建立标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | A1、A2 与 P01-Final 模块内 callable runner 落地；不提供 repo CLI、`scripts/` 常驻脚本、模块 `run.py` 或 `__main__.py` | P01 目录结构与 T0X 模块一致 |

## 当前 Support Retained 模块

| 模块 ID | 路径 | 当前正式范围 | 当前文档面状态 | 当前实现状态 | 备注 |
|---|---|---|---|---|---|
| `t00_utility_toolbox` | `modules/t00_utility_toolbox` | Tool1-Tool7、Tool9、Tool10、Tool11 固定脚本与共享底层能力；项目内工具集合，不直接承担业务生产逻辑 | 已具备 `architecture/*`、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | root `scripts/` 下固定工具脚本可用 | 纳入治理，但不计入 Active 业务模块集合 |

## 特殊模板资产

| 名称 | 路径 | 当前状态 | 当前定位 | 当前文档面状态 | 推荐动作 | 备注 |
|---|---|---|---|---|---|---|
| `_template` | `modules/_template` | `template-artifact` | 新模块启动模板 | 已提供标准文档契约骨架 | 后续新模块启动时复制并具体化 | 不属于业务模块生命周期 |

## 当前结论

1. 当前仓库已登记正式业务模块 `t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t07_semantic_junction_anchor`、`t08_preprocess` 与 P01 成果模块 `p01_arm_build`。
2. `t00_utility_toolbox` 已纳入治理，定位为工具集合模块 / 非业务生产模块。
3. `_template` 仍是后续新模块启动模板，不属于业务模块生命周期对象。
4. 后续任何新增 RCSD 模块仍应先按模板建立文档契约，再进入实现阶段。
5. 未在本盘点中登记的模块目录，不自动视为 repo 级正式治理对象。
