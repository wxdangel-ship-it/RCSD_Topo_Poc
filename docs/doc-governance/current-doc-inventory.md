# 当前文档盘点

## 范围

- 盘点日期：2026-04-19
- 目的：说明当前主阅读路径、标准文档位置、正式模块文档面与模板入口

## 当前主入口文档

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `AGENTS.md` | repo 级 durable guidance 入口 | `durable_guidance` | 只保留仓库级稳定规则 |
| `SPEC.md` | 项目级总规格入口 | `source_of_truth` | 项目级最高优先级规格 |
| `.specify/memory/constitution.md` | 宪章 | `constitution` | 约束长期文档与流程原则 |
| `docs/PROJECT_BRIEF.md` | 项目摘要入口 | `source_of_truth` | 提供项目级稳定摘要，不替代 architecture 细项 |
| `docs/ARTIFACT_PROTOCOL.md` | 文本回传协议 | `source_of_truth` | 约束文本回传形态 |
| `docs/architecture/*.md` | 项目级长期架构说明 | `source_of_truth` | 当前项目级长期真相主表面 |
| `docs/repository-metadata/README.md` | 仓库结构入口 | `durable_guidance` | 说明从哪里理解当前仓库结构 |
| `docs/doc-governance/README.md` | 治理主入口 | `durable_guidance` | 告诉维护者当前从哪里开始看治理文档 |
| `docs/doc-governance/module-lifecycle.md` | 模块生命周期真相 | `source_of_truth` | 定义业务模块状态类别 |
| `docs/doc-governance/current-module-inventory.md` | 当前模块盘点 | `inventory` | 说明当前登记模块、模板资产与状态快照 |
| `docs/doc-governance/current-doc-inventory.md` | 当前文档盘点 | `inventory` | 解释当前文档分层与位置 |
| `docs/doc-governance/module-doc-status.csv` | 模块文档状态总表 | `status_snapshot` | 记录模板资产与正式模块文档状态 |

## 当前纳入治理模块文档面

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `modules/t00_utility_toolbox/architecture/*` | T00 模块长期架构真相 | `source_of_truth` | T00 工具集合模块的长期文档主表面 |
| `modules/t00_utility_toolbox/INTERFACE_CONTRACT.md` | T00 稳定契约面 | `source_of_truth` | 固化 Tool1-Tool7、Tool9、Tool10、Tool11 的稳定输入、输出、覆盖、异常与摘要语义 |
| `modules/t00_utility_toolbox/README.md` | T00 操作者入口 | `operator_guide` | 说明固定脚本入口、工具边界和常见运行方式 |
| `modules/t00_utility_toolbox/AGENTS.md` | T00 durable guidance | `durable_guidance` | 只保留工具集合模块边界与协作规则 |
| `modules/t00_utility_toolbox/history/*` | T00 模块级历史材料 | `history` | 记录工具模块演进与补充说明 |
| `specs/t00-utility-toolbox/*` | T00 变更工件 | `active_change_artifact` | 记录工具模块治理变更，不替代长期模块真相 |
| `modules/t01_data_preprocess/architecture/*` | T01 模块长期架构真相 | `source_of_truth` | T01 正式模块的长期文档主表面 |
| `modules/t01_data_preprocess/INTERFACE_CONTRACT.md` | T01 稳定契约面 | `source_of_truth` | 固化 working bootstrap、Step1-Step6、freeze compare 与 debug/no-debug 契约 |
| `modules/t01_data_preprocess/README.md` | T01 操作者入口 | `operator_guide` | 说明 official end-to-end、freeze compare、分步运行方式与关键产物 |
| `modules/t01_data_preprocess/AGENTS.md` | T01 durable guidance | `durable_guidance` | 只保留模块级执行边界与协作规则 |
| `modules/t01_data_preprocess/history/*` | T01 模块级历史材料 | `history` | 记录 baseline 演进、结构拆分与后续修正轨迹 |
| `specs/t01-data-preprocess/*` | T01 变更工件 | `active_change_artifact` | 记录当前 active change 的计划与任务，不替代长期模块真相 |
| `modules/t02_junction_anchor/architecture/*` | T02 模块长期架构真相 | `source_of_truth` | T02 正式模块的长期文档主表面 |
| `modules/t02_junction_anchor/INTERFACE_CONTRACT.md` | T02 稳定契约面 | `source_of_truth` | 固化 stage1、stage2、stage3 baseline 与文本支撑入口的输入、输出、入口、参数类别与验收标准 |
| `modules/t02_junction_anchor/README.md` | T02 操作者入口 | `operator_guide` | 说明 stage1 / stage2 / stage3 官方运行入口、文本支撑入口、常见运行方式与关键产物 |
| `modules/t02_junction_anchor/AGENTS.md` | T02 durable guidance | `durable_guidance` | 只保留模块级执行边界与协作规则 |
| `modules/t02_junction_anchor/history/*` | T02 模块级历史材料 | `history` | 记录 bootstrap 与后续演进轨迹 |
| `specs/t02-junction-anchor/*`、`specs/t02-virtual-intersection-batch-poc/*` | T02 变更工件 | `active_change_artifact` | 记录历次与当前 active change 的变更规格，不替代长期模块真相 |
| `modules/t03_virtual_junction_anchor/architecture/*` | T03 模块长期架构真相 | `source_of_truth` | T03 正式模块的长期文档主表面；当前正式范围按 `Step1~Step7` 业务主链表达，并通过 `10-business-steps-vs-implementation-stages.md` 说明 `Association / Finalization` 实现阶段映射 |
| `modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md` | T03 稳定契约面 | `source_of_truth` | 固化 Anchor61 `case-package` / internal full-input 输入、`Step1~Step7` 正式业务主链、formal/review/internal 分层、batch aggregate polygons、updated nodes layer、anchor update audit、terminal case records 与 `association_* / step7_*` 正式输出文件名 |
| `modules/t03_virtual_junction_anchor/README.md` | T03 操作者入口 | `operator_guide` | 说明 T03 `Step1~Step7` 模块定位、关联阶段 CLI、冻结前置入口、内网 full-input shell/watch 用法、批次根目录 `virtual_intersection_polygons.gpkg / nodes.gpkg / nodes_anchor_update_audit.*` 成果、`fail3` downstream output 语义与默认路径边界 |
| `modules/t03_virtual_junction_anchor/AGENTS.md` | T03 durable guidance | `durable_guidance` | 只保留模块级边界、`Step1~Step7` 主链、冻结前置约束、`Association / Finalization` 实现阶段命名边界与当前执行边界 |
| `modules/t03_virtual_junction_anchor/history/*` | T03 模块级历史 closeout | `history` | 记录阶段性 closeout 与准备材料；不替代当前 `INTERFACE_CONTRACT.md` 与 `architecture/*` 源事实 |
| `specs/t03-*` | T03 spec-kit 变更工件 | `history_or_active_change_artifact` | T03 历史与当前定向治理规格目录，目录名保留创建时语境；不替代模块长期真相 |
| `modules/t04_divmerge_virtual_polygon/architecture/*` | T04 模块长期架构真相 | `source_of_truth` | T04 正式模块的长期文档主表面；当前正式范围覆盖 `Step1-7` 主链，明确 `admission / local_context / topology / event_interpretation / arbiter / support_domain / polygon_assembly / final_publish / review_render / outputs / batch_runner` 分层、Step4 候选 ledger / 仲裁发布与 Step5-7 消费边界 |
| `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md` | T04 稳定契约面 | `source_of_truth` | 固化 case-package 输入、Step1-7 业务边界、event-unit 规则、Step4 arbiter 发布字段、review PNG / flat mirror / index / summary 输出、Step7 accepted/rejected 发布与当前无 repo 官方 CLI 的入口状态 |
| `modules/t04_divmerge_virtual_polygon/README.md` | T04 操作者入口 | `operator_guide` | 说明默认 case root、默认输出根、模块内 runner 与 Step4 review 产物位置 |
| `modules/t04_divmerge_virtual_polygon/AGENTS.md` | T04 durable guidance | `durable_guidance` | 只保留 T04 当前正式范围已扩展到 `Step1-7`、Step5-7 研发走 SpecKit、不得新增 repo 官方入口的模块边界 |
| `modules/t05_junction_surface_fusion/architecture/*` | T05 模块长期架构真相 | `source_of_truth` | T05 Phase 1 / Phase 2 长期文档主表面；覆盖路口面融合发布、RCSD junctionization、SWSD-RCSD relation 生产与 copy-on-write RCSD 网络输出 |
| `modules/t05_junction_surface_fusion/INTERFACE_CONTRACT.md` | T05 稳定契约面 | `source_of_truth` | 固化 Phase 1 / Phase 2 callable runner、输入、输出、relation 字段、copy-on-write RCSD 成果与审计契约 |
| `modules/t05_junction_surface_fusion/README.md` | T05 操作者入口 | `operator_guide` | 说明 Phase 1 / Phase 2 callable runner、内网 handoff / experiment 脚本、输出文件与审计口径 |
| `modules/t05_junction_surface_fusion/AGENTS.md` | T05 durable guidance | `durable_guidance` | 只保留 T05 Phase 1 / Phase 2 执行边界、输入只读、copy-on-write 输出与入口边界 |
| `modules/t06_segment_fusion_precheck/architecture/*` | T06 模块长期架构真相 | `source_of_truth` | T06 Step1 / Step2 / Step3 长期文档主表面；覆盖 SWSD 可融合 Segment 识别、buffer-based RCSDSegment 构建、replaceable 集合、F-RCSD 输出与语义路口 C 重建 |
| `modules/t06_segment_fusion_precheck/INTERFACE_CONTRACT.md` | T06 稳定契约面 | `source_of_truth` | 固化 Step1 / Step2 / Step3 callable runner、T01/T05/Step2 输入、输出文件、字段、失败原因与验收标准 |
| `modules/t06_segment_fusion_precheck/README.md` | T06 操作者入口 | `operator_guide` | 说明模块内 runner、内网脚本入口、输入输出、Step3 状态、非目标和审计产物 |
| `modules/t06_segment_fusion_precheck/AGENTS.md` | T06 durable guidance | `durable_guidance` | 只保留 T06 Step1 / Step2 / Step3 范围、内网脚本包装边界、copy-on-write 与不回改 T01/T05/Step2 输入的模块边界 |
| `specs/t06-buffer-rcsd-segment-extraction/*`、`specs/t06-step3-segment-replacement/*` | T06 变更工件 | `active_change_artifact` | 记录 T06 Step2 buffer-based RCSDSegment 构建与 Step3 Segment 替换输出 / 语义路口重建的规格、计划与任务，不替代模块长期真相 |
| `modules/t07_semantic_junction_anchor/architecture/*` | T07 模块长期架构真相 | `source_of_truth` | T07 Step1 / Step2 / Step3 长期文档主表面；覆盖语义路口级 `has_evd / is_anchor / anchor_reason`、T07 handoff surface/evidence 与 T05 relation 补锚，不处理 Segment |
| `modules/t07_semantic_junction_anchor/INTERFACE_CONTRACT.md` | T07 稳定契约面 | `source_of_truth` | 固化 Step1 / Step2 / Step3 callable runner、`nodes / DriveZone / RCSDIntersection / intersection_match_all / RCSDNode` 输入、字段、`t07_rcsdintersection_anchor_surface / t07_swsd_rcsd_relation_evidence` 输出文件、Step2 / Step3 锚定计数、审计、失败原因与验收标准 |
| `modules/t07_semantic_junction_anchor/README.md` | T07 操作者入口 | `operator_guide` | 说明模块内 runner、内网脚本入口、输入输出、非目标和审计产物 |
| `modules/t07_semantic_junction_anchor/AGENTS.md` | T07 durable guidance | `durable_guidance` | 只保留 T07 Step1 / Step2 / Step3 范围、内网脚本包装边界、`kind_2` 口径、T05 relation 补锚口径与无 Segment 依赖 |
| `modules/t08_preprocess/architecture/*` | T08 模块长期架构真相 | `source_of_truth` | T08 正式预处理模块长期文档主表面；当前覆盖 Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合、Tool4 路口类型修复、Tool5 复杂路口预处理、Tool6 Nodes 类型质检、Tool7 交通限制显性化、Tool8 Laneinfo 箭头显性化与 Tool9 RCSD 数据清理 |
| `modules/t08_preprocess/INTERFACE_CONTRACT.md` | T08 稳定契约面 | `source_of_truth` | 固化 Tool1 / Tool2 / Tool3 / Tool4 / Tool5 / Tool6 / Tool7 / Tool8 / Tool9 输入、输出、入口、参数、CRS、summary、`_toolX` 输出命名与验收标准 |
| `modules/t08_preprocess/README.md` | T08 操作者入口 | `operator_guide` | 说明 Tool1 / Tool2 / Tool3 / Tool4 / Tool5 / Tool6 / Tool7 / Tool8 / Tool9 内网脚本、示例路径、输出与主要文档 |
| `modules/t08_preprocess/AGENTS.md` | T08 durable guidance | `durable_guidance` | 只保留 T08 工具作为正式组成部分、Tool1-Tool9 范围、`_toolX` 输出命名与入口边界 |
| `modules/p01_arm_build/architecture/*` | P01 模块长期架构真相 | `source_of_truth` | P01 v1.0.0 长期文档主表面；覆盖 A1 Arm 构建、A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原 |
| `modules/p01_arm_build/INTERFACE_CONTRACT.md` | P01 稳定契约面 | `source_of_truth` | 固化 A1 / A2 / P01-Final 输入输出、RoadNextRoad-aware movement、Source exact mapping、final GeoJSON、audit / issue 与无 repo 官方 CLI 的入口状态 |
| `modules/p01_arm_build/README.md` | P01 操作者入口 | `operator_guide` | 说明 P01-A1/A2/Final 模块定位、边界、模块内 callable runner、dev helper 与主要文档 |
| `modules/p01_arm_build/AGENTS.md` | P01 durable guidance | `durable_guidance` | 只保留 P01-A1/A2/Final 边界、禁止 Grade/turnType movement/几何反推/空间近似 source mapping/P01-B 以及正式入口边界 |
| `specs/t04-step14-speckit-refactor/*` | T04 Step1-4 治理变更工件 | `active_change_artifact` | 记录 T04 doc-first formalization、架构规划、任务拆解与重构计划，不替代模块长期真相 |
| `specs/t04-step34-repair-formalization/*` | T04 Step3/Step4 修复方案变更工件 | `active_change_artifact` | 记录 Step3 粗骨架分层、Step4 complex/multi 修复方案、契约冲突冻结与后续实现任务，不替代模块长期真相 |
| `specs/p01-arm-build/*` | P01 v1.0.0 变更工件 | `active_change_artifact` | 记录 P01-A1 / A2 / Final 的成果级规格、计划、任务与覆盖状态，不替代模块长期真相 |
| `specs/p01-arm-alignment/*` | P01-A2 变更工件 | `active_change_artifact` | 记录 P01-A2 Arm 配准与 LogicalArmGroup 构建的需求规格、计划与任务拆解，不替代模块长期真相 |

## 当前模块模板文档面

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `modules/_template/architecture/*` | 模板级长期结构骨架 | `template` | 新模块启动时复制并补实 |
| `modules/_template/INTERFACE_CONTRACT.md` | 模板级稳定契约骨架 | `template` | 给出统一章节顺序 |
| `modules/_template/AGENTS.md` | 模板级 durable guidance 骨架 | `template` | 只给出工作边界 |
| `modules/_template/review-summary.md` | 模板级治理摘要骨架 | `template` | 建议在模块成熟后启用 |
| `modules/_template/README.md` | 模板级操作者总览骨架 | `template` | 按需启用 |

## 当前历史 / 归档位置

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `docs/doc-governance/history/` | 历史治理过程文档 | `legacy_candidate` | 当前为预留目录 |
| `docs/archive/nonstandard/` | 项目级非标准历史说明 | `legacy_candidate` | 当前为预留目录 |
| `specs/archive/` | 历史变更工件 | `legacy_candidate` | 当前为预留目录 |

## 当前结论

1. 主阅读路径已经收口到项目级源事实、治理入口、结构元数据、T01 / T02 正式模块文档面与模块模板。
2. 当前已存在正式业务模块文档面：`modules/t01_data_preprocess/*`、`modules/t02_junction_anchor/*`、`modules/t03_virtual_junction_anchor/*`、`modules/t04_divmerge_virtual_polygon/*`、`modules/t05_junction_surface_fusion/*`、`modules/t06_segment_fusion_precheck/*`、`modules/t07_semantic_junction_anchor/*`、`modules/t08_preprocess/*` 与 P01 成果模块文档面 `modules/p01_arm_build/*`。
3. `t00_utility_toolbox` 当前作为已纳入治理的工具集合模块文档面存在。
4. `_template` 继续承担新模块启动模板职责。
5. 模块根目录不放 `SKILL.md` 的规则已经写回仓库级文档。
