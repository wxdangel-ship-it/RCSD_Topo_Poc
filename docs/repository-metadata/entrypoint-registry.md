# 当前执行入口注册表

## 1. 文档目的

本文档用于登记当前仓库中已识别的执行入口脚本与入口文件。

## 2. 当前登记摘要

- 当前共识别 `8` 个执行入口文件
- 分布概览：
  - repo 级 / 工具级：`8`

## 3. 当前已识别入口清单

| 名称 | 路径 | 类型 | 适用范围 | 当前状态 | 是否建议后续收敛 |
|---|---|---|---|---|---|
| `Makefile` | `Makefile` | repo 级 | 仓库级测试入口 | `active` | 否 |
| `agent_enter.sh` | `scripts/agent_enter.sh` | repo 级 | 进入仓库后的标准握手辅助 | `active` | 否 |
| `python -m rcsd_topo_poc` | `src/rcsd_topo_poc/__main__.py` | repo 级 | 仓库级 Python 包入口 | `active` | 否 |
| `t01-run-skill-v1` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Skill v1.0.0 官方 end-to-end 入口 | `active` | 否 |
| `t01-compare-freeze` | `src/rcsd_topo_poc/cli.py` | repo 级 | T01 Skill v1.0.0 freeze compare 入口 | `active` | 否 |
| `t00_tool1_patch_directory_bootstrap.py` | `scripts/t00_tool1_patch_directory_bootstrap.py` | repo 级 | T00 Tool1 内网固定执行脚本 | `active` | 否 |
| `t00_tool2_drivezone_merge.py` | `scripts/t00_tool2_drivezone_merge.py` | repo 级 | T00 Tool2 全量 DriveZone 预处理与汇总输出 | `active` | 否 |
| `t00_tool3_intersection_merge.py` | `scripts/t00_tool3_intersection_merge.py` | repo 级 | T00 Tool3 全量 Intersection 预处理与汇总 | `active` | 否 |

## 4. 新增入口脚本的准入规则

- 默认禁止新增新的执行入口脚本。
- 新入口必须获得任务书明确批准，并补录到本注册表。
