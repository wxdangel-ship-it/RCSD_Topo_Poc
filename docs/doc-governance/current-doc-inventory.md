# 当前文档盘点

## 范围

- 盘点日期：2026-04-14
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
| `modules/t00_utility_toolbox/INTERFACE_CONTRACT.md` | T00 稳定契约面 | `source_of_truth` | 固化 Tool1-Tool9 的稳定输入、输出、覆盖、异常与摘要语义 |
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
| `modules/t03_virtual_junction_anchor/architecture/*` | T03 模块长期架构真相 | `source_of_truth` | T03 正式模块的长期文档主表面；当前正式范围只到 Phase A / Step3 |
| `modules/t03_virtual_junction_anchor/INTERFACE_CONTRACT.md` | T03 稳定契约面 | `source_of_truth` | 固化 Anchor61 `case-package` 输入、Step3 A-H、批量输出与 tri-state 状态 |
| `modules/t03_virtual_junction_anchor/README.md` | T03 操作者入口 | `operator_guide` | 说明官方入口、默认路径与当前边界 |
| `modules/t03_virtual_junction_anchor/AGENTS.md` | T03 durable guidance | `durable_guidance` | 只保留模块级边界与执行约束 |
| `specs/t03-virtual-junction-anchor/*` | T03 变更工件 | `active_change_artifact` | 记录 T03 Phase A 变更计划，不替代长期模块真相 |

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
2. 当前已存在正式业务模块文档面：`modules/t01_data_preprocess/*`、`modules/t02_junction_anchor/*` 与 `modules/t03_virtual_junction_anchor/*`。
3. `t00_utility_toolbox` 当前作为已纳入治理的工具集合模块文档面存在。
4. `_template` 继续承担新模块启动模板职责。
5. 模块根目录不放 `SKILL.md` 的规则已经写回仓库级文档。
