# 当前执行入口注册表

## 1. 文档目的

登记当前仓库已识别的执行入口脚本与入口文件。

## 2. 当前登记摘要

- 当前真实执行入口共 `67` 个。
- 分布概览：
  - repo 级入口文件：`43`（`Makefile` 1 + `scripts/` 41 + `.venv/bin/python -m rcsd_topo_poc` 1）
  - CLI 稳定子命令：`24`
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
| `t03_run_internal_full_input_8workers.sh` | `scripts/t03_run_internal_full_input_8workers.sh` | repo 级 | T03 模块级内网 full-input 全量运行主脚本；外层 shell 结构与 public env surface 镜像 T02 Stage3 内网模板，内部主链为 candidate discovery / shared handle preload / per-case local context query / direct Step1~Step7 case execution，并在 `.venv/bin/python` 关键依赖不可用时自动 fallback 到 `python3`；当前 `_internal/<RUN_ID>/` 已拆分为 `t03_internal_full_input_manifest/progress/performance/failure` 等模块级 observability 工件，批次根目录正式成果至少包括 `virtual_intersection_polygons.gpkg`、downstream `nodes.gpkg` 与 `t03_review_*` review-only 输出 | `active` | 否 |
| `t03_watch_internal_full_input.sh` | `scripts/t03_watch_internal_full_input.sh` | repo 级 | T03 模块级内网 full-input 实时跟踪主脚本；当前作为 T03 internal full-input 的正式 repo 级监控面，默认按 formal-first 口径显示 `total / completed / running / pending / success / failed`（其中 `success = accepted`、`failed = rejected + runtime_failed`）与执行阶段信息，只有 `DEBUG_VISUAL=1` 时才从 review-only 工件读取 V1-V5 统计 | `active` | 否 |
| `t03_run_internal_full_input_innernet.sh` | `scripts/t03_run_internal_full_input_innernet.sh` | repo 级 | T03 internal full-input 内网运行包装脚本，设置 innernet 默认运行参数后转发到 `t03_run_internal_full_input_8workers.sh` | `active` | 否 |
| `t03_run_internal_full_input_innernet_flat_review.sh` | `scripts/t03_run_internal_full_input_innernet_flat_review.sh` | repo 级 | T03 internal full-input 内网 flat-review 运行包装脚本，写入 latest run id 并转发到 `t03_run_internal_full_input_8workers.sh` | `active` | 否 |
| `t03_watch_internal_full_input_innernet.sh` | `scripts/t03_watch_internal_full_input_innernet.sh` | repo 级 | T03 internal full-input 内网监控包装脚本，设置默认监控参数后转发到 `t03_watch_internal_full_input.sh` | `active` | 否 |
| `t03_watch_internal_full_input_innernet_flat_review.sh` | `scripts/t03_watch_internal_full_input_innernet_flat_review.sh` | repo 级 | T03 internal full-input 内网 flat-review 监控包装脚本，从 latest run id 文件发现 RUN_ID 后转发到 `t03_watch_internal_full_input.sh` | `active` | 否 |
| `t04_run_internal_full_input_8workers.sh` | `scripts/t04_run_internal_full_input_8workers.sh` | repo 级 | T04 模块级内网 full-input 全量运行主脚本；输入全局 `nodes/roads/DriveZone/DivStripZone/RCSDRoad/RCSDNode`，执行 preflight / candidate discovery / shared bootstrap / direct Step1-7 case execution / batch closeout，并输出 `divmerge_virtual_anchor_surface*` 正式成果与 `visual_checks/final_*` 最终平铺目视审计入口；不新增 repo 官方 CLI 子命令 | `active` | 否 |
| `t04_watch_internal_full_input.sh` | `scripts/t04_watch_internal_full_input.sh` | repo 级 | T04 内网 full-input 实时监控脚本；显示 `selected / completed / running / pending / accepted / rejected / runtime_failed / missing_status`、phase/status/message/entered_case_execution 与性能估算，并支持 `CASE_SCAN=auto/on/off` 降扫描 | `active` | 否 |
| `t04_run_internal_full_input_innernet_flat_review.sh` | `scripts/t04_run_internal_full_input_innernet_flat_review.sh` | repo 级 | T04 内网 full-input 最终平铺目视审计运行包装；默认关闭 debug、启用 resume/retry/perf audit、使用 failed_only snapshot，并转发到 `t04_run_internal_full_input_8workers.sh` | `active` | 否 |
| `.venv/bin/python -m rcsd_topo_poc` | `src/rcsd_topo_poc/__main__.py` | repo 级 | Python 包入口 | `active` | 否 |
| `doctor` | `src/rcsd_topo_poc/cli.py` | repo 级 | 检查 repo / docs / repo `.venv` / 锁文件 / 运行与开发依赖是否齐备 | `active` | 否 |
| `qc-template` | `src/rcsd_topo_poc/cli.py` | repo 级 | 打印 `TEXT_QC_BUNDLE v1` 模板 | `active` | 否 |
| `qc-demo` | `src/rcsd_topo_poc/cli.py` | repo 级 | 打印可粘贴、截断版 `TEXT_QC_BUNDLE` 示例 | `active` | 否 |
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

## 4. 新增入口脚本的准入规则

- 默认禁止新增新的执行入口脚本
- 新入口必须获得任务书明确批准，并补录到本注册表
