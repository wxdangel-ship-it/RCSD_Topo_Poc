# 当前文档盘点

## 范围

- 盘点日期：2026-03-22
- 目的：说明当前主阅读路径、标准文档位置、正式模块文档面与模板入口

## 当前主入口文档

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `AGENTS.md` | repo 级 durable guidance 入口 | `durable_guidance` | 只保留仓库级稳定规则 |
| `SPEC.md` | 项目级总规格入口 | `source_of_truth` | 项目级最高优先级规格 |
| `.specify/memory/constitution.md` | 宪章 | `constitution` | 约束长期文档与流程原则 |
| `docs/PROJECT_BRIEF.md` | 项目摘要入口 | `source_of_truth` / `digest` | 只提供稳定摘要 |
| `docs/ARTIFACT_PROTOCOL.md` | 文本回传协议 | `source_of_truth` | 约束文本回传形态 |
| `docs/architecture/*.md` | 项目级长期架构说明 | `source_of_truth` | 当前项目级长期真相主表面 |
| `docs/repository-metadata/README.md` | 仓库结构入口 | `durable_guidance` | 说明从哪里理解当前仓库结构 |
| `docs/doc-governance/README.md` | 治理主入口 | `durable_guidance` | 告诉维护者当前从哪里开始看治理文档 |
| `docs/doc-governance/module-lifecycle.md` | 模块生命周期真相 | `source_of_truth` | 定义业务模块状态类别 |
| `docs/doc-governance/current-module-inventory.md` | 当前模块盘点 | `source_of_truth` / `durable_guidance` | 说明当前正式模块与模板资产 |
| `docs/doc-governance/current-doc-inventory.md` | 当前文档盘点 | `source_of_truth` / `durable_guidance` | 解释当前文档分层与位置 |
| `docs/doc-governance/module-doc-status.csv` | 模块文档状态总表 | `source_of_truth` / `durable_guidance` | 记录模板资产与正式模块文档状态 |

## 当前正式模块文档面

| 路径 | 当前角色 | 主要属性 | 说明 |
|---|---|---|---|
| `modules/t02_junction_anchor/architecture/*` | T02 模块长期架构真相 | `source_of_truth` | T02 正式模块的长期文档主表面 |
| `modules/t02_junction_anchor/INTERFACE_CONTRACT.md` | T02 稳定契约面 | `source_of_truth` | 固化 stage1、stage2 与单 `mainnodeid` 受控实验入口的输入、输出、入口、参数类别与验收标准 |
| `modules/t02_junction_anchor/README.md` | T02 操作者入口 | `operator_guide` | 说明官方运行入口、受控实验入口、常见运行方式与关键产物 |
| `modules/t02_junction_anchor/AGENTS.md` | T02 durable guidance | `durable_guidance` | 只保留模块级执行边界与协作规则 |
| `modules/t02_junction_anchor/history/*` | T02 模块级历史材料 | `history` | 记录 bootstrap 与后续演进轨迹 |
| `specs/t02-junction-anchor/*` | T02 变更工件 | `active_change_artifact` | 记录本轮与前序轮次的变更规格，不替代长期模块真相 |

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

1. 主阅读路径已经收口到项目级源事实、治理入口、结构元数据、T02 正式模块文档面与模块模板。
2. 当前已存在正式业务模块文档面：`modules/t02_junction_anchor/*`。
3. `_template` 继续承担新模块启动模板职责。
4. 模块根目录不放 `SKILL.md` 的规则已经写回仓库级文档。
