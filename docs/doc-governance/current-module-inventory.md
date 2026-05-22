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
| `t06_segment_fusion_precheck` | `modules/t06_segment_fusion_precheck` | Step1 SWSD 可融合 Segment 识别；Step2 RCSD Segment candidate 抽取、趋势硬筛、可替换集合与错误分析 | 本轮按新模块启动要求建立 `INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` 与 architecture 文档 | 提供模块内 callable runner 与 `scripts/t06_run_innernet_precheck.py` 内网运行包装；不新增 repo CLI、`tools/`、`Makefile` 或模块 `run.py` / `__main__.py` | 当前范围不执行 Segment 替换，不重塑路口，不修改 T01/T05 输出 |
| `t08_preprocess` | `modules/t08_preprocess` | Tool1 基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出均写回输入目录下同名文件；Tool2 Road GPKG 预处理，补充 `patch_id / kind`；Tool3 Nodes 类型聚合，补充 `kind_2 / grade_2` 并处理环岛、复杂分歧 / 合流 mainnode；输出 `EPSG:3857` GPKG | 已建立 `INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` 与 architecture 文档 | 提供模块内 callable runner 与 `scripts/t08_tool1_shp_to_gpkg.py`、`scripts/t08_tool2_road_preprocess.py`、`scripts/t08_tool3_nodes_type_aggregation.py` 内网运行脚本 | 工具形态属于项目正式组成部分；Tool3 以外的 Node 预处理待后续定义 |
| `p01_arm_build` | `modules/p01_arm_build` | P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原；输出 Arm / Movement / LogicalArmGroup / final GeoJSON / audit / review PNG / review GPKG / summary / review index | 已建立标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | A1、A2 与 P01-Final 模块内 callable runner 落地；不提供 repo CLI、`scripts/` 常驻脚本、模块 `run.py` 或 `__main__.py` | P01 目录结构与 T0X 模块一致 |

## 当前 Support Retained 模块

| 模块 ID | 路径 | 当前正式范围 | 当前文档面状态 | 当前实现状态 | 备注 |
|---|---|---|---|---|---|
| `t00_utility_toolbox` | `modules/t00_utility_toolbox` | Tool1-Tool7、Tool9、Tool10 固定脚本与共享底层能力；项目内工具集合，不直接承担业务生产逻辑 | 已具备 `architecture/*`、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | root `scripts/` 下固定工具脚本可用 | 纳入治理，但不计入 Active 业务模块集合 |

## 特殊模板资产

| 名称 | 路径 | 当前状态 | 当前定位 | 当前文档面状态 | 推荐动作 | 备注 |
|---|---|---|---|---|---|---|
| `_template` | `modules/_template` | `template-artifact` | 新模块启动模板 | 已提供标准文档契约骨架 | 后续新模块启动时复制并具体化 | 不属于业务模块生命周期 |

## 当前结论

1. 当前仓库已登记正式业务模块 `t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`、`t05_junction_surface_fusion`、`t06_segment_fusion_precheck`、`t08_preprocess` 与 P01 成果模块 `p01_arm_build`。
2. `t00_utility_toolbox` 已纳入治理，定位为工具集合模块 / 非业务生产模块。
3. `_template` 仍是后续新模块启动模板，不属于业务模块生命周期对象。
4. 后续任何新增 RCSD 模块仍应先按模板建立文档契约，再进入实现阶段。
5. 未在本盘点中登记的模块目录，不自动视为 repo 级正式治理对象。
