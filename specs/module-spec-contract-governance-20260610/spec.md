# Module SPEC Contract Governance Specification

- 文档类型：SpecKit 需求说明书
- 创建日期：2026-06-10
- 分支：`codex/module-spec-contract-governance-20260610`
- 状态：Draft

## 1. 背景

用户已确认模块级文档结构应尽量对齐项目级文档职责模型，并明确：

1. `README.md` 应作为模块阅读入口和文档索引，不承载凝练版模块业务需求正文。
2. `SPEC.md` 应承载凝练版模块业务需求。
3. `architecture/04-solution-strategy.md` 应承载详细版模块业务需求 / 落地策略。
4. `AGENTS.md` 后续应重点审计，只保留项目级规则之外、对当前模块具有独特作用的信息。

本轮先修复除 `T10` 外其他正式启用模块的需求文档契约，并对 `SPEC.md` 与 `architecture/04-solution-strategy.md` 做成果正确性审计。

## 2. 范围

### 2.1 包含

- 目标模块：
  - `modules/t01_data_preprocess`
  - `modules/t03_virtual_junction_anchor`
  - `modules/t04_divmerge_virtual_polygon`
  - `modules/t05_junction_surface_fusion`
  - `modules/t06_segment_fusion_precheck`
  - `modules/t07_semantic_junction_anchor`
  - `modules/t08_preprocess`
  - `modules/t09_swsd_field_rule_restoration`
- 每个目标模块新增或修复：
  - `SPEC.md`：凝练版模块业务需求。
  - `README.md`：模块阅读入口与文档索引。
  - `architecture/04-solution-strategy.md`：详细版需求 / 业务落地策略。
- 在目标模块内部最小同步仍指向旧职责分工的文档引用。
- 同步更新本轮模块文档契约审计材料，使其反映已确认的新职责分工。
- 新增本 SpecKit 工件。

### 2.2 不包含

- 不修改 `modules/t10_e2e_orchestration/**`。
- 不修改 `src/**`、`tests/**`、`scripts/**`、`Makefile` 或入口登记。
- 不改变任何模块官方入口、CLI 参数、输出文件名或算法行为。
- 不删除历史实现、历史基线或现有运行脚本。
- 不处理 `T00 / T02 / P01 / _template`。
- 不对 `AGENTS.md` 做实质性收敛；本轮仅在审计结论中保留后续治理要求。

## 3. 文档契约目标

| 文件 | 职责 | 验收重点 |
|---|---|---|
| `README.md` | 模块阅读入口、当前状态、文档职责表、阅读顺序、入口位置。 | 能帮助读者快速进入正确文档，不承载长篇业务需求。 |
| `SPEC.md` | 凝练版模块业务需求：业务目标、范围、非目标、上下游、输入输出、关键业务步骤、对错边界、治理缺口。 | 能让人和 AI 快速建立模块业务共识。 |
| `architecture/04-solution-strategy.md` | 详细版需求 / 落地策略：按业务步骤解释目的、输入前提、落地策略、输出审计、失败策略和对错边界。 | 不是伪代码或参数堆砌，能解释业务如何真正落地。 |
| `INTERFACE_CONTRACT.md` | 稳定接口契约。 | 本轮不主动重写，只作为事实来源和一致性校验对象。 |

## 4. 正确性要求

### 4.1 产品视角

- `SPEC.md` 必须能回答模块解决什么业务问题、服务哪个下游、什么结果算正确、什么行为算错误。
- 需求表述必须与当前项目级模块盘点一致，不得重新定义模块生命周期或主业务链。

### 4.2 架构视角

- `architecture/04-solution-strategy.md` 必须与当前模块上下游、输入输出和正式范围一致。
- 详细策略只能基于已存在的模块源事实、接口契约、历史 architecture 文档和当前项目级盘点，不得新增未经确认的字段语义或强规则。

### 4.3 研发视角

- 本轮只改文档，不改代码、测试、脚本、入口和登记表。
- `README.md` 只做索引，不替代 `SPEC.md` 或 `INTERFACE_CONTRACT.md`。

### 4.4 测试视角

- 文档验收以路径级检查、关键词检查、结构检查和 `git diff --check` 为主。
- 代码测试不属于本轮必跑项；若未运行，完成回报必须说明。

### 4.5 QA 视角

- 需逐模块审计 `SPEC.md` 与 `architecture/04-solution-strategy.md` 是否同时覆盖业务目标、输入输出、关键步骤、对错边界和风险/失败策略。
- 需确认 `T10` 未被本轮改动触碰。
- 当前工作区已有非本轮 T10 脏改，本轮验证必须用路径级 diff 区分。

## 5. 验收标准

1. 8 个目标模块均存在 `SPEC.md`。
2. 8 个目标模块的 `README.md` 均定位为模块阅读入口与索引。
3. 8 个目标模块的 `architecture/04-solution-strategy.md` 均定位为详细版需求 / 落地策略。
4. `SPEC.md` 与 `architecture/04-solution-strategy.md` 的内容不与项目级模块盘点、模块生命周期和接口契约中的核心口径冲突。
5. 目标模块内部不再把凝练版业务需求指向 `README.md`。
6. `git diff --name-only` 中本轮新增/修改的目标文件不包含 `modules/t10_e2e_orchestration/**`。
7. `git diff --check` 通过。
