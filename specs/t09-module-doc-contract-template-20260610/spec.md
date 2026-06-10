# T09 Module Documentation Surface And Contract Template Specification

- 文档类型：SpecKit 需求说明书
- 创建日期：2026-06-10
- 分支：`codex/t09-module-doc-contract-template-20260610`
- 状态：Draft

## 1. 背景

用户要求先完成两件事：

1. 补齐 `t09_swsd_field_rule_restoration` 的模块级文档面。
2. 统一模块级文档契约模板，使后续模块治理具备“凝练版需求说明”和“详细版需求说明”两层人类握手文档。

本轮只做模块级文档契约治理，不修改 T09 实现、测试、repo CLI、root scripts、Makefile 或入口登记。

## 2. 范围

### 2.1 包含

- 新增 `modules/t09_swsd_field_rule_restoration/` 文档面。
- 更新 `modules/_template/`，明确模块文档契约分工。
- 同步项目级文档盘点、模块生命周期、模块文档状态表和项目级风险文档中 T09 的缺口状态。
- 按用户授权，最小同步 T10 中关于“T09 模块文档面缺失”的过期引用。
- 新增本 SpecKit 工件。

### 2.2 不包含

- 不修改 `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/**`。
- 不修改 `tests/modules/t09_swsd_field_rule_restoration/**`。
- 不新增 repo CLI、root `scripts/`、Makefile 目标或模块 `run.py` / `__main__.py`。
- 不重构 T01 / T03 / T04 / T05 / T06 / T07 / T08 / T10 既有模块文档；T10 仅允许同步 T09 文档面缺口已关闭的 stale reference。

## 3. 文档契约目标

每个正式模块后续应具备两类面向人的需求说明：

| 层级 | 承载文件 | 目的 |
|---|---|---|
| 凝练版需求说明 | `README.md` | 让读者快速理解模块业务目标、上下游、输入输出、关键步骤，以及什么是对 / 错。 |
| 详细版需求说明 | `architecture/04-solution-strategy.md` | 用中文展开每个业务步骤的落地策略、判定逻辑、输出和审计要求。 |

同时保留面向稳定接口和 AI / AI 审计的文档：

| 文件 | 职责 |
|---|---|
| `INTERFACE_CONTRACT.md` | 稳定输入、输出、入口、参数类别和验收口径。 |
| `architecture/05-building-block-view.md` | 实现构件与职责映射。 |
| `architecture/10-quality-requirements.md` | 质量、审计、GIS / 拓扑、性能要求。 |
| `architecture/11-risks-and-technical-debt.md` | 风险、缺口和技术债。 |
| `AGENTS.md` | 模块级执行规则，不承载业务真相。 |

## 4. 验收标准

- T09 具备 `AGENTS.md`、`README.md`、`INTERFACE_CONTRACT.md` 和 architecture 文档。
- T09 `README.md` 能作为凝练版需求说明独立阅读。
- T09 `architecture/04-solution-strategy.md` 能作为详细版需求说明说明 Step1/2/3 的业务落地逻辑。
- `_template` 明确上述分工，并能作为后续模块治理模板。
- 项目级盘点不再将 T09 标记为缺少模块文档面。
- `git diff --check` 通过。
