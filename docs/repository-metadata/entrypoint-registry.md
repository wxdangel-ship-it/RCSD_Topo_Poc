# 当前执行入口注册表

## 1. 文档目的

登记当前仓库已识别的执行入口脚本与入口文件。

## 2. 当前登记摘要

- 当前共识别 `27` 个执行入口文件
- 分布概览：
  - repo 级 / 工具级：`25`

## 3. 当前已识别入口清单

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `Makefile` | `Makefile` | repo 级 | 仓库级测试入口 | `active` | 否 |
| `agent_enter.sh` | `scripts/agent_enter.sh` | repo 级 | 进入仓库后的标准握手辅助 | `active` | 否 |
| `t01_pull_from_internal_github.sh` | `scripts/t01_pull_from_internal_github.sh` | repo 级 | T01 部署机从内网 Git 远端 clone/fetch/pull 主干 | `active` | 否 |
| `t01_run_full_data_skill_v1.sh` | `scripts/t01_run_full_data_skill_v1.sh` | repo 级 | T01 accepted runner 全量执行脚本 | `active` | 否 |
| `t02_run_stage3_full_input_8workers.sh` | `scripts/t02_run_stage3_full_input_8workers.sh` | repo 级 | T02 stage3 full-input 8 线程自动发现运行包装脚本 | `active` | 否 |
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
| `t02-export-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 单 mainnodeid 文本证据包导出入口 | `active` | 否 |
| `t02-decode-text-bundle` | `src/rcsd_topo_poc/cli.py` | repo 级 | T02 单 mainnodeid 文本证据包解包入口 | `active` | 否 |
| `t00_tool1_patch_directory_bootstrap.py` | `scripts/t00_tool1_patch_directory_bootstrap.py` | repo 级 | T00 Tool1 固定脚本 | `active` | 否 |
| `t00_tool2_drivezone_merge.py` | `scripts/t00_tool2_drivezone_merge.py` | repo 级 | T00 Tool2 DriveZone 预处理与合并 | `active` | 否 |
| `t00_tool3_intersection_merge.py` | `scripts/t00_tool3_intersection_merge.py` | repo 级 | T00 Tool3 Intersection 预处理与汇总 | `active` | 否 |
| `t00_tool4_a200_patch_join.py` | `scripts/t00_tool4_a200_patch_join.py` | repo 级 | T00 Tool4 A200 road 增加 patch_id | `active` | 否 |
| `t00_tool5_a200_kind_enrich.py` | `scripts/t00_tool5_a200_kind_enrich.py` | repo 级 | T00 Tool5 A200 road 增加 kind | `active` | 否 |
| `t00_tool6_node_export.py` | `scripts/t00_tool6_node_export.py` | repo 级 | T00 Tool6 shp 导出 GeoJSON | `active` | 否 |
| `t00_tool7_geojson_to_gpkg.py` | `scripts/t00_tool7_geojson_to_gpkg.py` | repo 级 | T00 Tool7 顶层目录 GeoJSON 批量转 GPKG | `active` | 否 |

## 4. 新增入口脚本的准入规则

- 默认禁止新增新的执行入口脚本
- 新入口必须获得任务书明确批准，并补录到本注册表
