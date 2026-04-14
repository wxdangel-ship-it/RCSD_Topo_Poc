# 当前执行入口注册表

## 1. 文档目的

登记当前仓库已识别的执行入口脚本与入口文件。

## 2. 当前登记摘要

- 当前共识别 `42` 个执行入口文件
- 分布概览：
  - repo 级 / 工具级：`36`

## 3. 当前已识别入口清单

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `Makefile` | `Makefile` | repo 级 | 仓库级测试入口 | `active` | 否 |
| `agent_enter.sh` | `scripts/agent_enter.sh` | repo 级 | 进入仓库后的标准握手辅助 | `active` | 否 |
| `t01_pull_from_internal_github.sh` | `scripts/t01_pull_from_internal_github.sh` | repo 级 | T01 部署机从内网 Git 远端 clone/fetch/pull 主干 | `active` | 否 |
| `t01_run_full_data_skill_v1.sh` | `scripts/t01_run_full_data_skill_v1.sh` | repo 级 | T01 accepted runner 全量执行脚本 | `active` | 否 |
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
| `python -m rcsd_topo_poc` | `src/rcsd_topo_poc/__main__.py` | repo 级 | Python 包入口 | `active` | 否 |
| `t01-step1-pair-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step1 pair candidate 诊断入口 | `active` | 否 |
| `t01-step2-segment-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step2 validated/trunk/segment_body 诊断入口 | `active` | 否 |
| `t01-build-validation-slices` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 validation slice 构建入口 | `active` | 否 |
| `t01-s2-refresh-node-road` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step3 refresh 节点/道路刷新入口 | `active` | 否 |
| `t01-step4-residual-graph` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step4 residual graph 入口 | `active` | 否 |
| `t01-step5-staged-residual-graph` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step5A/5B/5C staged residual graph 入口 | `active` | 否 |
| `t01-run-skill-v1` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Skill v1 end-to-end 入口 | `active` | 否 |
| `t01-step6-segment-aggregation-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Step6 segment 聚合入口 | `active` | 否 |
| `t01-compare-freeze` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 freeze compare 入口 | `active` | 否 |
| `t02-stage1-drivezone-gate` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 stage1 DriveZone / has_evd gate 入口 | `active` | 否 |
| `t02-virtual-intersection-poc` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 stage3 虚拟路口锚定 baseline 入口（`case-package` + `full-input`） | `active` | 否 |
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
| `t00_tool10_json_point_export.py` | `scripts/t00_tool10_json_point_export.py` | repo 级 | T00 Tool10 超大 JSON 点记录流式转点 GPKG | `active` | 否 |

## 4. 新增入口脚本的准入规则

- 默认禁止新增新的执行入口脚本
- 新入口必须获得任务书明确批准，并补录到本注册表
