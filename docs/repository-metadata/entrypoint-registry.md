# 当前执行入口注册表

## 1. 文档目的

登记当前仓库已识别的执行入口脚本与入口文件。

## 2. 当前登记摘要

- 当前真实执行入口共 `101` 个。
- 分布概览：
  - repo 级入口文件：`71`（`Makefile` 1 + `scripts/` 69 + `.venv/bin/python -m rcsd_topo_poc` 1）
  - QGIS 插件加载入口：`1`
  - 模块级 `python -m` 专项入口：`1`
  - CLI 稳定子命令：`28`
- 维护口径：
  - CLI 子命令以 `.venv/bin/python -m rcsd_topo_poc --help` 为准。
  - 脚本入口以 `scripts/` 下纳入版本管理的文件为准。
  - 若摘要数字、表格行数与事实来源不一致，以事实来源回填本表。
- 当前仓库本地标准环境与自检入口：
  - `make env-sync`
  - `make doctor`
  - `make test`
  - `make smoke`
- 当前 `make test` / `make smoke` 已重新纳入 `tests/modules/t03_virtual_junction_anchor/**`、`tests/test_smoke_t03_step3_batch.py` 与 `tests/test_smoke_t03_association_batch.py`；T03 不再作为默认本地自检的排除项。
- 新增依赖或新增入口时，除更新本表外，还必须同步更新 `pyproject.toml`、`uv.lock`、repo root `Makefile`、`doctor` 逻辑以及受影响模块文档。
- 当前 T03 模块仍保留单独治理轮次；在其专门收口之前，不得把 T03 现存命令示例当作新模块模板。

## 3. 当前已识别入口清单

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `Makefile` | `Makefile` | repo 级 | 仓库级环境同步 / 自检 / 测试入口 | `active` | 否 |
| `agent_enter.sh` | `scripts/agent_enter.sh` | repo 级 | 进入仓库后的标准握手辅助 | `active` | 否 |
| `t01_pull_from_internal_github.sh` | `scripts/t01_pull_from_internal_github.sh` | repo 级 | T01 部署机从内网 Git 远端 clone/fetch/pull 主干 | `active` | 否 |
| `t01_pull_main_from_internal_github.sh` | `scripts/t01_pull_main_from_internal_github.sh` | repo 级 | 在现有 repo worktree 中从指定 remote / branch 拉取主干；若 worktree dirty 或存在 untracked 文件则阻断 | `active` | 否 |
| `t01_run_full_data.sh` | `scripts/t01_run_full_data.sh` | repo 级 | 以 `t01-run-skill-v1` 为底层入口的 T01 全量运行包装脚本，支持 roads / nodes 输入、输出目录、freeze compare 与 debug 参数 | `active` | 否 |
| `t01_run_full_data_skill_v1.sh` | `scripts/t01_run_full_data_skill_v1.sh` | repo 级 | T01 accepted runner 全量执行脚本 | `active` | 否 |
| `t02_extract_key_info.py` | `scripts/t02_extract_key_info.py` | repo 级 | 提取 T02 stage1 / stage2 运行目录的高信号摘要并输出 JSON | `active` | 否 |
| `t02_extract_key_info_latest.sh` | `scripts/t02_extract_key_info_latest.sh` | repo 级 | 自动发现最近 stage1 / stage2 运行目录并调用 `scripts/t02_extract_key_info.py` 生成 JSON 摘要 | `active` | 否 |
| `t02_run_stage3_full_input_8workers.sh` | `scripts/t02_run_stage3_full_input_8workers.sh` | repo 级 | T02 stage3 full-input 8 线程自动发现运行包装脚本 | `active` | 否 |
| `t02_run_stage3_internal_full_input_8workers.sh` | `scripts/t02_run_stage3_internal_full_input_8workers.sh` | repo 级 | T02 stage3 内网 full-input 8 线程运行脚本，统一输出 visual_checks 目录 | `active` | 否 |
| `t02_pull_stage4_from_internal_github.sh` | `scripts/t02_pull_stage4_from_internal_github.sh` | repo 级 | T02 stage4 内网工作副本拉取当前 Stage4 分支包装脚本 | `active` | 否 |
| `t02_run_stage1_internal_full_input.sh` | `scripts/t02_run_stage1_internal_full_input.sh` | repo 级 | T02 stage1 内网 full-input 运行脚本，读取 T01 segment/nodes 与 DriveZone 并产出 stage1 批次目录 | `active` | 否 |
| `t02_run_stage2_internal_full_input.sh` | `scripts/t02_run_stage2_internal_full_input.sh` | repo 级 | T02 stage2 内网 full-input 运行脚本，默认接最近一次 stage1 批次并读取 RCSDIntersection 产出 stage2 批次目录 | `active` | 否 |
| `t02_run_stage4_internal_divmerge_single_case.sh` | `scripts/t02_run_stage4_internal_divmerge_single_case.sh` | repo 级 | T02 stage4 内网单 case div/merge 虚拟路口面运行脚本 | `active` | 否 |
| `t02_run_stage4_internal_full_input_8workers.sh` | `scripts/t02_run_stage4_internal_full_input_8workers.sh` | repo 级 | T02 stage4 内网 full-input 8 线程运行脚本，自动发现 `kind_2 in {8,16}` 候选并汇总 batch summary | `active` | 否 |
| `t02_run_stage4_internal_anchor2_cases.sh` | `scripts/t02_run_stage4_internal_anchor2_cases.sh` | repo 级 | T02 stage4 内网 case-package 运行脚本，扫描 `T02/Anchor_2` 根目录下的 bundle txt 或一级纯数字 `mainnodeid` case 目录，解包后逐 case 执行 Stage4 并写 batch summary | `active` | 否 |
| `t02_run_aggregate_continuous_divmerge_internal.sh` | `scripts/t02_run_aggregate_continuous_divmerge_internal.sh` | repo 级 | T02 连续分歧 / 合流复杂路口聚合 Tool 内网运行脚本，默认读取指定 Stage2 批次 `nodes.gpkg` 与 T02 `roads.gpkg` 并输出 `nodes_fix.gpkg / roads_fix.gpkg / continuous_divmerge_report.json` | `active` | 否 |
| `t02_watch_stage4_internal_full_input.sh` | `scripts/t02_watch_stage4_internal_full_input.sh` | repo 级 | T02 stage4 内网 full-input 运行监控脚本，按批次汇总 selected/completed/accepted/review/rejected/pending | `active` | 否 |
| `t02_export_text_bundle_internal_selected_mainnodeids.sh` | `scripts/t02_export_text_bundle_internal_selected_mainnodeids.sh` | repo 级 | T02 内网多 mainnodeid 文本证据包导出脚本，固定 selected mainnodeid 列表并输出单个 bundle txt | `active` | 否 |
| `t02_export_text_bundle_internal_divmerge_focus_mainnodeids.sh` | `scripts/t02_export_text_bundle_internal_divmerge_focus_mainnodeids.sh` | repo 级 | T02 内网分歧/合流 focus mainnodeid 文本证据包导出脚本，默认打包 `13460276 / 13460274 / 765592 / 13460256`，参数全部可外显覆盖 | `active` | 否 |
| `t02_export_text_bundle_internal_multi_mainnodeids.sh` | `scripts/t02_export_text_bundle_internal_multi_mainnodeids.sh` | repo 级 | T02 内网多 mainnodeid 单文件文本证据包导出脚本，默认写 `Anchor_2` 根目录，支持位置参数或 `MAINNODEIDS_TEXT` 自定义并可自动解包 | `active` | 否 |
| `pull_rcsd_topo_poc_main_from_github.sh` | `scripts/pull_rcsd_topo_poc_main_from_github.sh` | repo 级 | RCSD_Topo_Poc 固定仓库路径 / 固定远端 / 固定主干的零参数 GitHub 下拉脚本；首次运行可 clone，后续运行执行 fetch + switch main + ff-only pull | `active` | 否 |
| `p01_run_innernet_case.sh` | `scripts/p01_run_innernet_case.sh` | repo 级 | P01 内网单 Case 端到端执行脚本；直接消费全量 SH SWSD / RCSD / F-RCSD Node、Road 与 RoadNextRoad 输入和单个 `JUNCTION_GROUP`，不支持文本包打包 / 解包；输出以 `<OUT_ROOT>/<case_id>/` 为主目录，A1 / A2 原始 run root 仅保留在 `_raw/` | `active` | 否 |
| `p02_run_wuhan_internal_case.py` | `scripts/p02_run_wuhan_internal_case.py` | repo 级 | P02 武汉内网单 Case 端到端入口；唯一必填参数为四个约定 GeoJSON 所在 `--input-dir`，自动应用模块登记的 16 条人工锚定关系、9 条 `SNodeId/ENodeId` 修正和 `609020493` T 型人工修正，编排 T08→T01→T05→T06，执行当前结果硬校验并生成相对路径 QGIS 分析工程 | `active` | 否 |
| `p02_run_wuhan_innernet_case.sh` | `scripts/p02_run_wuhan_innernet_case.sh` | repo 级 | P02 武汉内网 WSL 固定 Case 包装入口；默认使用 `/mnt/d/Work/RCSD_Topo_Poc`、约定四 GeoJSON 输入目录、仓库 `.venv/bin/python` 与 `/usr/bin/python3` PyQGIS，完成前置检查、持久日志、`--qgis-mode required` 转调和 17 阶段/QGIS 结果复核，不复制业务算法 | `active` | 否 |
| `t03_run_internal_full_input_8workers.sh` | `scripts/t03_run_internal_full_input_8workers.sh` | repo 级 | T03 模块级内网 full-input 全量运行主脚本；外层 shell 暴露 T03 full-input public env surface，并可通过可选 `INTERSECTION_MATCH_ALL_PATH` 读取 `intersection_match_all.geojson` 作为最终 relation 校验输入，旧 `INTERSECTION_MATCH_T07_PATH` 仅作兼容别名且不得与不同文件的 `INTERSECTION_MATCH_ALL_PATH` 同时提供；内部主链为 candidate discovery / shared handle preload / per-case local context query / direct Step1~Step7 case execution，并在 `.venv/bin/python` 关键依赖不可用时自动 fallback 到 `python3`；当前 `_internal/<RUN_ID>/` 已拆分为 `t03_internal_full_input_manifest/progress/performance/failure` 等模块级 observability 工件，批次根目录正式成果至少包括 `virtual_intersection_polygons.gpkg`、downstream `nodes.gpkg`、`t03_swsd_rcsd_relation_evidence.csv/json`、`intersection_match_t03.geojson` 与 `t03_review_*` review-only 输出 | `active` | 否 |
| `t03_watch_internal_full_input.sh` | `scripts/t03_watch_internal_full_input.sh` | repo 级 | T03 模块级内网 full-input 实时跟踪主脚本；当前作为 T03 internal full-input 的正式 repo 级监控面，默认按 formal-first 口径显示 `total / completed / running / pending / success / failed`（其中 `success = accepted`、`failed = rejected + runtime_failed`）与执行阶段信息，只有 `DEBUG_VISUAL=1` 时才从 review-only 工件读取 V1-V5 统计 | `active` | 否 |
| `t03_run_internal_full_input_innernet.sh` | `scripts/t03_run_internal_full_input_innernet.sh` | repo 级 | T03 internal full-input 内网运行包装脚本，设置 innernet 默认运行参数后转发到 `t03_run_internal_full_input_8workers.sh` | `active` | 否 |
| `t03_run_internal_full_input_innernet_flat_review.sh` | `scripts/t03_run_internal_full_input_innernet_flat_review.sh` | repo 级 | T03 internal full-input 内网 flat-review 运行包装脚本，写入 latest run id 并转发到 `t03_run_internal_full_input_8workers.sh` | `active` | 否 |
| `t03_watch_internal_full_input_innernet.sh` | `scripts/t03_watch_internal_full_input_innernet.sh` | repo 级 | T03 internal full-input 内网监控包装脚本，设置默认监控参数后转发到 `t03_watch_internal_full_input.sh` | `active` | 否 |
| `t03_watch_internal_full_input_innernet_flat_review.sh` | `scripts/t03_watch_internal_full_input_innernet_flat_review.sh` | repo 级 | T03 internal full-input 内网 flat-review 监控包装脚本，从 latest run id 文件发现 RUN_ID 后转发到 `t03_watch_internal_full_input.sh` | `active` | 否 |
| `t03_export_text_bundle_internal_multi_mainnodeids.sh` | `scripts/t03_export_text_bundle_internal_multi_mainnodeids.sh` | repo 级 | T03 内网多 mainnodeid 单文件文本证据包导出脚本；复用 T03/T04 共用文本包模块，支持命令参数或环境变量覆盖 SWSD/RCSD/DriveZone/DivStripZone 输入路径，超过阈值自动分片 | `active` | 否 |
| `t05_backfill_t03_relation_evidence_innernet.py` | `scripts/t05_backfill_t03_relation_evidence_innernet.py` | repo 级 | T05 Phase 2 内网 handoff 补齐脚本；读取 T03 run root 的批次 relation evidence 与 case 级 `step6_status/step6_audit`，输出补齐后的 `t03_swsd_rcsd_relation_evidence_backfilled.*`、audit 与 summary，不修改 T03 主链或原始输出 | `active` | 否 |
| `t05_innernet_experiment.py` | `scripts/t05_innernet_experiment.py` | repo 级 | T05 内网 Phase 1 + Phase 2 联合实验入口；以 T02/T03/T04 成果目录、原始 RCSDRoad/RCSDNode、final nodes 与 RCSDIntersection 为参数，先执行 T03 evidence handoff 补齐，再运行 junction surface fusion 与 one-to-one relation 发布；可选消费 T10 side-group endpoint candidates 与 pair-anchor endpoint clusters 作为已有 relation / road-only split 的 RCSDNode grouping 补充；可选 `--t11-manual-relation` 消费 T11 人工正向关系 CSV，`NULL`/空白审计行不进入 T05 | `active` | 否 |
| `t06_run_innernet_precheck.py` | `scripts/t06_run_innernet_precheck.py` | repo 级 | T06 内网 Step1 + Step2 运行包装脚本；读取 T01 `segment.gpkg / roads.gpkg`、final `nodes.gpkg` 与 T05 Phase 2 `intersection_match_all.geojson / rcsdroad_out.gpkg / rcsdnode_out.gpkg`，输出 T06 candidates / replaceable / rejected / summary，不修改输入文件 | `active` | 否 |
| `t06_run_step3_segment_replacement.py` | `scripts/t06_run_step3_segment_replacement.py` | repo 级 | T06 Step3 独立运行脚本；消费既有 T06 run root 的 Step2 `t06_rcsd_segment_replaceable.gpkg`、可选 `t06_special_junction_group_audit.*` 与 `t06_segment_group_replacement_audit.gpkg`，读取 SWSD Segment/Road/Node 与 T05 Phase 2 copy-on-write RCSDRoad/RCSDNode；可选读取 T07/T03/T04/T05 surface 与 T04 audit 执行 junction surface topology 后处理；输出 F-RCSD Road / Node、替换单元、路口 C 重建、id 冲突审计与拓扑审计，不改变 Step1 + Step2 内网脚本默认行为 | `active` | 否 |
| `t07_run_semantic_junction_anchor_innernet.sh` | `scripts/t07_run_semantic_junction_anchor_innernet.sh` | repo 级 | T07 内网语义路口级 Step1 / Step2 执行脚本；读取 `nodes / DriveZone / RCSDIntersection`，可选读取 RCSDNode 辅助判断 RCSDIntersection 消费性，调用模块内 callable runner 输出代表 node 的 `has_evd / is_anchor / anchor_reason`，不处理 Segment | `active` | 否 |
| `t07_run_step3_intersection_match_innernet.sh` | `scripts/t07_run_step3_intersection_match_innernet.sh` | repo 级 | T07 Step3 独立内网执行脚本；读取 Step2 后 `nodes.gpkg`、显式提供的 `intersection_match_all.geojson` 兼容 relation 文件与输入 `RCSDNode.gpkg`，输出 `intersection_match_t07.geojson` 并对符合条件的 SWSD 代表 node 补写 `is_anchor = yes`；T 型路口 `kind_2 = 2048` 不由 T07 独立建立 surface 关系，但可在兼容 relation 成功且 RCSD base 存在时补锚；不处理 Segment | `active` | 否 |
| `t04_run_internal_full_input_8workers.sh` | `scripts/t04_run_internal_full_input_8workers.sh` | repo 级 | T04 模块级内网 full-input 全量运行主脚本；输入全局 `nodes/roads/DriveZone/DivStripZone/RCSDRoad/RCSDNode`，可通过 `INTERSECTION_MATCH_T07_PATH / INTERSECTION_MATCH_T03_PATH` 读取 T07/T03 最终 relation 校验输入，执行 preflight / candidate discovery / shared bootstrap / direct Step1-7 case execution / batch closeout，并输出 `divmerge_virtual_anchor_surface*`、`intersection_match_t04.geojson` 正式成果与 `visual_checks/final_*` 最终平铺目视审计入口；full-input 不通过 repo CLI 子命令承载 | `active` | 否 |
| `t04_watch_internal_full_input.sh` | `scripts/t04_watch_internal_full_input.sh` | repo 级 | T04 内网 full-input 实时监控脚本；显示 `selected / completed / running / pending / accepted / rejected / runtime_failed / missing_status`、phase/status/message/entered_case_execution 与性能估算，并支持 `CASE_SCAN=auto/on/off` 降扫描 | `active` | 否 |
| `t04_run_internal_full_input_innernet_flat_review.sh` | `scripts/t04_run_internal_full_input_innernet_flat_review.sh` | repo 级 | T04 内网 full-input 最终平铺目视审计运行包装；默认关闭 debug、启用 resume/retry/perf audit、使用 failed_only snapshot，并转发到 `t04_run_internal_full_input_8workers.sh` | `active` | 否 |
| `t04_export_text_bundle_internal_multi_mainnodeids.sh` | `scripts/t04_export_text_bundle_internal_multi_mainnodeids.sh` | repo 级 | T04 内网多 mainnodeid 单文件文本证据包导出脚本；复用 T03/T04 共用文本包模块，支持命令参数或环境变量覆盖 SWSD/RCSD/DriveZone/DivStripZone 输入路径，超过阈值自动分片 | `active` | 否 |
| `t04_fallback_postprocess_existing.sh` | `scripts/t04_fallback_postprocess_existing.sh` | repo 级 | T04 补充策略 postprocess-existing 内网脚本；以既有 T04 run root 为参数，补齐 fallback SWSD-RCSD relation evidence 并把成功 fallback 的代表 node 写为 `fail4_fallback`，不重跑 Step1-7、不生产新路口面 | `active` | 否 |
| `t04_probe_706243_706247_innernet.py` | `scripts/t04_probe_706243_706247_innernet.py` | repo 级 | T04 内网专项诊断脚本；只读分析或重跑 `706243 / 706247`，输出 Step3/4/5/6/7、RCSD audit、候选与 GPKG 几何摘要，用于定位内网 full-input 与最新基线差异 | `active` | 是 |
| `.venv/bin/python -m rcsd_topo_poc` | `src/rcsd_topo_poc/__main__.py` | repo 级 | Python 包入口 | `active` | 否 |
| `doctor` | `src/rcsd_topo_poc/cli.py` | repo 级 | 检查 repo / docs / repo `.venv` / 锁文件 / 运行与开发依赖是否齐备 | `active` | 否 |
| `qc-template` | `src/rcsd_topo_poc/cli.py` | repo 级 | 打印历史 `TEXT_QC_BUNDLE v1` 兼容模板；当前正式协作以文件证据包和 summary/audit/review 为准 | `active` | 否 |
| `qc-demo` | `src/rcsd_topo_poc/cli.py` | repo 级 | 打印历史 `TEXT_QC_BUNDLE` 兼容示例；当前正式协作以文件证据包和 summary/audit/review 为准 | `active` | 否 |
| `lint-text` | `src/rcsd_topo_poc/cli.py` | repo 级 | 校验文本可粘贴性，包括体积、行数与长行约束 | `active` | 否 |
| `t01-step1-pair-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step1 pair candidate 诊断入口 | `active` | 否 |
| `t01-step2-segment-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step2 validated/trunk/segment_body 诊断入口 | `active` | 否 |
| `t01-build-validation-slices` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 validation slice 构建入口 | `active` | 否 |
| `t01-s2-refresh-node-road` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step3 refresh 节点/道路刷新入口 | `active` | 否 |
| `t01-step4-residual-graph` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step4 residual graph 入口 | `active` | 否 |
| `t01-step5-staged-residual-graph` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step5A/5B/5C staged residual graph 入口 | `active` | 否 |
| `t01-run-skill-v1` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Skill v1 end-to-end 入口 | `active` | 否 |
| `t01-continue-oneway-segment` | `src/rcsd_topo_poc/cli.py` | repo 级 | 从既有 Step5 refreshed 输出继续执行 oneway completion 与 Step6 | `active` | 否 |
| `t01-step6-segment-aggregation-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step6 segment 聚合入口 | `active` | 否 |
| `t01-compare-freeze` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 freeze compare 入口 | `active` | 否 |
| `t02-stage1-drivezone-gate` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 stage1 DriveZone / has_evd gate 入口 | `active` | 否 |
| `t02-stage2-anchor-recognition` | `src/rcsd_topo_poc/cli.py` | repo 级 | 在 stage1 node 输出与 `RCSDIntersection` 输入上执行 T02 stage2 anchor recognition | `active` | 否 |
| `t02-virtual-intersection-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 stage3 虚拟路口锚定入口（`case-package` 为唯一正式验收基线，`full-input` 为完整数据 `fixture / dev-only / regression`） | `active` | 否 |
| `t03-step3-legal-space` | `src/rcsd_topo_poc/cli.py` | repo 级 | T03 Phase A / Step3 legal-space baseline 入口；消费 Anchor61 `case-package`，输出 case 级产物、平铺 PNG、索引与汇总 | `active` | 否 |
| `t03-rcsd-association` | `src/rcsd_topo_poc/cli.py` | repo 级 | T03 RCSD 关联阶段入口；业务含义对应 `Step4 + Step5`，消费 Anchor61 `case-package` 与冻结 Step3 run root，输出 `required/support/excluded` RCSD 中间结果包、平铺 PNG、索引与汇总 | `active` | 否 |
| `t02-fix-node-error-2` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 `node_error_2` 独立离线修复工具，输出 `nodes_fix.gpkg / roads_fix.gpkg / fix_report.json` | `active` | 否 |
| `t02-export-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 单 / 多 mainnodeid 文本证据包导出入口 | `active` | 否 |
| `t02-decode-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 单 / 多 mainnodeid 文本证据包解包入口 | `active` | 否 |
| `t03-export-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T03 单 / 多 mainnodeid 文本证据包导出入口；T03/T04-ready 输入包含 `nodes/roads/DriveZone/DivStripZone/RCSDRoad/RCSDNode`，超过阈值自动分片 | `active` | 否 |
| `t03-decode-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T03 单 / 多 mainnodeid 文本证据包解包入口；支持自动拼接 T03 分片证据包 | `active` | 否 |
| `t04-export-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T04 单 / 多 mainnodeid 文本证据包导出入口；底层复用 T03/T04-ready 共用文本包模块 | `active` | 否 |
| `t04-decode-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T04 单 / 多 mainnodeid 文本证据包解包入口；支持自动拼接 T04 分片证据包 | `active` | 否 |
| `t02-stage4-divmerge-virtual-polygon` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 stage4 单 case div/merge 虚拟路口面独立入口 | `active` | 否 |
| `t02-aggregate-continuous-divmerge` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 连续分歧 / 合流复杂路口聚合离线工具，按 T04 continuous chain 规则改写 `nodes / roads` 并输出 `nodes_fix.gpkg / roads_fix.gpkg / continuous_divmerge_report.json` | `active` | 否 |
| `t00_tool1_patch_directory_bootstrap.py` | `scripts/t00_tool1_patch_directory_bootstrap.py` | repo 级 | T00 Tool1 固定脚本 | `active` | 否 |
| `t00_tool2_drivezone_merge.py` | `scripts/t00_tool2_drivezone_merge.py` | repo 级 | T00 Tool2 DriveZone 预处理与合并 | `active` | 否 |
| `t00_tool3_intersection_merge.py` | `scripts/t00_tool3_intersection_merge.py` | repo 级 | T00 Tool3 Intersection 预处理与汇总 | `active` | 否 |
| `t00_tool4_a200_patch_join.py` | `scripts/t00_tool4_a200_patch_join.py` | repo 级 | T00 Tool4 A200 road 增加 patch_id | `active` | 否 |
| `t00_tool5_a200_kind_enrich.py` | `scripts/t00_tool5_a200_kind_enrich.py` | repo 级 | T00 Tool5 A200 road 增加 kind | `active` | 否 |
| `t00_tool6_node_export.py` | `scripts/t00_tool6_node_export.py` | repo 级 | T00 Tool6 shp 导出 GeoJSON | `active` | 否 |
| `t00_tool7_geojson_to_gpkg.py` | `scripts/t00_tool7_geojson_to_gpkg.py` | repo 级 | T00 Tool7 顶层目录 GeoJSON 批量转 GPKG | `active` | 否 |
| `t00_tool9_divstripzone_merge.py` | `scripts/t00_tool9_divstripzone_merge.py` | repo 级 | T00 Tool9 DivStripZone 预处理与汇总 | `active` | 否 |
| `t00_tool10_json_point_export.py` | `scripts/t00_tool10_json_point_export.py` | repo 级 | T00 Tool10 指定 JSON 上车点导出双图层 GPKG | `active` | 否 |
| `t00_tool11_mif_to_vector.py` | `scripts/t00_tool11_mif_to_vector.py` | repo 级 | T00 Tool11 MIF 批量 / 单文件转 GeoJSON 与 GPKG | `active` | 否 |
| `t08_tool1_vector_convert.py` | `scripts/t08_tool1_vector_convert.py` | repo 级 | T08 Tool1 基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，转换成果写回输入目录下并使用同 stem、不同格式后缀，采用流式转换并输出进度，支持可选目标 EPSG 与 summary 输出 | `active` | 否 |
| `t08_tool2_road_preprocess.py` | `scripts/t08_tool2_road_preprocess.py` | repo 级 | T08 Tool2 Road GPKG 预处理，补充 `patch_id` 与原始 `kind`，删除 `kind` 具有 `17` 主辅路出入口属性的 Road 并输出 `event_road_0a_tool2.gpkg`，成果输出文件名以 `_tool2` 结尾 | `active` | 否 |
| `t08_tool3_nodes_type_aggregation.py` | `scripts/t08_tool3_nodes_type_aggregation.py` | repo 级 | T08 Tool3 Nodes 类型聚合，补充 `kind_2 / grade_2` 并处理环岛 mainnode，输出 `EPSG:3857` Nodes GPKG，成果输出文件名以 `_tool3` 结尾 | `active` | 否 |
| `t08_tool4_junction_type_repair.py` | `scripts/t08_tool4_junction_type_repair.py` | repo 级 | T08 Tool4 路口类型修复，校验 `kind_2=2048` T 型语义路口、分合流一入一出类型，并可消费 Tool6 人工确认成果，copy-on-write 输出完整 Nodes、可选 Roads、audit Nodes GPKG 与 summary，不改写输入 Nodes/Roads，成果输出文件名以 `_tool4` 结尾 | `active` | 否 |
| `t08_tool5_complex_junction_preprocess.py` | `scripts/t08_tool5_complex_junction_preprocess.py` | repo 级 | T08 Tool5 复杂路口预处理，构建复杂分歧 / 合流路口，并可基于 `RCSDIntersection` 识别和处理错误 1 对多路口，copy-on-write 输出 `EPSG:3857` Nodes/Roads/audit Nodes GPKG 与 summary，成果输出文件名以 `_tool5` 结尾 | `active` | 否 |
| `t08_tool6_nodes_type_qc.py` | `scripts/t08_tool6_nodes_type_qc.py` | repo 级 | T08 Tool6 Nodes 类型质检，基于语义路口入出度、连续分歧合流 T 型候选与交叉路口候选规则输出 `node_error_tool6.csv / node_error_tool6.gpkg / node_error_summary_tool6.json`，CSV 最后一列 `是否修复` 默认 `1`，不改写输入 Nodes/Roads | `active` | 否 |
| `t08_tool7_traffic_restriction.py` | `scripts/t08_tool7_traffic_restriction.py` | repo 级 | T08 Tool7 交通限制显性化，读取 SW C 表、SW Node 与 SW Road，筛选 `CondType=1` 且 in/out Link 均存在于 SW Road 的记录，输出 `sw_restriction_tool7.gpkg` 与 summary，不改写输入 | `active` | 否 |
| `t08_tool8_lane_arrow.py` | `scripts/t08_tool8_lane_arrow.py` | repo 级 | T08 Tool8 Laneinfo 箭头显性化，读取 SW Laneinfo、SW Node 与 SW Road，筛选 `LinkID` 存在于 SW Road 的记录，按 `LinkID + Lane_Dir` 将 `Arrow_Dir` 聚合为 Road 方向级 `arrow`，按 `direction / Lane_Dir` 输出 `sw_arrow_tool8.gpkg` 与 summary，不改写输入 | `active` | 否 |
| `t08_tool9_rcsd_cleaning.py` | `scripts/t08_tool9_rcsd_cleaning.py` | repo 级 | T08 Tool9 RCSD 数据清理，读取 RCSDNode、RCSDRoad 与道路面 GPKG，按道路面覆盖语义组、Road 相交与起终点保留状态输出 `rcsdnode_clean_tool9.gpkg / rcsdroad_clean_tool9.gpkg` 与 summary，不改写输入 | `active` | 否 |
| `t08_tool10_trajectory_aggregation.py` | `scripts/t08_tool10_trajectory_aggregation.py` | repo 级 | T08 Tool10 Patch 轨迹聚合，扫描 `<Patch>/Traj/*/raw_dat_pose.geojson`，严格校验 PointZ/CRS，转换 XY 到 `EPSG:3857` 后按距离/时间/序号断点切分，将全部 `LineStringZ` 轨迹段写入单个 `<Patch>/Traj/raw_dat_pose.gpkg` 的 `raw_dat_pose` 图层并输出 `_tool10` summary，不改写输入 | `active` | 否 |
| `t08_tool10_run_patches_innernet.sh` | `scripts/t08_tool10_run_patches_innernet.sh` | repo 级 | T08 Tool10 内网多 Patch 参数化批处理入口；从位置参数读取任意数量 Patch 目录，兼容 WSL 路径和单引号包裹的 Windows 路径，逐 Patch 调用正式 Tool10、记录日志并汇总成功/失败，不内置业务目录 | `active` | 否 |
| `t09_export_step3_input_text_bundle_innernet.sh` | `scripts/t09_export_step3_input_text_bundle_innernet.sh` | repo 级 | T09 内网 Step3 输入单文件文本证据包导出脚本；按中心点与 `SIZE_M` / `RADIUS_M` 空间窗口切片 SWSD nodes / roads / Segment、T08 Tool7 / Tool8 输出和 T06 Step3 FRCSD Road / Node，生成 base85 文本 bundle，超过 250KB 自动分片并可立即解包校验 | `active` | 否 |
| `t10_pack_innernet_cases.sh` | `scripts/t10_pack_innernet_cases.sh` | repo 级 | T10 内网多 Case 证据包正式打包入口；以 SWSD semantic junction id 列表为 CaseID，读取 T10 v1 外部输入 slot，生成 `cases/<case_id>/` 结构的文件证据包并导出可自动分片的文本 bundle，可选立即解包校验 | `active` | 否 |
| `t10_pack_innernet_segments.sh` | `scripts/t10_pack_innernet_segments.sh` | repo 级 | T10 内网多 Segment 证据包正式打包入口；以 SWSD SegmentID 列表为输入，读取既有 `T10_RUN_ROOT` 反查 T01 Segment 与 T06 证据，按 T01 Segment geometry `200m` buffer 生成 `<SegmentID>/` 一级目录结构的文件证据包并导出可自动分片的文本 bundle，可选立即解包校验 | `active` | 否 |
| `t10_run_e2e_cases.sh` | `scripts/t10_run_e2e_cases.sh` | repo 级 | T10 Case 级端到端执行入口；从 Case package 读取局部输入切片，串联 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T11 -> T09` 的既有入口或 callable；T11 为 audit-only 必经阶段，输出 candidates/summary，不改变 T09 对 T06 的业务 handoff；同时输出阶段审计与 T06 数据漏斗，并支持 feedback iteration no-regression guard | `active` | 否 |
| `t10_run_innernet_full_pipeline.sh` | `scripts/t10_run_innernet_full_pipeline.sh` | repo 级 | T10 内网全量端到端总控脚本；默认串联 `T08 -> T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 Step1/2 -> T06 Step3 -> T11 -> T09`，所有阶段写入同一 run root 与 manifest；T07 Step3 仍为显式可选兼容阶段；支持 `FINALIZE_EXISTING` 及 `RESUME_RUN_ROOT / RESUME_FROM_STAGE / RUN_STAGES`，新完成口径要求 passed 的 T11 stage 与 candidates/summary | `active` | 否 |
| `t11_extract_relation_repair_candidates.py` | `scripts/t11_extract_relation_repair_candidates.py` | repo 级 | T11 人工 relation 修复候选抽取入口；由 T10 Case/full runner 在 T06 后、T09 前以 audit-only 阶段调用；兼容单个 `--t10-case-root`，并支持 `--t10-suite-root / --case-ids / --workers` 批量并行处理相互隔离的 Case；输出候选 CSV/GPKG/XLSX、人工模板与 summary JSON，不修改 T05/T06/T09 输入成果 | `active` | 否 |
| `t11_run_manual_rerun.py` | `scripts/t11_run_manual_rerun.py` | repo 级 | T11 人工 Excel 结果消费与重跑入口；读取三张 Segment 审计 Excel，抽取可执行人工 relation 并合并为 T05 `--t11-manual-relation` CSV，随后串联既有 T05、T06 Step1/2 与 T06 Step3 脚本，输出人工导入 summary 与修复前后指标对比，不修改输入 Case root 或 baseline | `active` | 否 |
| `t11_manual_relation_review.innernet_loss_metrics` | `src/rcsd_topo_poc/modules/t11_manual_relation_review/innernet_loss_metrics.py` | 模块级 `python -m` | T11 内网人工重跑损失度量抽取入口；只读指定 T11 manual rerun / T05 / T06 run root，按收益降序输出人工 relation 漏锚、`5_replaceable_scope_unreplaced` road/Segment 聚合和建议打包清单，并默认限制单个输出文件不超过 240KB | `active` | 否 |
| `T11 Relation Review QGIS plugin` | `qgis_plugins/t11_relation_review/__init__.py` | QGIS 插件 | T11 表 2 / 表 3 relation 缺口 Excel 的地图化人工编辑入口；QGIS `classFactory(iface)` 加载左侧任务管理 Dock 与底部任务处理 Dock，单次加载一张审计 Excel，绑定 SWSD/RCSD 图层，从 selection 提取 RCSDNode/RCSDRoad ID，任务定位默认约 `1:1500`，并立即同步写回 Excel 三个人工字段；不新增 CLI 或 scripts 入口 | `active` | 否 |

## 4. 新增入口脚本的准入规则

- 默认禁止新增新的执行入口脚本
- 新入口必须获得任务书明确批准，并补录到本注册表
