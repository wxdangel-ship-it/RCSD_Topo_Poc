# 文档治理入口

本文件是项目文档治理入口，负责说明当前文档体系从哪里读、模块文档如何写、哪些材料只供追溯。业务需求本身不在本文件展开。

## 1. 主阅读顺序

1. 根目录 `README.md`：项目级阅读入口和最短索引。
2. 根目录 `SPEC.md`：项目级简版需求。
3. `docs/PROJECT_REQUIREMENTS.md`：项目级详细需求。
4. `docs/architecture/01~06`：项目级架构、证据、质量和风险说明。
5. `docs/doc-governance/module-lifecycle.md`：模块生命周期事实。
6. `docs/doc-governance/current-module-inventory.md`：模块业务目标、上下游和治理缺口。
7. `docs/doc-governance/current-doc-inventory.md`：项目文档结构和职责盘点。
8. `docs/doc-governance/module-doc-template.md`：模块文档模板与写法规则。

## 2. 模块文档标准结构

模块级文档以 T03 当前结构为标准参考：

| 文档 | 职责 |
|---|---|
| `README.md` | 模块阅读入口和文档索引，只说明当前状态、文档职责、入口类别和推荐阅读顺序。 |
| `SPEC.md` | 模块需求，使用业务语言说明模块定位、业务目标、范围、上下游、输入输出、关键业务步骤、核心场景概念和对错边界。 |
| `INTERFACE_CONTRACT.md` | 稳定接口契约速查，主要给实现、运行、联调和 Agent 维护使用，只保留输入、输出、状态、入口和最小审计字段。 |
| `architecture/01-introduction-and-goals.md` | 模块架构目标、上下文、当前范围、兼容边界和非目标。 |
| `architecture/02-data-and-domain-model.md` | 模块关键输入对象、业务对象、领域分层、字段 / CRS / 数据形态和下游语义。 |
| `architecture/03-solution-strategy.md` | 架构设计 / 需求具体实现策略，按业务步骤说明如何落地；可引用实现构件，但不能用文件名替代业务说明。 |
| `architecture/04-evidence-and-audit.md` | formal、review-only、internal、handoff 等证据层和审计分工。 |
| `architecture/05-quality-requirements.md` | 业务正确性、输出稳定性、review/formal 分层、观测性能和治理要求。 |
| `architecture/06-risks-and-technical-debt.md` | 历史命名、数据质量、入口治理、性能、跨模块 handoff 等风险与技术债。 |
| `history/` | 历史阶段 closeout、旧实验和背景材料，不替代当前需求或契约。 |

模块可保留少量非编号补充文档，例如 T01 的 `architecture/accepted-baseline.md`；这类文档必须在模块 `README.md` 中说明用途，不得替代 01-06 主结构。

## 3. 关键信息写法

- 先写业务目的，再写输入输出和实现策略。
- 关键概念必须说明“回答什么业务问题”，例如 T03 的 `A / B / C` 是 RCSD 关联角色，不是视觉等级。
- 状态字段必须分层说明，避免把中间状态、发布状态和下游 relation 状态混用。
- 参数、字段和值域可以出现，但必须附带业务解释；不得用大段参数表、伪代码或实现文件名替代需求说明。
- 历史命名可以保留，但必须说明它是兼容资产还是当前正式业务主结构。
- review-only、formal、internal 证据必须分开，人工复核结论不得反写为机器正式状态。

## 4. 非主阅读材料

`docs/doc-governance/history/`、`docs/doc-governance/audits/`、`docs/archive/`、`specs/*`、`outputs/*` 都不属于 day-0 主阅读路径。需要追溯历史交付或运行证据时再进入。
