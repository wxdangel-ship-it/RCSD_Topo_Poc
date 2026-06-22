# <module_id> 治理摘要

## 当前正式定位

- 当前模块：`modules/<module_id>`
- 当前角色：`<补充>`
- 当前文档分层：
  - `SPEC.md`：模块需求
  - `architecture/*`：架构设计
  - `INTERFACE_CONTRACT.md`：稳定契约
  - `AGENTS.md`：可选 Agent 局部红线
  - repo root `.agents/skills/<skill-name>/SKILL.md`：标准可复用流程
  - `README.md`：模块阅读入口

## 当前标准文档面

### 启动时必建

- `SPEC.md`
- `README.md`
- `INTERFACE_CONTRACT.md`
- `architecture/01-introduction-and-goals.md`
- `architecture/03-solution-strategy.md`

### 建议尽早补齐

- `architecture/02-data-and-domain-model.md`
- `architecture/04-evidence-and-audit.md`
- `architecture/05-quality-requirements.md`
- `architecture/06-risks-and-technical-debt.md`
- `AGENTS.md`（仅当模块存在项目级规则无法覆盖的特殊红线时）

### 模块成熟后补齐

- `review-summary.md`
- `history/README.md`
- `scripts/README.md`（仅当模块确有获批模块内脚本时）

说明：

- 本文件是建议文档，通常在模块进入正式化阶段后补齐。
